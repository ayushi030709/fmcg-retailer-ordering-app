from datetime import date
from decimal import Decimal

import pytest

from app.services.scheme_engine import (
    BUY_X_GET_Y_FREE,
    PERCENT_DISCOUNT,
    InvalidQuantity,
    SchemeConfig,
    calculate_line,
)

BISCUIT = SchemeConfig(BUY_X_GET_Y_FREE, threshold_qty=10, free_qty=1, description="Buy 10 cases, get 1 free")
DETERGENT = SchemeConfig(
    PERCENT_DISCOUNT, threshold_qty=5, discount_percent=Decimal("3.00"), description="3% off 5 or more cases"
)
GST = Decimal("18.00")


@pytest.mark.parametrize("paid,free", [(1, 0), (9, 0), (10, 1), (19, 1), (20, 2), (25, 2), (100, 10)])
def test_biscuit_buy_10_get_1(paid, free):
    calc = calculate_line(paid, Decimal("8.10"), GST, False, BISCUIT)
    assert calc.free_qty == free
    assert calc.fulfil_qty == paid + free  # free cases count toward fulfilment/stock
    assert calc.discount_amount == Decimal("0.00")
    assert calc.gross_amount == Decimal("8.10") * paid


def test_biscuit_hint_for_next_free_case():
    assert calculate_line(9, Decimal("8.10"), GST, False, BISCUIT).hints == ["Add 1 more case to get 1 more free."]
    assert calculate_line(10, Decimal("8.10"), GST, False, BISCUIT).hints == []


def test_detergent_below_threshold_has_no_discount():
    calc = calculate_line(4, Decimal("101.50"), GST, False, DETERGENT)
    assert calc.discount_amount == Decimal("0.00")
    assert calc.scheme_applied is None
    assert calc.hints == ["Add 1 more case to get 3% off."]


def test_detergent_brief_worked_example_and_rounding():
    # Brief: 5 x 101.50 = 507.50; 3% = 15.225 -> rounds half-up to 15.23.
    calc = calculate_line(5, Decimal("101.50"), GST, False, DETERGENT)
    assert calc.gross_amount == Decimal("507.50")
    assert calc.discount_percent == Decimal("3.00")
    assert calc.discount_amount == Decimal("15.23")
    assert calc.taxable_amount == Decimal("492.27")
    assert calc.tax_amount == Decimal("88.61")  # 492.27 x 18% = 88.6086
    assert calc.line_total == Decimal("580.88")
    assert calc.taxable_amount + calc.tax_amount == calc.line_total
    assert calc.free_qty == 0


def test_no_scheme_tea():
    calc = calculate_line(3, Decimal("118.00"), GST, False, None)
    assert (calc.free_qty, calc.discount_amount, calc.scheme_applied) == (0, Decimal("0.00"), None)
    assert calc.line_total == Decimal("417.72")  # 354.00 + 63.72


def test_gst_inclusive_price_backs_out_tax():
    calc = calculate_line(1, Decimal("118.00"), GST, True, None)
    assert calc.line_total == Decimal("118.00")
    assert calc.taxable_amount == Decimal("100.00")
    assert calc.tax_amount == Decimal("18.00")


def test_all_amounts_are_decimal_two_places():
    calc = calculate_line(7, Decimal("101.50"), GST, False, DETERGENT)
    for v in (calc.gross_amount, calc.discount_amount, calc.taxable_amount, calc.tax_amount, calc.line_total):
        assert isinstance(v, Decimal)
        assert v.as_tuple().exponent == -2


@pytest.mark.parametrize("bad", [0, -1, 5001, 1.5, True, "5", None])
def test_invalid_quantities_rejected(bad):
    with pytest.raises(InvalidQuantity):
        calculate_line(bad, Decimal("8.10"), GST, False, BISCUIT)


def test_scheme_outside_dates_or_inactive_not_applied():
    expired = SchemeConfig(BUY_X_GET_Y_FREE, 10, "old", free_qty=1, ends_on=date(2020, 1, 1))
    future = SchemeConfig(BUY_X_GET_Y_FREE, 10, "future", free_qty=1, starts_on=date(2099, 1, 1))
    inactive = SchemeConfig(BUY_X_GET_Y_FREE, 10, "off", free_qty=1, is_active=False)
    for s in (expired, future, inactive):
        assert calculate_line(10, Decimal("8.10"), GST, False, s).free_qty == 0
