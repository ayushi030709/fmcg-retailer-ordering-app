import threading
import uuid

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Inventory, Order, Product, Retailer, User
from app.services.orders import LineInput, create_order

from tests.conftest import IS_POSTGRES


def rid():
    return f"test-{uuid.uuid4().hex}"


def stock(db, sku):
    db.expire_all()
    return db.scalar(select(Inventory.available_cases).join(Product).where(Product.sku_code == sku))


def test_catalogue_shows_brief_skus_prices_stock_and_schemes(client, retailer_a):
    body = client.get("/retailer/catalogue", headers=retailer_a).json()
    items = {i["sku_code"]: i for i in body["items"]}
    assert set(items) == {"SKU-BS-075", "SKU-DT-1KG", "SKU-TE-250"}
    assert items["SKU-BS-075"]["dealer_price"] == "8.10"
    assert items["SKU-BS-075"]["available_cases"] == 340
    assert items["SKU-BS-075"]["scheme"]["description"] == "Buy 10 cases, get 1 free"
    assert items["SKU-DT-1KG"]["dealer_price"] == "101.50"
    assert items["SKU-DT-1KG"]["scheme"]["discount_percent"] == "3.00"
    assert items["SKU-TE-250"]["stock_status"] == "out_of_stock" and items["SKU-TE-250"]["scheme"] is None
    assert all(i["gst_inclusive"] is False for i in items.values())
    assert "EXCLUDE GST" in body["gst_note"]


def test_catalogue_search(client, retailer_a):
    body = client.get("/retailer/catalogue", params={"q": "chai"}, headers=retailer_a).json()
    assert [i["sku_code"] for i in body["items"]] == ["SKU-TE-250"]


def test_retailer_specific_price_is_private(client, retailer_a, retailer_b):
    a = {i["sku_code"]: i for i in client.get("/retailer/catalogue", headers=retailer_a).json()["items"]}
    b = {i["sku_code"]: i for i in client.get("/retailer/catalogue", headers=retailer_b).json()["items"]}
    assert a["SKU-DT-1KG"]["dealer_price"] == "101.50"
    assert b["SKU-DT-1KG"]["dealer_price"] == "99.00"  # synthetic demo override for retailer B only


def test_preview_matches_created_order(client, retailer_a):
    lines = [{"sku_code": "SKU-BS-075", "paid_qty": 10}, {"sku_code": "SKU-DT-1KG", "paid_qty": 5}]
    preview = client.post("/orders/preview", headers=retailer_a, json={"lines": lines}).json()
    assert preview["can_submit"] is True
    assert preview["totals"]["free_cases"] == 1
    r = client.post("/orders", headers=retailer_a, json={"client_request_id": rid(), "lines": lines})
    assert r.status_code == 200, r.text
    order = r.json()["order"]
    assert order["status"] == "pending_review" and order["source"] == "manual"
    for k in ("subtotal", "discount_total", "taxable_total", "tax_total", "grand_total"):
        assert order[k] == preview["totals"][k]
    assert order["grand_total"] == "676.46"  # 95.58 + 580.88


def test_out_of_stock_tea_is_blocked(client, retailer_a, db):
    lines = [{"sku_code": "SKU-TE-250", "paid_qty": 1}]
    preview = client.post("/orders/preview", headers=retailer_a, json={"lines": lines}).json()
    assert preview["can_submit"] is False
    assert preview["issues"][0]["code"] == "out_of_stock"
    before = db.scalar(select(func.count(Order.id)))
    r = client.post("/orders", headers=retailer_a, json={"client_request_id": rid(), "lines": lines})
    assert r.status_code == 422 and r.json()["error"]["code"] == "order_invalid"
    assert db.scalar(select(func.count(Order.id))) == before


def test_free_goods_count_toward_stock(client, retailer_a, db):
    inv = db.scalar(select(Inventory).join(Product).where(Product.sku_code == "SKU-BS-075"))
    inv.available_cases = 10
    db.commit()
    r = client.post(
        "/orders", headers=retailer_a, json={"client_request_id": rid(), "lines": [{"sku_code": "SKU-BS-075", "paid_qty": 10}]}
    )
    assert r.status_code == 422
    assert "needs 11" in r.json()["error"]["details"][0]["message"]
    r = client.post(
        "/orders", headers=retailer_a, json={"client_request_id": rid(), "lines": [{"sku_code": "SKU-BS-075", "paid_qty": 9}]}
    )
    assert r.status_code == 200


def test_order_reserves_stock(client, retailer_a, db):
    before = stock(db, "SKU-BS-075")
    client.post(
        "/orders", headers=retailer_a, json={"client_request_id": rid(), "lines": [{"sku_code": "SKU-BS-075", "paid_qty": 20}]}
    )
    assert stock(db, "SKU-BS-075") == before - 22


def test_double_submit_is_idempotent(client, retailer_a, db):
    body = {"client_request_id": rid(), "lines": [{"sku_code": "SKU-DT-1KG", "paid_qty": 1}]}
    first = client.post("/orders", headers=retailer_a, json=body).json()
    second = client.post("/orders", headers=retailer_a, json=body).json()
    assert first["created"] is True and second["created"] is False
    assert first["order"]["id"] == second["order"]["id"]
    assert stock(db, "SKU-DT-1KG") == 84


@pytest.mark.parametrize(
    "lines,code",
    [
        ([{"sku_code": "SKU-BS-075", "paid_qty": 0}], "validation_error"),
        ([{"sku_code": "SKU-BS-075", "paid_qty": -3}], "validation_error"),
        ([{"sku_code": "SKU-BS-075", "paid_qty": 2.5}], "validation_error"),
        ([{"sku_code": "SKU-BS-075", "paid_qty": "5"}], "validation_error"),
        ([{"sku_code": "SKU-BS-075", "paid_qty": 999999}], "validation_error"),
        ([], "validation_error"),
        ([{"sku_code": "SKU-NOPE", "paid_qty": 1}], "order_invalid"),
        ([{"sku_code": "SKU-BS-075", "paid_qty": 1}, {"sku_code": "SKU-BS-075", "paid_qty": 2}], "order_invalid"),
    ],
)
def test_invalid_orders_rejected(client, retailer_a, lines, code):
    r = client.post("/orders", headers=retailer_a, json={"client_request_id": rid(), "lines": lines})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == code


def test_credit_within_limit_is_pending(client, retailer_a):
    r = client.post(
        "/orders", headers=retailer_a, json={"client_request_id": rid(), "lines": [{"sku_code": "SKU-DT-1KG", "paid_qty": 1}]}
    )
    assert r.json()["order"]["status"] == "pending_review"


def test_credit_over_limit_is_held_with_reason(client, retailer_b):
    lines = [{"sku_code": "SKU-DT-1KG", "paid_qty": 2}]
    preview = client.post("/orders/preview", headers=retailer_b, json={"lines": lines}).json()
    assert preview["will_be_held"] is True and preview["can_submit"] is True
    r = client.post("/orders", headers=retailer_b, json={"client_request_id": rid(), "lines": lines})
    order = r.json()["order"]
    assert order["status"] == "on_hold"
    assert "Credit limit exceeded" in order["hold_reason"]


def test_retailer_sees_only_own_orders(client, retailer_a, retailer_b, db):
    b_orders = client.get("/retailer/orders", headers=retailer_b).json()["items"]
    assert b_orders and all(o["retailer"]["code"] == "DEMO-R002" for o in b_orders)
    a_orders = client.get("/retailer/orders", headers=retailer_a).json()["items"]
    assert {o["id"] for o in a_orders}.isdisjoint({o["id"] for o in b_orders})
    # Retailer A cannot fetch B's order — and gets 404, not 403, so existence is not leaked.
    r = client.get(f"/retailer/orders/{b_orders[0]['id']}", headers=retailer_a)
    assert r.status_code == 404


def test_me_shows_only_own_credit(client, retailer_a):
    me = client.get("/me", headers=retailer_a).json()
    assert me["retailer"]["code"] == "DEMO-R001"
    assert me["credit"]["credit_limit"] == "50000.00"


@pytest.mark.skipif(not IS_POSTGRES, reason="row locking needs PostgreSQL (set TEST_DATABASE_URL)")
def test_concurrent_orders_do_not_oversell(db):
    inv = db.scalar(select(Inventory).join(Product).where(Product.sku_code == "SKU-DT-1KG"))
    inv.available_cases = 5
    db.commit()
    retailer_ids = db.scalars(select(Retailer.id).order_by(Retailer.id)).all()
    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt(retailer_id: int):
        with SessionLocal() as s:
            retailer = s.get(Retailer, retailer_id)
            user = s.get(User, retailer.user_id)
            barrier.wait()
            try:
                create_order(s, user, retailer, client_request_id=rid(), lines=[LineInput("SKU-DT-1KG", 4)])
                results.append("ok")
            except Exception as exc:  # AppError for insufficient stock
                results.append(type(exc).__name__)

    threads = [threading.Thread(target=attempt, args=(r,)) for r in retailer_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["AppError", "ok"]
    assert stock(db, "SKU-DT-1KG") == 1
