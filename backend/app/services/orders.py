"""Order pricing, validation and creation.

The backend is the source of truth: every submission re-prices every line,
re-checks stock (inside a row lock) and re-checks credit, regardless of what the
browser showed. AI-captured orders go through exactly the same path.

Policies (documented as assumptions in the TDD):
  * Stock: paid + free cases must be available. Stock is reserved when the
    order is submitted and released if the desk rejects it.
  * Credit: exposure = outstanding balance + open orders (pending review /
    approved). If the new order would exceed the credit limit it is still
    accepted but placed ON HOLD with a reason for the order desk.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.money import ZERO, money
from app.models import AiExtraction, Order, OrderItem, OrderStatus, Product, Retailer, User
from app.services import audit
from app.services.aliases import upsert_sku_alias, upsert_unit_alias
from app.services.ai.parsing import CASE_WORDS, PIECE_WORDS, contains_phrase, normalize, parse_segment, tokenize
from app.services.catalogue import (
    active_scheme,
    inventory_for_update,
    load_products,
    price_for,
    retailer_prices,
    stock_status,
)
from app.services.scheme_engine import InvalidQuantity, LineCalculation, calculate_line


@dataclass
class LineInput:
    sku_code: str
    paid_qty: int
    original_phrase: str | None = None
    unit_confirmed: bool = True
    remember_product_alias: bool = False
    unit_alias: str | None = None
    remember_unit_alias: bool = False


@dataclass
class PricedLine:
    input: LineInput
    product: Product
    calc: LineCalculation
    available_cases: int


@dataclass
class Issue:
    code: str
    message: str
    sku_code: str | None = None
    blocking: bool = True

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "sku_code": self.sku_code, "blocking": self.blocking}


@dataclass
class PricingResult:
    lines: list[PricedLine] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.blocking]


def price_lines(
    db: Session, retailer: Retailer, lines: list[LineInput], *, lock: bool, on: date | None = None
) -> PricingResult:
    settings = get_settings()
    result = PricingResult()
    if not lines:
        result.issues.append(Issue("empty_order", "Add at least one product to the order."))
        return result
    if len(lines) > settings.max_lines_per_order:
        result.issues.append(Issue("too_many_lines", f"An order can have at most {settings.max_lines_per_order} lines."))
        return result

    seen: set[str] = set()
    for li in lines:
        if li.sku_code in seen:
            result.issues.append(
                Issue("duplicate_sku", "This product appears more than once. Combine the quantities into one line.", li.sku_code)
            )
        seen.add(li.sku_code)

    products = {p.sku_code: p for p in load_products(db)}
    wanted = [products[li.sku_code] for li in lines if li.sku_code in products]
    overrides = retailer_prices(db, retailer, [p.id for p in wanted])
    inventory = (
        inventory_for_update(db, [p.id for p in wanted])
        if lock
        else {p.id: p.inventory for p in wanted if p.inventory is not None}
    )

    for li in lines:
        product = products.get(li.sku_code)
        if product is None:
            result.issues.append(Issue("unknown_sku", "This product is not in the catalogue.", li.sku_code))
            continue
        try:
            calc = calculate_line(
                li.paid_qty,
                price_for(product, overrides),
                product.gst_rate,
                product.gst_inclusive,
                active_scheme(product, on),
                on=on,
                max_qty=settings.max_qty_per_line,
            )
        except InvalidQuantity as exc:
            result.issues.append(Issue("invalid_quantity", str(exc), li.sku_code))
            continue
        inv = inventory.get(product.id)
        available = inv.available_cases if inv is not None else 0
        if available <= 0:
            result.issues.append(
                Issue("out_of_stock", f"{product.name} is out of stock. Remove it to continue.", li.sku_code)
            )
        elif calc.fulfil_qty > available:
            extra = f" ({calc.paid_qty} paid + {calc.free_qty} free)" if calc.free_qty else ""
            result.issues.append(
                Issue(
                    "insufficient_stock",
                    f"Only {available} cases of {product.name} are available; this line needs {calc.fulfil_qty}{extra}.",
                    li.sku_code,
                )
            )
        result.lines.append(PricedLine(input=li, product=product, calc=calc, available_cases=max(available, 0)))
    return result


def order_totals(lines: list[PricedLine] | list[LineCalculation]) -> dict:
    calcs = [l.calc if isinstance(l, PricedLine) else l for l in lines]
    return {
        "subtotal": sum((c.gross_amount for c in calcs), ZERO),
        "discount_total": sum((c.discount_amount for c in calcs), ZERO),
        "taxable_total": sum((c.taxable_amount for c in calcs), ZERO),
        "tax_total": sum((c.tax_amount for c in calcs), ZERO),
        "grand_total": sum((c.line_total for c in calcs), ZERO),
        "paid_cases": sum(c.paid_qty for c in calcs),
        "free_cases": sum(c.free_qty for c in calcs),
    }


def open_orders_total(db: Session, retailer_id: int, exclude_order_id: int | None = None) -> Decimal:
    stmt = select(func.coalesce(func.sum(Order.grand_total), 0)).where(
        Order.retailer_id == retailer_id, Order.status.in_(OrderStatus.CREDIT_EXPOSURE)
    )
    if exclude_order_id is not None:
        stmt = stmt.where(Order.id != exclude_order_id)
    return money(db.execute(stmt).scalar_one())


def credit_check(db: Session, retailer: Retailer, order_total: Decimal, exclude_order_id: int | None = None) -> dict:
    open_total = open_orders_total(db, retailer.id, exclude_order_id)
    available = money(retailer.credit_limit - retailer.outstanding_balance - open_total)
    return {
        "credit_limit": money(retailer.credit_limit),
        "outstanding_balance": money(retailer.outstanding_balance),
        "open_orders_total": open_total,
        "available_credit": available,
        "order_total": money(order_total),
        "within_limit": money(order_total) <= available,
    }


def credit_hold_reason(credit: dict) -> str:
    return (
        f"Credit limit exceeded: order total Rs {credit['order_total']} is more than available credit "
        f"Rs {credit['available_credit']} (limit Rs {credit['credit_limit']}, outstanding Rs "
        f"{credit['outstanding_balance']}, open orders Rs {credit['open_orders_total']})."
    )


def line_payload(pl: PricedLine) -> dict:
    c = pl.calc
    return {
        "sku_code": pl.product.sku_code,
        "product_id": pl.product.id,
        "name": pl.product.name,
        "pack_size": pl.product.pack_size_label,
        "paid_qty": c.paid_qty,
        "free_qty": c.free_qty,
        "fulfil_qty": c.fulfil_qty,
        "unit_price": c.unit_price,
        "gross_amount": c.gross_amount,
        "discount_percent": c.discount_percent,
        "discount_amount": c.discount_amount,
        "taxable_amount": c.taxable_amount,
        "gst_rate": c.gst_rate,
        "gst_inclusive": c.gst_inclusive,
        "tax_amount": c.tax_amount,
        "line_total": c.line_total,
        "scheme_applied": c.scheme_applied,
        "hints": c.hints,
        "available_cases": pl.available_cases,
        "stock_status": stock_status(pl.available_cases),
        "original_phrase": pl.input.original_phrase,
    }


def preview_order(db: Session, retailer: Retailer, lines: list[LineInput]) -> dict:
    priced = price_lines(db, retailer, lines, lock=False)
    totals = order_totals(priced.lines)
    credit = credit_check(db, retailer, totals["grand_total"])
    warnings: list[str] = []
    if not credit["within_limit"] and priced.lines:
        warnings.append(
            "This order is more than your available credit. You can still submit it, but it will be placed "
            "on hold until the order desk reviews it."
        )
    return {
        "lines": [line_payload(pl) for pl in priced.lines],
        "issues": [i.as_dict() for i in priced.issues],
        "totals": totals,
        "credit": credit,
        "can_submit": not priced.blocking,
        "will_be_held": bool(priced.lines) and not credit["within_limit"],
        "warnings": warnings,
    }


def _validate_ai_extraction(db: Session, retailer: Retailer, extraction_id: int, lines: list[LineInput]) -> AiExtraction:
    extraction = db.get(AiExtraction, extraction_id, with_for_update=True, populate_existing=True)
    if extraction is None or extraction.retailer_id != retailer.id:
        raise AppError(404, "not_found", "AI extraction not found.")
    if extraction.status == "confirmed":
        raise AppError(409, "already_confirmed", "These AI lines have already been confirmed as an order.")
    if extraction.status != "extracted":
        raise AppError(409, "extraction_not_usable", "This AI extraction failed. Please run the extraction again.")
    unconfirmed = [li.sku_code for li in lines if not li.unit_confirmed]
    if unconfirmed:
        raise AppError(
            422,
            "unit_not_confirmed",
            "Confirm the unit (cases) for every line before placing the order.",
            details={"sku_codes": unconfirmed},
        )
    for li in lines:
        if li.original_phrase and not contains_phrase(extraction.original_message, li.original_phrase):
            raise AppError(
                422, "phrase_mismatch", "An original phrase does not appear in the AI message.", {"sku_code": li.sku_code}
            )
    return extraction


def _remember_aliases(db: Session, user: User, retailer: Retailer, extraction: AiExtraction, priced: PricingResult) -> None:
    message_tokens = set(tokenize(extraction.original_message))
    for pl in priced.lines:
        li = pl.input
        if li.remember_product_alias and li.original_phrase:
            phrase = parse_segment(li.original_phrase).product_phrase
            upsert_sku_alias(
                db,
                retailer_id=retailer.id,
                alias_text=phrase,
                product_id=pl.product.id,
                source="retailer_confirmed",
                user_id=user.id,
            )
        if li.remember_unit_alias and li.unit_alias:
            word = normalize(li.unit_alias)
            if word in message_tokens and word not in CASE_WORDS | PIECE_WORDS:
                upsert_unit_alias(
                    db, retailer_id=retailer.id, alias_text=word, unit="case", source="retailer_confirmed", user_id=user.id
                )


def create_order(
    db: Session,
    user: User,
    retailer: Retailer,
    *,
    client_request_id: str,
    lines: list[LineInput],
    ai_extraction_id: int | None = None,
) -> tuple[Order, bool]:
    """Create an order after explicit confirmation. Returns (order, created)."""
    existing = db.scalar(
        select(Order).where(Order.retailer_id == retailer.id, Order.client_request_id == client_request_id)
    )
    if existing is not None:
        return existing, False  # idempotent replay of a double-submitted request

    try:
        extraction = None
        if ai_extraction_id is not None:
            extraction = _validate_ai_extraction(db, retailer, ai_extraction_id, lines)

        # Lock the retailer row so two concurrent orders cannot both pass the credit check.
        locked_retailer = db.get(Retailer, retailer.id, with_for_update=True, populate_existing=True)
        assert locked_retailer is not None
        priced = price_lines(db, locked_retailer, lines, lock=True)
        if priced.blocking:
            raise AppError(
                422,
                "order_invalid",
                "Some lines need attention before this order can be placed.",
                details=[i.as_dict() for i in priced.issues],
            )

        totals = order_totals(priced.lines)
        credit = credit_check(db, locked_retailer, totals["grand_total"])
        status = OrderStatus.PENDING_REVIEW if credit["within_limit"] else OrderStatus.ON_HOLD

        order = Order(
            retailer_id=locked_retailer.id,
            status=status,
            source="ai" if extraction else "manual",
            client_request_id=client_request_id,
            subtotal=totals["subtotal"],
            discount_total=totals["discount_total"],
            taxable_total=totals["taxable_total"],
            tax_total=totals["tax_total"],
            grand_total=totals["grand_total"],
            hold_reason=None if credit["within_limit"] else credit_hold_reason(credit),
            credit_snapshot={k: (str(v) if isinstance(v, Decimal) else v) for k, v in credit.items()},
            ai_extraction_id=extraction.id if extraction else None,
            created_by_user_id=user.id,
        )
        db.add(order)
        db.flush()
        order.order_number = f"ORD-{order.created_at:%y%m%d}-{order.id:05d}"

        inventory = inventory_for_update(db, [pl.product.id for pl in priced.lines])
        for pl in priced.lines:
            c = pl.calc
            order.items.append(
                OrderItem(
                    product_id=pl.product.id,
                    sku_code=pl.product.sku_code,
                    product_name=pl.product.name,
                    paid_qty=c.paid_qty,
                    free_qty=c.free_qty,
                    unit_price=c.unit_price,
                    gross_amount=c.gross_amount,
                    discount_percent=c.discount_percent,
                    discount_amount=c.discount_amount,
                    taxable_amount=c.taxable_amount,
                    gst_rate=c.gst_rate,
                    gst_inclusive=c.gst_inclusive,
                    tax_amount=c.tax_amount,
                    line_total=c.line_total,
                    scheme_applied=c.scheme_applied,
                    original_phrase=pl.input.original_phrase,
                )
            )
            inventory[pl.product.id].available_cases -= c.fulfil_qty  # reservation

        if extraction is not None:
            _remember_aliases(db, user, locked_retailer, extraction, priced)
            extraction.status = "confirmed"
            extraction.order_id = order.id

        audit.record(
            db,
            actor_user_id=user.id,
            entity_type="order",
            entity_id=order.id,
            action="created",
            after={
                "status": status,
                "source": order.source,
                "grand_total": order.grand_total,
                "lines": [{"sku": pl.product.sku_code, "paid": pl.calc.paid_qty, "free": pl.calc.free_qty} for pl in priced.lines],
            },
            note=order.hold_reason,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Order).where(Order.retailer_id == retailer.id, Order.client_request_id == client_request_id)
        )
        if existing is not None:
            return existing, False
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    return order, True
