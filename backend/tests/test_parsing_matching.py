from decimal import Decimal

from app.services.ai.matching import ProductProfile, band, score_products
from app.services.ai.parsing import parse_message, parse_segment, tokenize

from tests.conftest import SAMPLE

PRODUCTS = [
    ProductProfile(1, "SKU-BS-075", "Glucose biscuit 75 g, case of 96", Decimal("75"), "g", ["biscuit", "glucose biscuit"]),
    ProductProfile(2, "SKU-DT-1KG", "Detergent powder 1 kg, case of 20", Decimal("1"), "kg", ["detergent", "washing powder"]),
    ProductProfile(3, "SKU-TE-250", "Tea leaf 250 g, case of 40", Decimal("250"), "g", ["tea", "chai patti"]),
]


def top(phrase, **kw):
    p = parse_segment(phrase)
    args = dict(size_value=p.size_value, size_unit=p.size_unit, llm_sku=None, llm_description=None, aliases={}, llm_available=False)
    args.update(kw)
    return score_products(p.product_phrase, PRODUCTS, **args)


def test_sample_message_is_segmented_with_original_wording():
    lines = parse_message(SAMPLE)
    assert [l.original_text for l in lines] == [
        "5 peti biscuit chhota",
        "2 peti washing powder 1 kilo",
        "chai patti 250 wala 1 peti",
    ]
    assert [l.quantity for l in lines] == [5, 2, 1]
    assert all(l.unit_text == "peti" and l.unit_kind == "ambiguous" for l in lines)
    # Pack sizes are recognised and NOT mistaken for quantities.
    assert (lines[1].size_value, lines[1].size_unit) == (Decimal("1"), "kg")
    assert (lines[2].size_value, lines[2].size_unit) == (Decimal("250"), None)


def test_glued_tokens_and_hinglish_numbers():
    assert tokenize("250g chai 5peti") == ["250", "g", "chai", "5", "peti"]
    p = parse_segment("do case washing powder")
    assert (p.quantity, p.unit_kind) == (2, "case")
    p = parse_segment("10 pcs biscuit")
    assert (p.quantity, p.unit_kind) == (10, "piece")


def test_devanagari_survives_normalisation():
    assert tokenize("चाय पत्ती 2 पेटी") == ["चाय", "पत्ती", "2", "पेटी"]


def test_clear_phrases_score_high():
    r = top("2 peti washing powder 1 kilo")
    assert r[0].product.sku_code == "SKU-DT-1KG" and band(r[0].score) == "high"
    r = top("chai patti 250 wala 1 peti")
    assert r[0].product.sku_code == "SKU-TE-250" and band(r[0].score) == "high"


def test_single_keyword_without_size_is_medium_not_high():
    r = top("5 peti biscuit chhota")
    assert r[0].product.sku_code == "SKU-BS-075"
    assert band(r[0].score) == "medium"


def test_conflicting_pack_size_caps_confidence():
    r = top("3 case biscuit 200 g")
    assert r[0].product.sku_code == "SKU-BS-075"
    assert r[0].score <= 0.55 and band(r[0].score) == "low"


def test_unknown_product_has_no_lexical_evidence():
    r = top("4 case maggi noodles")
    assert all(s.lexical == 0 for s in r)
    assert all(s.score <= 0.15 for s in r)


def test_llm_agreement_raises_score_but_cannot_create_evidence_alone():
    r = top("4 case maggi noodles", llm_sku="SKU-BS-075", llm_available=True)
    assert r[0].product.sku_code == "SKU-BS-075"
    assert band(r[0].score) == "low"  # model opinion alone never reaches medium


def test_retailer_alias_is_strong_evidence():
    r = top("5 peti khaas wala", aliases={"khaas wala": 1})
    assert r[0].product.sku_code == "SKU-BS-075"
    assert r[0].score >= 0.95 and r[0].alias_match


def test_typo_tolerance():
    r = top("3 case detergant")
    assert r[0].product.sku_code == "SKU-DT-1KG"
    assert r[0].lexical > 0
