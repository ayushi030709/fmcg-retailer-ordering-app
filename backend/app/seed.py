"""Seed the database with the brief's sample catalogue plus SYNTHETIC demo accounts.

Usage:
    python -m app.seed           # seeds only if the database is empty
    python -m app.seed --reset   # wipes all rows, then seeds (development/demo only)

Data provenance:
  * Products, dealer prices, stock and schemes: the three rows supplied in the
    client brief (data_source = "client_brief"). Nothing else is added.
  * Retailers, people, phone numbers, credit limits, balances, the price override,
    aliases and historical orders: SYNTHETIC demo data (assumption A5).
  * GST 18% on every SKU: DEMO assumption (A1) — the brief gives no GST rate.
"""

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal
from app.models import (
    Inventory,
    Order,
    Product,
    Retailer,
    RetailerPrice,
    RetailerSkuAlias,
    RetailerUnitAlias,
    Role,
    Scheme,
    User,
)
from app.services import desk, export
from app.services.orders import LineInput, create_order

DEMO_GST_RATE = Decimal("18.00")

PRODUCTS = [
    {
        "sku_code": "SKU-BS-075",
        "name": "Glucose biscuit 75 g, case of 96",
        "description": "Glucose biscuit, 75 g pack. Sold by the case (96 packs per case).",
        "pack_size_value": Decimal("75"),
        "pack_size_unit": "g",
        "units_per_case": 96,
        "dealer_price": Decimal("8.10"),
        "stock": 340,
        "keywords": ["biscuit", "biscuits", "glucose biscuit", "glucose", "biskut", "biscut"],
        "scheme": {
            "scheme_type": "buy_x_get_y_free",
            "threshold_qty": 10,
            "free_qty": 1,
            "description": "Buy 10 cases, get 1 free",
        },
    },
    {
        "sku_code": "SKU-DT-1KG",
        "name": "Detergent powder 1 kg, case of 20",
        "description": "Detergent (washing) powder, 1 kg pack. Sold by the case (20 packs per case).",
        "pack_size_value": Decimal("1"),
        "pack_size_unit": "kg",
        "units_per_case": 20,
        "dealer_price": Decimal("101.50"),
        "stock": 85,
        "keywords": ["detergent", "detergent powder", "washing powder", "kapde ka powder", "sarf"],
        "scheme": {
            "scheme_type": "percent_discount",
            "threshold_qty": 5,
            "discount_percent": Decimal("3.00"),
            "description": "3% off 5 or more cases",
        },
    },
    {
        "sku_code": "SKU-TE-250",
        "name": "Tea leaf 250 g, case of 40",
        "description": "Tea leaf (chai patti), 250 g pack. Sold by the case (40 packs per case).",
        "pack_size_value": Decimal("250"),
        "pack_size_unit": "g",
        "units_per_case": 40,
        "dealer_price": Decimal("118.00"),
        "stock": 0,
        "keywords": ["tea", "tea leaf", "chai", "chai patti", "chaipatti", "chai ki patti", "patti"],
        "scheme": None,
    },
]

# SYNTHETIC demo accounts — not real people or shops.
RETAILERS = [
    {
        "phone": "9000000001",
        "name": "Demo Owner A",
        "code": "DEMO-R001",
        "shop_name": "Demo Kirana Store A",
        "city": "Jabalpur",
        "credit_limit": Decimal("50000.00"),
        "outstanding_balance": Decimal("12000.00"),
    },
    {
        "phone": "9000000002",
        "name": "Demo Owner B",
        "code": "DEMO-R002",
        "shop_name": "Demo General Store B",
        "city": "Jabalpur",
        "credit_limit": Decimal("20000.00"),
        "outstanding_balance": Decimal("19750.00"),
    },
]
DESK_USER = {"phone": "9000000009", "email": "desk@demo.local", "name": "Demo Order Desk"}


def reset(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        names = ", ".join(t.name for t in Base.metadata.sorted_tables)
        db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    else:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
    db.commit()


def seed(db: Session) -> bool:
    if db.scalar(select(User).limit(1)) is not None:
        return False

    products: dict[str, Product] = {}
    for spec in PRODUCTS:
        p = Product(
            sku_code=spec["sku_code"],
            name=spec["name"],
            description=spec["description"],
            pack_size_value=spec["pack_size_value"],
            pack_size_unit=spec["pack_size_unit"],
            units_per_case=spec["units_per_case"],
            sell_unit="case",
            dealer_price=spec["dealer_price"],
            gst_rate=DEMO_GST_RATE,
            gst_inclusive=False,
            match_keywords=spec["keywords"],
            data_source="client_brief",
        )
        p.inventory = Inventory(available_cases=spec["stock"])
        if spec["scheme"]:
            p.schemes.append(Scheme(**spec["scheme"]))
        db.add(p)
        products[p.sku_code] = p

    retailers: list[Retailer] = []
    for spec in RETAILERS:
        u = User(phone=spec["phone"], name=spec["name"], role=Role.RETAILER)
        r = Retailer(
            user=u,
            code=spec["code"],
            shop_name=spec["shop_name"],
            owner_name=spec["name"],
            city=spec["city"],
            credit_limit=spec["credit_limit"],
            outstanding_balance=spec["outstanding_balance"],
            is_demo_data=True,
        )
        db.add(r)
        retailers.append(r)
    desk_user = User(phone=DESK_USER["phone"], email=DESK_USER["email"], name=DESK_USER["name"], role=Role.ORDER_DESK)
    db.add(desk_user)
    db.flush()
    ret_a, ret_b = retailers

    # Retailer B: synthetic negotiated price and previously confirmed vocabulary.
    db.add(RetailerPrice(retailer_id=ret_b.id, product_id=products["SKU-DT-1KG"].id, price=Decimal("99.00")))
    db.add(RetailerUnitAlias(retailer_id=ret_b.id, alias_text="peti", unit="case", source="seed_demo"))
    db.add(
        RetailerSkuAlias(
            retailer_id=ret_b.id, alias_text="biscuit chhota", product_id=products["SKU-BS-075"].id, source="seed_demo"
        )
    )
    db.commit()

    user_a, user_b = ret_a.user, ret_b.user

    def place(retailer: Retailer, user: User, lines: list[tuple[str, int]], days_ago: float) -> Order:
        order, _ = create_order(
            db, user, retailer, client_request_id=f"seed-{uuid.uuid4().hex[:16]}",
            lines=[LineInput(sku_code=s, paid_qty=q) for s, q in lines],
        )
        ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
        order.created_at = order.confirmed_at = ts
        order.order_number = f"ORD-{ts:%y%m%d}-{order.id:05d}"
        db.commit()
        return order

    # Historical orders so every desk state is visible without manual setup.
    exported = place(ret_a, user_a, [("SKU-BS-075", 10), ("SKU-DT-1KG", 2)], days_ago=3)
    desk.change_status(db, desk_user, exported.id, action="approve", version=exported.version, reason=None)
    export.create_export(db, desk_user, [exported.id])

    approved = place(ret_a, user_a, [("SKU-BS-075", 20)], days_ago=2)
    desk.change_status(db, desk_user, approved.id, action="approve", version=approved.version, reason=None)

    place(ret_a, user_a, [("SKU-BS-075", 12), ("SKU-DT-1KG", 5)], days_ago=1)  # pending review
    place(ret_b, user_b, [("SKU-DT-1KG", 1)], days_ago=0.5)  # pending review (uses B's price)
    place(ret_b, user_b, [("SKU-BS-075", 30)], days_ago=0.2)  # exceeds B's credit -> on hold

    # The brief's stock figures are treated as CURRENT available stock, i.e. the
    # seeded historical orders are assumed to be already reflected in them.
    for spec in PRODUCTS:
        products[spec["sku_code"]].inventory.available_cases = spec["stock"]
    db.commit()
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete all rows before seeding")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        if args.reset:
            reset(db)
            print("All rows deleted.")
        if seed(db):
            print("Seeded demo data. Retailer A: 9000000001, Retailer B: 9000000002, Desk: 9000000009 (demo OTP).")
        else:
            print("Database already has data; nothing seeded. Use --reset to start over.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
