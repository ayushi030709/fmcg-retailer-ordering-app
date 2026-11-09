import csv
import io
import uuid

from sqlalchemy import select

from app.models import Inventory, Product, Retailer, RetailerSkuAlias


def rid():
    return f"test-{uuid.uuid4().hex}"


def queue(client, desk, **params):
    r = client.get("/desk/orders", headers=desk, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def first(client, desk, status):
    return queue(client, desk, status=status)["items"][0]


def detail(client, desk, order_id):
    return client.get(f"/desk/orders/{order_id}", headers=desk).json()


def act(client, desk, order_id, action, reason=None, version=None):
    if version is None:
        version = detail(client, desk, order_id)["order"]["version"]
    return client.patch(
        f"/desk/orders/{order_id}", headers=desk, json={"action": action, "version": version, "reason": reason}
    )


def stock(db, sku):
    db.expire_all()
    return db.scalar(select(Inventory.available_cases).join(Product).where(Product.sku_code == sku))


def test_queue_shows_seeded_states_and_counts(client, desk):
    body = queue(client, desk)
    assert body["counts"] == {"exported": 1, "approved": 1, "pending_review": 2, "on_hold": 1}
    held = first(client, desk, "on_hold")
    assert "Credit limit exceeded" in held["hold_reason"]
    assert held["retailer"]["shop_name"] == "Demo General Store B"
    assert queue(client, desk, q="Store B")["total"] == 2


def test_detail_has_lines_credit_and_audit(client, desk):
    o = first(client, desk, "on_hold")
    d = detail(client, desk, o["id"])
    assert d["order"]["items"][0]["sku_code"] == "SKU-BS-075"
    assert d["credit"]["within_limit"] is False
    assert d["audit"][0]["action"] == "created"
    assert set(d["allowed_actions"]) == {"approve", "release", "reject", "correct"}


def test_approve_pending_order(client, desk):
    o = first(client, desk, "pending_review")
    r = act(client, desk, o["id"], "approve")
    assert r.status_code == 200 and r.json()["order"]["status"] == "approved"
    assert r.json()["audit"][-1]["action"] == "approve"


def test_stale_version_is_rejected(client, desk):
    o = first(client, desk, "pending_review")
    v = detail(client, desk, o["id"])["order"]["version"]
    assert act(client, desk, o["id"], "hold", "check stock", version=v).status_code == 200
    r = act(client, desk, o["id"], "approve", version=v)  # second desk user acting on old data
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_order"


def test_hold_and_reject_require_reason(client, desk):
    o = first(client, desk, "pending_review")
    assert act(client, desk, o["id"], "hold").status_code == 422
    assert act(client, desk, o["id"], "reject").status_code == 422


def test_held_order_needs_override_note_to_approve(client, desk):
    o = first(client, desk, "on_hold")
    r = act(client, desk, o["id"], "approve")
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = act(client, desk, o["id"], "approve", "Owner paid cash today")
    assert r.status_code == 200 and r.json()["order"]["status"] == "approved"
    assert r.json()["audit"][-1]["action"] == "approve_override"


def test_release_from_hold_then_approve_rechecks_credit(client, desk):
    o = first(client, desk, "on_hold")
    assert act(client, desk, o["id"], "release", "re-check").json()["order"]["status"] == "pending_review"
    r = act(client, desk, o["id"], "approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "credit_check_failed"


def test_invalid_transition(client, desk):
    o = first(client, desk, "exported")
    assert act(client, desk, o["id"], "approve").status_code == 409


def test_reject_releases_reserved_stock(client, desk, retailer_a, db):
    r = client.post(
        "/orders", headers=retailer_a, json={"client_request_id": rid(), "lines": [{"sku_code": "SKU-BS-075", "paid_qty": 10}]}
    )
    order_id = r.json()["order"]["id"]
    assert stock(db, "SKU-BS-075") == 340 - 11
    assert act(client, desk, order_id, "reject", "duplicate order").status_code == 200
    assert stock(db, "SKU-BS-075") == 340


def test_line_correction_recalculates_and_audits(client, desk, db):
    o = queue(client, desk, status="pending_review", q="Store A")["items"][0]
    d = detail(client, desk, o["id"])
    detergent = next(i for i in d["order"]["items"] if i["sku_code"] == "SKU-DT-1KG")
    before_stock = stock(db, "SKU-DT-1KG")
    r = client.patch(
        f"/desk/orders/{o['id']}/items/{detergent['id']}",
        headers=desk,
        json={"version": d["order"]["version"], "paid_qty": 4, "reason": "Retailer called to reduce"},
    )
    assert r.status_code == 200, r.text
    new = r.json()
    line = next(i for i in new["order"]["items"] if i["id"] == detergent["id"])
    assert line["paid_qty"] == 4 and line["discount_amount"] == "0.00"  # fell below the 5-case threshold
    assert stock(db, "SKU-DT-1KG") == before_stock + 1
    ev = new["audit"][-1]
    assert ev["action"] == "line_corrected" and ev["actor"] == "Demo Order Desk"
    assert ev["before"]["paid_qty"] == 5 and ev["after"]["paid_qty"] == 4
    assert new["order"]["version"] == d["order"]["version"] + 1


def test_correction_beyond_stock_rejected(client, desk):
    o = first(client, desk, "pending_review")
    d = detail(client, desk, o["id"])
    item = d["order"]["items"][0]
    r = client.patch(
        f"/desk/orders/{o['id']}/items/{item['id']}",
        headers=desk,
        json={"version": d["order"]["version"], "paid_qty": 5000, "reason": "typo test"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "insufficient_stock"


def test_desk_correction_of_ai_line_can_save_alias(client, desk, retailer_a, db):
    ext = client.post("/ai/extract-text", headers=retailer_a, json={"message": "3 case sabun wala powder"}).json()
    body = {
        "client_request_id": rid(),
        "ai_extraction_id": ext["extraction_id"],
        "lines": [{"sku_code": "SKU-BS-075", "paid_qty": 3, "original_phrase": "3 case sabun wala powder"}],
    }
    order = client.post("/orders", headers=retailer_a, json=body).json()["order"]
    r = client.patch(
        f"/desk/orders/{order['id']}/items/{order['items'][0]['id']}",
        headers=desk,
        json={"version": order["version"], "sku_code": "SKU-DT-1KG", "reason": "Retailer meant detergent", "save_alias": True},
    )
    assert r.status_code == 200, r.text
    alias = db.scalar(select(RetailerSkuAlias).where(RetailerSkuAlias.source == "desk_correction"))
    assert alias.alias_text == "sabun wala powder"
    aliases = client.get("/desk/aliases", headers=desk).json()
    target = next(a for a in aliases if a["alias_text"] == "sabun wala powder")
    r = client.patch(f"/desk/aliases/sku/{target['id']}", headers=desk, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False


def test_export_only_approved_orders_and_prevent_duplicates(client, desk):
    preview = client.get("/desk/exports/preview", headers=desk).json()
    assert preview["order_count"] == 1  # the seeded approved order; held/pending excluded
    r = client.post("/desk/exports", headers=desk, json={})
    assert r.status_code == 200, r.text
    batch = r.json()
    assert batch["order_count"] == 1 and batch["row_count"] == 1

    rows = list(csv.DictReader(io.StringIO(client.get(f"/desk/exports/{batch['id']}/download", headers=desk).text)))
    assert rows[0]["Item Code"] == "SKU-BS-075"
    assert (rows[0]["Billed Qty"], rows[0]["Free Qty"], rows[0]["Actual Qty"]) == ("20", "2", "22")
    assert rows[0]["Rate"] == "8.10" and rows[0]["Line Amount"] == rows[0]["Order Total"] == "191.16"
    assert rows[0]["Voucher Number"] == batch["order_numbers"][0]

    # Exporting again finds nothing new; the order is not duplicated.
    r = client.post("/desk/exports", headers=desk, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "nothing_to_export"
    assert queue(client, desk, status="exported")["total"] == 2
    history = client.get("/desk/exports", headers=desk).json()
    assert len(history) == 2


def test_export_rejects_held_or_already_exported_ids(client, desk):
    held = first(client, desk, "on_hold")
    r = client.post("/desk/exports", headers=desk, json={"order_ids": [held["id"]]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_exportable"


def test_csv_neutralises_formula_injection(client, desk, retailer_a, db):
    retailer = db.scalar(select(Retailer).where(Retailer.code == "DEMO-R001"))
    retailer.shop_name = "=HYPERLINK(\"http://evil\")"
    db.commit()
    o = client.post(
        "/orders", headers=retailer_a, json={"client_request_id": rid(), "lines": [{"sku_code": "SKU-DT-1KG", "paid_qty": 1}]}
    ).json()["order"]
    act(client, desk, o["id"], "approve")
    batch = client.post("/desk/exports", headers=desk, json={"order_ids": [o["id"]]}).json()
    text = client.get(f"/desk/exports/{batch['id']}/download", headers=desk).text
    row = list(csv.DictReader(io.StringIO(text)))[0]
    assert row["Party Name"].startswith("'=")


def test_date_filter_uses_ist_calendar_days(client, desk, db):
    from datetime import datetime, timezone

    from app.models import Order

    order = db.scalar(select(Order).where(Order.status == "on_hold"))
    # 2026-03-10 20:00 UTC is 2026-03-11 01:30 in India.
    order.created_at = datetime(2026, 3, 10, 20, 0, tzinfo=timezone.utc)
    db.commit()
    ids = lambda **p: {o["id"] for o in queue(client, desk, **p)["items"]}  # noqa: E731
    assert order.id in ids(date_from="2026-03-11", date_to="2026-03-11")
    assert order.id not in ids(date_from="2026-03-10", date_to="2026-03-10")
