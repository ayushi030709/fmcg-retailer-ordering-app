import json
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.models import AiExtraction, Order, RetailerSkuAlias, RetailerUnitAlias
from app.services.ai import extraction as extraction_mod
from app.services.ai.provider import LlmMalformed, LlmTimeout, call_llm, parse_llm_json

from tests.conftest import SAMPLE


def rid():
    return f"test-{uuid.uuid4().hex}"


def llm_line(text, sku, qty, unit_text="peti", **extra):
    return {
        "original_text": text,
        "product_description": extra.pop("desc", text),
        "candidate_sku": sku,
        "quantity": qty,
        "unit_text": unit_text,
        "unit": "case",
        "unit_is_confirmed": True,  # the model over-claims; the server must not trust this
        "needs_clarification": False,
        "clarification_question": None,
        "alternatives": [],
        "reasoning_summary": "test",
        **extra,
    }


SAMPLE_LLM = {
    "message_language": "hi-Latn",
    "lines": [
        llm_line("5 peti biscuit chhota", "SKU-BS-075", 5, desc="small glucose biscuit"),
        llm_line("2 peti washing powder 1 kilo", "SKU-DT-1KG", 2, desc="detergent powder 1 kg"),
        llm_line("chai patti 250 wala 1 peti", "SKU-TE-250", 1, desc="tea leaf 250 g"),
    ],
    "unmatched_phrases": [],
}


@pytest.fixture
def fake_llm(monkeypatch, settings):
    """Switch the app to the LLM path and return a setter for the model's raw JSON."""
    monkeypatch.setattr(settings, "ai_provider_api_key", "test-key")
    state = {"raw": SAMPLE_LLM, "exc": None, "calls": []}

    def fake_call(messages, **_):
        state["calls"].append(messages)
        if state["exc"]:
            raise state["exc"]
        return parse_llm_json(state["raw"], latency_ms=5)

    monkeypatch.setattr(extraction_mod, "call_llm", fake_call)
    return state


def extract(client, headers, message=SAMPLE):
    return client.post("/ai/extract-text", headers=headers, json={"message": message})


def by_sku(lines):
    return {l["candidate"]["sku_code"]: l for l in lines if l["candidate"]}


def test_extraction_never_creates_an_order(client, retailer_a, db):
    before = db.scalar(select(func.count(Order.id)))
    r = extract(client, retailer_a)
    assert r.status_code == 200
    assert db.scalar(select(func.count(Order.id))) == before
    ext = db.get(AiExtraction, r.json()["extraction_id"])
    assert ext.status == "extracted" and ext.original_message == SAMPLE and ext.order_id is None


def test_fallback_parser_is_clearly_labelled(client, retailer_a):
    body = extract(client, retailer_a).json()
    assert body["is_fallback"] is True and body["provider"] == "fallback-rules"
    assert any("fallback" in w for w in body["warnings"])
    lines = by_sku(body["lines"])
    assert set(lines) == {"SKU-BS-075", "SKU-DT-1KG", "SKU-TE-250"}


def test_sample_message_llm_path(client, retailer_a, fake_llm):
    body = extract(client, retailer_a).json()
    assert body["is_fallback"] is False and body["provider"] == "groq"
    lines = by_sku(body["lines"])
    biscuit, detergent, tea = lines["SKU-BS-075"], lines["SKU-DT-1KG"], lines["SKU-TE-250"]
    # Original wording preserved per line.
    assert biscuit["original_text"] == "5 peti biscuit chhota"
    assert (biscuit["quantity"], detergent["quantity"], tea["quantity"]) == (5, 2, 1)
    # 'peti' is NOT assumed to be a case for retailer A, even though the model said so.
    for line in (biscuit, detergent, tea):
        assert line["unit"] == "unknown" and line["unit_confirmed"] is False
        assert any(c["type"] == "unit" and "peti" in c["question"] for c in line["clarifications"])
    assert detergent["confidence_band"] == "high"
    assert biscuit["confidence_band"] in ("medium", "high")
    # Lines needing verification always offer two alternatives (brief 7.4).
    if biscuit["confidence_band"] != "high":
        assert len(biscuit["alternatives"]) == 2
    assert all(a["sku_code"] != "SKU-BS-075" for a in biscuit["alternatives"])
    # A clear high-confidence line does not pad its alternatives with unrelated products.
    assert detergent["alternatives"] == []
    # Tea is out of stock and flagged, never silently accepted.
    assert tea["out_of_stock"] is True and tea["status"] == "out_of_stock"
    # The model received the constrained catalogue but no prices or retailer identity.
    system_prompt = fake_llm["calls"][0][0]["content"]
    assert "SKU-BS-075" in system_prompt and "Demo Kirana" not in system_prompt and "101.50" not in system_prompt


def test_retailer_unit_alias_resolves_peti(client, retailer_b, fake_llm):
    body = extract(client, retailer_b).json()
    for line in body["lines"]:
        assert line["unit"] == "case" and line["unit_confirmed"] and line["unit_source"] == "retailer_alias"
    biscuit = by_sku(body["lines"])["SKU-BS-075"]
    assert biscuit["confidence"] >= 0.95  # seeded alias "biscuit chhota" for retailer B
    assert biscuit["status"] == "ready"


def test_invented_sku_is_ignored(client, retailer_a, fake_llm):
    fake_llm["raw"] = {"lines": [llm_line("5 peti biscuit chhota", "SKU-FAKE-999", 5)], "unmatched_phrases": []}
    body = extract(client, retailer_a, "5 peti biscuit chhota").json()
    assert any("unknown SKU" in w for w in body["warnings"])
    assert body["lines"][0]["ai_suggested_sku"] is None
    assert body["lines"][0]["candidate"]["sku_code"] == "SKU-BS-075"  # from deterministic matching only


def test_unsupported_action_fields_are_ignored(client, retailer_a, fake_llm, db):
    before = db.scalar(select(func.count(Order.id)))
    fake_llm["raw"] = {**SAMPLE_LLM, "place_order": True, "order_status": "approved"}
    body = extract(client, retailer_a).json()
    assert any("place_order" in w for w in body["warnings"])
    assert db.scalar(select(func.count(Order.id))) == before


def test_paraphrased_line_is_reread_from_message(client, retailer_a, fake_llm):
    fake_llm["raw"] = {
        "lines": [llm_line("five cases of small biscuits", "SKU-BS-075", 5)],
        "unmatched_phrases": [],
    }
    body = extract(client, retailer_a, "5 peti biscuit chhota").json()
    assert any("paraphrased" in w for w in body["warnings"])
    assert body["lines"][0]["original_text"] == "5 peti biscuit chhota"


def test_partial_extraction_surfaces_missed_text(client, retailer_a, fake_llm):
    fake_llm["raw"] = {"lines": SAMPLE_LLM["lines"][:1], "unmatched_phrases": []}
    body = extract(client, retailer_a).json()
    assert len(body["lines"]) == 3
    assert any("not extracted" in w for w in body["warnings"])


def test_unknown_product_is_no_match_never_fabricated(client, retailer_a, fake_llm):
    fake_llm["raw"] = {"lines": [], "unmatched_phrases": ["3 case maggi noodles"]}
    body = extract(client, retailer_a, "3 case maggi noodles").json()
    line = body["lines"][0]
    assert line["candidate"] is None and line["status"] == "no_match"
    assert any(c["type"] == "sku" for c in line["clarifications"])


def test_ambiguous_quantity_disagreement_is_asked(client, retailer_a, fake_llm):
    fake_llm["raw"] = {"lines": [llm_line("5 peti biscuit chhota", "SKU-BS-075", 50)], "unmatched_phrases": []}
    line = extract(client, retailer_a, "5 peti biscuit chhota").json()["lines"][0]
    assert any(c["type"] == "quantity" for c in line["clarifications"])


def test_pieces_are_not_silently_converted(client, retailer_a):
    line = extract(client, retailer_a, "10 pcs biscuit").json()["lines"][0]
    assert line["unit"] == "piece" and not line["unit_confirmed"]
    assert any("sold by the case" in c["question"] for c in line["clarifications"])


@pytest.mark.parametrize(
    "exc,status,code",
    [(LlmTimeout("t"), 504, "ai_timeout"), (LlmMalformed("bad"), 502, "ai_invalid_response")],
)
def test_provider_failures_are_reported_and_logged(client, retailer_a, fake_llm, db, exc, status, code):
    fake_llm["exc"] = exc
    r = extract(client, retailer_a)
    assert r.status_code == status and r.json()["error"]["code"] == code
    ext = db.get(AiExtraction, r.json()["error"]["details"]["extraction_id"])
    assert ext.status == "failed" and ext.error_message.startswith(code)


def test_malformed_provider_payloads(settings, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider_api_key", "k")

    def transport(content):
        return httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
            )
        )

    msgs = [{"role": "user", "content": "x"}]
    with pytest.raises(LlmMalformed):
        call_llm(msgs, client=transport("not json at all"))
    with pytest.raises(LlmMalformed):
        call_llm(msgs, client=transport(json.dumps({"lines": "should be a list"})))
    with pytest.raises(LlmMalformed):
        call_llm(msgs, client=transport(json.dumps([1, 2, 3])))
    ok = call_llm(msgs, client=transport(json.dumps(SAMPLE_LLM)))
    assert len(ok.output.lines) == 3


def test_message_length_is_limited(client, retailer_a):
    r = extract(client, retailer_a, "5 case biscuit " * 100)
    assert r.status_code == 422


def confirm_body(extraction_id, **line_overrides):
    line = {
        "sku_code": "SKU-DT-1KG",
        "paid_qty": 2,
        "original_phrase": "2 peti washing powder 1 kilo",
        "unit_confirmed": True,
        "unit_alias": "peti",
        "remember_unit_alias": True,
        "remember_product_alias": True,
        **line_overrides,
    }
    return {"client_request_id": rid(), "ai_extraction_id": extraction_id, "lines": [line]}


def test_confirmation_creates_ai_order_and_learns_aliases(client, retailer_a, db):
    ext_id = extract(client, retailer_a).json()["extraction_id"]
    r = client.post("/orders", headers=retailer_a, json=confirm_body(ext_id))
    assert r.status_code == 200, r.text
    order = r.json()["order"]
    assert order["source"] == "ai"
    assert order["items"][0]["original_phrase"] == "2 peti washing powder 1 kilo"
    ext = db.get(AiExtraction, ext_id)
    assert ext.status == "confirmed" and ext.order_id == order["id"]
    assert db.scalar(select(RetailerUnitAlias).where(RetailerUnitAlias.retailer_id == 1, RetailerUnitAlias.alias_text == "peti"))
    alias = db.scalar(select(RetailerSkuAlias).where(RetailerSkuAlias.retailer_id == 1))
    assert alias.alias_text == "washing powder 1 kilo" and alias.source == "retailer_confirmed"

    # Next time, retailer A's 'peti' is understood and the phrase matches strongly.
    line = by_sku(extract(client, retailer_a).json()["lines"])["SKU-DT-1KG"]
    assert line["unit"] == "case" and line["unit_source"] == "retailer_alias"
    assert line["confidence"] >= 0.95 and line["status"] == "ready"


def test_extraction_cannot_be_confirmed_twice(client, retailer_a):
    ext_id = extract(client, retailer_a).json()["extraction_id"]
    assert client.post("/orders", headers=retailer_a, json=confirm_body(ext_id)).status_code == 200
    r = client.post("/orders", headers=retailer_a, json=confirm_body(ext_id))
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_confirmed"


def test_unconfirmed_unit_blocks_order(client, retailer_a, db):
    ext_id = extract(client, retailer_a).json()["extraction_id"]
    before = db.scalar(select(func.count(Order.id)))
    r = client.post("/orders", headers=retailer_a, json=confirm_body(ext_id, unit_confirmed=False))
    assert r.status_code == 422 and r.json()["error"]["code"] == "unit_not_confirmed"
    assert db.scalar(select(func.count(Order.id))) == before


def test_confirming_out_of_stock_ai_line_is_blocked(client, retailer_a):
    ext_id = extract(client, retailer_a).json()["extraction_id"]
    body = confirm_body(ext_id, sku_code="SKU-TE-250", paid_qty=1, original_phrase="chai patti 250 wala 1 peti")
    r = client.post("/orders", headers=retailer_a, json=body)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["code"] == "out_of_stock"


def test_other_retailer_cannot_use_or_read_extraction(client, retailer_a, retailer_b):
    ext_id = extract(client, retailer_a).json()["extraction_id"]
    assert client.get(f"/ai/extractions/{ext_id}", headers=retailer_b).status_code == 404
    r = client.post("/orders", headers=retailer_b, json=confirm_body(ext_id))
    assert r.status_code == 404
    assert client.get(f"/ai/extractions/{ext_id}", headers=retailer_a).status_code == 200


def test_unconfirmed_ai_guess_is_not_learned(client, retailer_a, db):
    extract(client, retailer_a)
    assert db.scalar(select(func.count(RetailerSkuAlias.id)).where(RetailerSkuAlias.retailer_id == 1)) == 0
    assert db.scalar(select(func.count(RetailerUnitAlias.id)).where(RetailerUnitAlias.retailer_id == 1)) == 0
