"""Catalogue reads: retailer-specific price, stock status and active scheme."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Inventory, Product, Retailer, RetailerPrice, Scheme
from app.services.scheme_engine import SchemeConfig

# Demo assumption: at or below this many cases a product is shown as "low stock".
LOW_STOCK_CASES = 20


def stock_status(available_cases: int) -> str:
    if available_cases <= 0:
        return "out_of_stock"
    if available_cases <= LOW_STOCK_CASES:
        return "low_stock"
    return "in_stock"


def scheme_config(scheme: Scheme) -> SchemeConfig:
    return SchemeConfig(
        scheme_type=scheme.scheme_type,
        threshold_qty=scheme.threshold_qty,
        free_qty=scheme.free_qty,
        discount_percent=scheme.discount_percent,
        description=scheme.description,
        starts_on=scheme.starts_on,
        ends_on=scheme.ends_on,
        is_active=scheme.is_active,
    )


def active_scheme(product: Product, on: date | None = None) -> SchemeConfig | None:
    on = on or date.today()
    for s in sorted(product.schemes, key=lambda s: s.id):
        cfg = scheme_config(s)
        if cfg.applies_on(on):
            return cfg
    return None


def retailer_prices(db: Session, retailer: Retailer, product_ids: list[int]) -> dict[int, Decimal]:
    if not product_ids:
        return {}
    rows = db.execute(
        select(RetailerPrice.product_id, RetailerPrice.price).where(
            RetailerPrice.retailer_id == retailer.id, RetailerPrice.product_id.in_(product_ids)
        )
    ).all()
    return {pid: price for pid, price in rows}


def price_for(product: Product, overrides: dict[int, Decimal]) -> Decimal:
    return overrides.get(product.id, product.dealer_price)


def load_products(db: Session, *, active_only: bool = True) -> list[Product]:
    stmt = select(Product).options(selectinload(Product.schemes), selectinload(Product.inventory))
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    return list(db.scalars(stmt.order_by(Product.sku_code)).all())


def catalogue_item(product: Product, price: Decimal, on: date | None = None) -> dict:
    scheme = active_scheme(product, on)
    available = product.inventory.available_cases if product.inventory else 0
    return {
        "product_id": product.id,
        "sku_code": product.sku_code,
        "name": product.name,
        "description": product.description,
        "pack_size": product.pack_size_label,
        "units_per_case": product.units_per_case,
        "sell_unit": product.sell_unit,
        "dealer_price": price,
        "gst_rate": product.gst_rate,
        "gst_inclusive": product.gst_inclusive,
        "image_url": product.image_url,
        "available_cases": max(available, 0),
        "stock_status": stock_status(available),
        "scheme": (
            {
                "type": scheme.scheme_type,
                "description": scheme.description,
                "threshold_qty": scheme.threshold_qty,
                "free_qty": scheme.free_qty,
                "discount_percent": scheme.discount_percent,
            }
            if scheme
            else None
        ),
        "data_source": product.data_source,
    }


def list_catalogue(db: Session, retailer: Retailer, q: str | None = None) -> list[dict]:
    products = load_products(db)
    if q:
        needle = q.strip().lower()
        products = [
            p
            for p in products
            if needle in p.name.lower()
            or needle in p.sku_code.lower()
            or any(needle in str(k).lower() for k in (p.match_keywords or []))
        ]
    overrides = retailer_prices(db, retailer, [p.id for p in products])
    return [catalogue_item(p, price_for(p, overrides)) for p in products]


def inventory_for_update(db: Session, product_ids: list[int]) -> dict[int, Inventory]:
    """Lock inventory rows in a stable order (prevents deadlocks between concurrent orders)."""
    if not product_ids:
        return {}
    # populate_existing: rows may already be cached in this session from an unlocked
    # read; without it we would act on the stale count we saw *before* the lock.
    rows = db.scalars(
        select(Inventory)
        .where(Inventory.product_id.in_(sorted(set(product_ids))))
        .order_by(Inventory.product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return {r.product_id: r for r in rows}
