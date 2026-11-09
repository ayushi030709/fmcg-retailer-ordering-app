"""Deterministic scheme and pricing engine.

This module is pure (no database, no I/O) so it can be unit-tested exhaustively
and reused by the manual cart, the AI review flow, order submission and desk
corrections. The LLM never calculates prices, discounts or tax.

Rounding policy (documented in the TDD):
  * gross_amount    = unit_price x paid_qty                     (exact, 2 dp)
  * discount_amount = round_half_up(gross x discount% , 2 dp)
  * GST-exclusive:  taxable = gross - discount
                    tax     = round_half_up(taxable x rate%, 2 dp)
                    total   = taxable + tax
  * GST-inclusive:  total   = gross - discount
                    taxable = round_half_up(total x 100 / (100 + rate), 2 dp)
                    tax     = total - taxable
Each stored component is already at 2 dp, so line components always reconcile
exactly and order totals are plain sums of line values.

Free goods (Scheme A) carry zero value and therefore zero tax in this demo
(assumption, see TDD). Free cases DO consume stock (assumption A8).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.money import HUNDRED, ZERO, money

BUY_X_GET_Y_FREE = "buy_x_get_y_free"
PERCENT_DISCOUNT = "percent_discount"
SCHEME_TYPES = (BUY_X_GET_Y_FREE, PERCENT_DISCOUNT)


@dataclass(frozen=True)
class SchemeConfig:
    scheme_type: str
    threshold_qty: int
    description: str
    free_qty: int | None = None
    discount_percent: Decimal | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool = True

    def applies_on(self, on: date) -> bool:
        if not self.is_active:
            return False
        if self.starts_on and on < self.starts_on:
            return False
        if self.ends_on and on > self.ends_on:
            return False
        return True


@dataclass
class LineCalculation:
    paid_qty: int
    free_qty: int
    fulfil_qty: int
    unit_price: Decimal
    gross_amount: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    gst_rate: Decimal
    gst_inclusive: bool
    tax_amount: Decimal
    line_total: Decimal
    scheme_applied: str | None
    hints: list[str] = field(default_factory=list)


class InvalidQuantity(ValueError):
    pass


def calculate_line(
    paid_qty: int,
    unit_price: Decimal,
    gst_rate: Decimal,
    gst_inclusive: bool,
    scheme: SchemeConfig | None,
    on: date | None = None,
    max_qty: int = 5000,
) -> LineCalculation:
    if isinstance(paid_qty, bool) or not isinstance(paid_qty, int):
        raise InvalidQuantity("Quantity must be a whole number of cases.")
    if paid_qty <= 0:
        raise InvalidQuantity("Quantity must be at least 1 case.")
    if paid_qty > max_qty:
        raise InvalidQuantity(f"Quantity cannot exceed {max_qty} cases on one line.")
    if unit_price < ZERO or gst_rate < ZERO:
        raise ValueError("Price and GST rate must not be negative.")

    on = on or date.today()
    active = scheme if scheme is not None and scheme.applies_on(on) else None

    unit_price = money(unit_price)
    gross = money(unit_price * paid_qty)
    free_qty = 0
    discount_percent = ZERO
    discount_amount = ZERO
    scheme_applied: str | None = None
    hints: list[str] = []

    if active is not None:
        if active.scheme_type == BUY_X_GET_Y_FREE:
            per_block = active.free_qty or 0
            free_qty = (paid_qty // active.threshold_qty) * per_block
            if free_qty:
                scheme_applied = active.description
            remainder = paid_qty % active.threshold_qty
            if per_block and remainder:
                more = active.threshold_qty - remainder
                hints.append(f"Add {more} more case{'s' if more != 1 else ''} to get {per_block} more free.")
        elif active.scheme_type == PERCENT_DISCOUNT:
            if paid_qty >= active.threshold_qty:
                discount_percent = money(active.discount_percent or ZERO)
                discount_amount = money(gross * discount_percent / HUNDRED)
                scheme_applied = active.description
            else:
                more = active.threshold_qty - paid_qty
                hints.append(
                    f"Add {more} more case{'s' if more != 1 else ''} to get {money(active.discount_percent or ZERO).normalize()}% off."
                )
        else:  # pragma: no cover - guarded by seed/validation
            raise ValueError(f"Unknown scheme type {active.scheme_type!r}")

    rate = money(gst_rate)
    after_discount = gross - discount_amount
    if gst_inclusive:
        line_total = after_discount
        taxable = money(after_discount * HUNDRED / (HUNDRED + rate))
        tax = line_total - taxable
    else:
        taxable = after_discount
        tax = money(taxable * rate / HUNDRED)
        line_total = taxable + tax

    return LineCalculation(
        paid_qty=paid_qty,
        free_qty=free_qty,
        fulfil_qty=paid_qty + free_qty,
        unit_price=unit_price,
        gross_amount=gross,
        discount_percent=discount_percent,
        discount_amount=discount_amount,
        taxable_amount=taxable,
        gst_rate=rate,
        gst_inclusive=gst_inclusive,
        tax_amount=tax,
        line_total=line_total,
        scheme_applied=scheme_applied,
        hints=hints,
    )
