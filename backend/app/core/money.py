"""Decimal helpers. All currency maths uses Decimal with ROUND_HALF_UP to 2 dp."""

from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


def money(value: Decimal | int | str) -> Decimal:
    """Round a value to 2 decimal places using half-up (commercial) rounding."""
    return Decimal(value).quantize(PAISE, rounding=ROUND_HALF_UP)
