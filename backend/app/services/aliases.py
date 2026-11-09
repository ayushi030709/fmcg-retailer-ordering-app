"""Retailer-specific product and unit aliases (correction learning).

Only confirmed corrections become aliases — never an unconfirmed AI guess.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RetailerSkuAlias, RetailerUnitAlias
from app.services import audit
from app.services.ai.parsing import normalize


def active_sku_aliases(db: Session, retailer_id: int) -> list[RetailerSkuAlias]:
    return list(
        db.scalars(
            select(RetailerSkuAlias).where(
                RetailerSkuAlias.retailer_id == retailer_id, RetailerSkuAlias.is_active.is_(True)
            )
        ).all()
    )


def active_unit_aliases(db: Session, retailer_id: int) -> list[RetailerUnitAlias]:
    return list(
        db.scalars(
            select(RetailerUnitAlias).where(
                RetailerUnitAlias.retailer_id == retailer_id, RetailerUnitAlias.is_active.is_(True)
            )
        ).all()
    )


def upsert_sku_alias(
    db: Session, *, retailer_id: int, alias_text: str, product_id: int, source: str, user_id: int
) -> RetailerSkuAlias | None:
    text = normalize(alias_text)
    if not text or len(text) > 200:
        return None
    now = datetime.now(timezone.utc)
    for existing in active_sku_aliases(db, retailer_id):
        if existing.alias_text == text:
            if existing.product_id == product_id:
                return existing
            # A correction supersedes the old mapping; keep the old row for audit.
            existing.is_active = False
            existing.deactivated_at = now
            existing.deactivated_by_user_id = user_id
            audit.record(
                db, actor_user_id=user_id, entity_type="sku_alias", entity_id=existing.id, action="superseded"
            )
    alias = RetailerSkuAlias(
        retailer_id=retailer_id, alias_text=text, product_id=product_id, source=source, confirmed_by_user_id=user_id
    )
    db.add(alias)
    db.flush()
    audit.record(
        db,
        actor_user_id=user_id,
        entity_type="sku_alias",
        entity_id=alias.id,
        action="created",
        after={"retailer_id": retailer_id, "alias_text": text, "product_id": product_id, "source": source},
    )
    return alias


def upsert_unit_alias(
    db: Session, *, retailer_id: int, alias_text: str, unit: str, source: str, user_id: int
) -> RetailerUnitAlias | None:
    text = normalize(alias_text)
    if not text or len(text) > 40 or unit != "case":
        return None
    for existing in active_unit_aliases(db, retailer_id):
        if existing.alias_text == text:
            return existing
    alias = RetailerUnitAlias(
        retailer_id=retailer_id, alias_text=text, unit=unit, source=source, confirmed_by_user_id=user_id
    )
    db.add(alias)
    db.flush()
    audit.record(
        db,
        actor_user_id=user_id,
        entity_type="unit_alias",
        entity_id=alias.id,
        action="created",
        after={"retailer_id": retailer_id, "alias_text": text, "unit": unit, "source": source},
    )
    return alias
