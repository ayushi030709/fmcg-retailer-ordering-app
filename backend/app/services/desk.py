"""Order-desk workflow: queue, detail, status transitions and line corrections.

Status workflow (assumption A6):

    pending_review --approve--> approved --export--> exported
         |   ^                     |
       hold  release             hold / reject
         v   |                     v
        on_hold --approve (override note required)--> approved
         |
       reject --> rejected   (reserved stock is released)

Every change bumps ``orders.version``; the client must send the version it saw,
so two desk users cannot silently overwrite each other (HTTP 409 instead).
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.models import AiExtraction, AuditEvent, Order, OrderItem, OrderStatus, Product, Retailer, User
from app.services import audit
from app.services.aliases import upsert_sku_alias
from app.services.ai.parsing import parse_segment
from app.services.catalogue import active_scheme, inventory_for_update, price_for, retailer_prices
from app.services.orders import credit_check, credit_hold_reason, order_totals
from app.services.scheme_engine import InvalidQuantity, calculate_line

S = OrderStatus
IST = ZoneInfo("Asia/Kolkata")  # the desk works in Indian time; date filters are IST calendar days
TRANSITIONS: dict[str, dict[str, str]] = {
    "approve": {S.PENDING_REVIEW: S.APPROVED, S.ON_HOLD: S.APPROVED},
    "hold": {S.PENDING_REVIEW: S.ON_HOLD, S.APPROVED: S.ON_HOLD},
    "release": {S.ON_HOLD: S.PENDING_REVIEW},
    "reject": {S.PENDING_REVIEW: S.REJECTED, S.ON_HOLD: S.REJECTED, S.APPROVED: S.REJECTED},
}
EDITABLE = (S.PENDING_REVIEW, S.ON_HOLD)


def allowed_actions(order: Order) -> list[str]:
    actions = [a for a, t in TRANSITIONS.items() if order.status in t]
    if order.status in EDITABLE:
        actions.append("correct")
    return actions


def list_orders(
    db: Session,
    *,
    status: str | None,
    retailer_id: int | None,
    date_from,
    date_to,
    q: str | None,
    limit: int,
    offset: int,
) -> dict:
    filters = []
    if retailer_id:
        filters.append(Order.retailer_id == retailer_id)
    if date_from:
        filters.append(Order.created_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=IST).astimezone(timezone.utc))
    if date_to:
        filters.append(Order.created_at <= datetime.combine(date_to, datetime.max.time(), tzinfo=IST).astimezone(timezone.utc))
    if q and q.strip():
        like = f"%{q.strip()}%"
        shops = select(Retailer.id).where(Retailer.shop_name.ilike(like))
        filters.append(or_(Order.order_number.ilike(like), Order.retailer_id.in_(shops)))
    # Counts per status ignore the status filter so the UI can show tab badges.
    counts = dict(db.execute(select(Order.status, func.count(Order.id)).where(*filters).group_by(Order.status)).all())
    if status:
        filters.append(Order.status == status)
    total = db.scalar(select(func.count(Order.id)).where(*filters)) or 0
    rows = db.scalars(
        select(Order)
        .options(selectinload(Order.retailer), selectinload(Order.items))
        .where(*filters)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {"items": rows, "total": total, "counts": counts}


def get_order(db: Session, order_id: int) -> Order:
    order = db.scalar(
        select(Order).options(selectinload(Order.items), selectinload(Order.retailer)).where(Order.id == order_id)
    )
    if order is None:
        raise not_found("Order")
    return order


def order_detail(db: Session, order: Order) -> dict:
    retailer = order.retailer
    exclude = order.id if order.status in S.CREDIT_EXPOSURE else None
    credit = credit_check(db, retailer, order.grand_total, exclude_order_id=exclude)
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_type == "order", AuditEvent.entity_id == order.id)
        .order_by(AuditEvent.created_at, AuditEvent.id)
    ).all()
    actor_ids = {e.actor_user_id for e in events if e.actor_user_id}
    actors = {u.id: u for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()} if actor_ids else {}
    ai_message = None
    if order.ai_extraction_id:
        ext = db.get(AiExtraction, order.ai_extraction_id)
        ai_message = {"message": ext.original_message, "provider": ext.provider, "model": ext.model} if ext else None
    stock = {
        pid: inv.available_cases
        for pid, inv in (
            (p.id, p.inventory) for p in db.scalars(select(Product).options(selectinload(Product.inventory))).all()
        )
        if inv is not None
    }
    return {
        "credit": credit,
        "audit": [
            {
                "id": e.id,
                "action": e.action,
                "actor": (actors[e.actor_user_id].name if e.actor_user_id in actors else None),
                "actor_role": (actors[e.actor_user_id].role if e.actor_user_id in actors else None),
                "before": e.before_json,
                "after": e.after_json,
                "note": e.note,
                "created_at": e.created_at,
            }
            for e in events
        ],
        "ai_message": ai_message,
        "stock": stock,
        "allowed_actions": allowed_actions(order),
    }


def _lock_order(db: Session, order_id: int, version: int) -> Order:
    order = db.get(Order, order_id, with_for_update=True, populate_existing=True)
    if order is None:
        raise not_found("Order")
    if order.version != version:
        raise AppError(
            409,
            "stale_order",
            "This order was changed by someone else. Reload to see the latest version before acting.",
            details={"current_version": order.version},
        )
    return order


def change_status(db: Session, desk_user: User, order_id: int, *, action: str, version: int, reason: str | None) -> Order:
    reason = (reason or "").strip() or None
    try:
        order = _lock_order(db, order_id, version)
        transitions = TRANSITIONS.get(action)
        if transitions is None or order.status not in transitions:
            raise AppError(409, "invalid_transition", f"Cannot {action} an order that is {order.status.replace('_', ' ')}.")
        if action in ("hold", "reject") and not reason:
            raise AppError(422, "reason_required", f"A reason is required to {action} an order.")
        if action == "approve" and order.status == S.ON_HOLD and not reason:
            raise AppError(422, "reason_required", "Approving a held order needs an override note explaining why.")

        retailer = db.get(Retailer, order.retailer_id)
        if action == "approve" and order.status == S.PENDING_REVIEW:
            credit = credit_check(db, retailer, order.grand_total, exclude_order_id=order.id)
            if not credit["within_limit"]:
                raise AppError(
                    409,
                    "credit_check_failed",
                    "This order now exceeds the retailer's available credit. Put it on hold, or approve it from hold with an override note.",
                    details={k: str(v) for k, v in credit.items()},
                )

        before = {"status": order.status, "hold_reason": order.hold_reason}
        new_status = transitions[order.status]
        if action == "reject":
            inventory = inventory_for_update(db, [i.product_id for i in order.items])
            for item in order.items:
                inventory[item.product_id].available_cases += item.paid_qty + item.free_qty
        if action == "hold":
            order.hold_reason = reason
        elif action == "release":
            order.hold_reason = None
        elif action == "approve":
            order.approved_at = datetime.now(timezone.utc)
            order.approved_by_user_id = desk_user.id
        order.status = new_status
        order.status_note = reason
        order.version += 1
        audit.record(
            db,
            actor_user_id=desk_user.id,
            entity_type="order",
            entity_id=order.id,
            action=action if not (action == "approve" and before["status"] == S.ON_HOLD) else "approve_override",
            before=before,
            after={"status": order.status, "hold_reason": order.hold_reason},
            note=reason,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_order(db, order_id)


def _item_snapshot(item: OrderItem) -> dict:
    return {
        "sku_code": item.sku_code,
        "paid_qty": item.paid_qty,
        "free_qty": item.free_qty,
        "unit_price": item.unit_price,
        "discount_amount": item.discount_amount,
        "tax_amount": item.tax_amount,
        "line_total": item.line_total,
    }


def correct_line(
    db: Session,
    desk_user: User,
    order_id: int,
    item_id: int,
    *,
    version: int,
    paid_qty: int | None,
    sku_code: str | None,
    reason: str,
    save_alias: bool,
) -> Order:
    settings = get_settings()
    try:
        order = _lock_order(db, order_id, version)
        if order.status not in EDITABLE:
            raise AppError(409, "not_editable", "Only orders pending review or on hold can be corrected.")
        item = next((i for i in order.items if i.id == item_id), None)
        if item is None:
            raise not_found("Order line")
        if not reason.strip():
            raise AppError(422, "reason_required", "A reason is required for a correction.")

        product = db.get(Product, item.product_id)
        if sku_code and sku_code != item.sku_code:
            product = db.scalar(select(Product).where(Product.sku_code == sku_code, Product.is_active.is_(True)))
            if product is None:
                raise AppError(422, "unknown_sku", "That product is not in the catalogue.")
            if any(i.product_id == product.id and i.id != item.id for i in order.items):
                raise AppError(422, "duplicate_sku", "That product is already on this order. Correct that line instead.")
        new_qty = paid_qty if paid_qty is not None else item.paid_qty
        if new_qty == item.paid_qty and product.id == item.product_id:
            raise AppError(422, "no_change", "Nothing to change on this line.")

        retailer = db.get(Retailer, order.retailer_id)
        overrides = retailer_prices(db, retailer, [product.id])
        try:
            calc = calculate_line(
                new_qty,
                price_for(product, overrides),
                product.gst_rate,
                product.gst_inclusive,
                active_scheme(product),
                max_qty=settings.max_qty_per_line,
            )
        except InvalidQuantity as exc:
            raise AppError(422, "invalid_quantity", str(exc))

        inventory = inventory_for_update(db, [item.product_id, product.id])
        inventory[item.product_id].available_cases += item.paid_qty + item.free_qty  # release old reservation
        available = inventory[product.id].available_cases
        if calc.fulfil_qty > available:
            raise AppError(
                422,
                "insufficient_stock",
                f"Only {available} cases of {product.name} are available; the corrected line needs {calc.fulfil_qty}.",
            )
        inventory[product.id].available_cases -= calc.fulfil_qty

        before = _item_snapshot(item)
        product_changed = product.id != item.product_id
        item.product_id = product.id
        item.sku_code = product.sku_code
        item.product_name = product.name
        for f in (
            "paid_qty", "free_qty", "unit_price", "gross_amount", "discount_percent", "discount_amount",
            "taxable_amount", "gst_rate", "gst_inclusive", "tax_amount", "line_total", "scheme_applied",
        ):
            setattr(item, f, getattr(calc, f))

        totals = order_totals([_calc_like(i) for i in order.items])
        for f in ("subtotal", "discount_total", "taxable_total", "tax_total", "grand_total"):
            setattr(order, f, totals[f])

        note = reason.strip()
        if order.status == S.PENDING_REVIEW:
            credit = credit_check(db, retailer, order.grand_total, exclude_order_id=order.id)
            if not credit["within_limit"]:
                order.status = S.ON_HOLD
                order.hold_reason = credit_hold_reason(credit)
                note += " | Order moved to hold: corrected total exceeds available credit."

        if save_alias and product_changed and item.original_phrase:
            upsert_sku_alias(
                db,
                retailer_id=order.retailer_id,
                alias_text=parse_segment(item.original_phrase).product_phrase,
                product_id=product.id,
                source="desk_correction",
                user_id=desk_user.id,
            )
        order.version += 1
        audit.record(
            db,
            actor_user_id=desk_user.id,
            entity_type="order",
            entity_id=order.id,
            action="line_corrected",
            before=before,
            after=_item_snapshot(item),
            note=note,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_order(db, order_id)


class _calc_like:
    """Adapter so order_totals() can sum persisted OrderItems."""

    def __init__(self, item: OrderItem):
        self.gross_amount = item.gross_amount
        self.discount_amount = item.discount_amount
        self.taxable_amount = item.taxable_amount
        self.tax_amount = item.tax_amount
        self.line_total = item.line_total
        self.paid_qty = item.paid_qty
        self.free_qty = item.free_qty
