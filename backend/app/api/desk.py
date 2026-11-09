from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_desk
from app.core.errors import AppError, not_found
from app.db import get_db
from app.models import OrderStatus, Product, Retailer, RetailerSkuAlias, RetailerUnitAlias, User
from app.schemas import (
    AliasOut,
    AliasUpdate,
    DeskOrderDetail,
    DeskOrdersResponse,
    ExportBatchOut,
    ExportCreate,
    ExportPreview,
    LineCorrection,
    ProductOption,
    RetailerOption,
    StatusChange,
)
from app.services import audit, desk, export
from app.services.catalogue import load_products
from app.api.retailer import order_summary

router = APIRouter(prefix="/desk", tags=["order desk"])


@router.get("/orders", response_model=DeskOrdersResponse)
def queue(
    status: str | None = Query(default=None),
    retailer_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_desk),
    db: Session = Depends(get_db),
):
    if status and status not in OrderStatus.ALL:
        raise AppError(422, "invalid_status", "Unknown status filter.")
    res = desk.list_orders(
        db, status=status, retailer_id=retailer_id, date_from=date_from, date_to=date_to, q=q, limit=limit, offset=offset
    )
    return {"items": [order_summary(o) for o in res["items"]], "total": res["total"], "counts": res["counts"]}


@router.get("/retailers", response_model=list[RetailerOption])
def retailers(_: User = Depends(require_desk), db: Session = Depends(get_db)):
    return [
        {"id": r.id, "code": r.code, "shop_name": r.shop_name}
        for r in db.scalars(select(Retailer).order_by(Retailer.shop_name)).all()
    ]


@router.get("/products", response_model=list[ProductOption])
def products(_: User = Depends(require_desk), db: Session = Depends(get_db)):
    """Active products for line corrections (no retailer-specific pricing here)."""
    return [
        {
            "sku_code": p.sku_code,
            "name": p.name,
            "pack_size": p.pack_size_label,
            "available_cases": p.inventory.available_cases if p.inventory else 0,
        }
        for p in load_products(db)
    ]


def _detail(db: Session, order_id: int) -> dict:
    order = desk.get_order(db, order_id)
    extra = desk.order_detail(db, order)
    return {"order": order, "retailer": order.retailer, **extra}


@router.get("/orders/{order_id}", response_model=DeskOrderDetail)
def detail(order_id: int, _: User = Depends(require_desk), db: Session = Depends(get_db)):
    return _detail(db, order_id)


@router.patch("/orders/{order_id}", response_model=DeskOrderDetail)
def change_status(order_id: int, body: StatusChange, user: User = Depends(require_desk), db: Session = Depends(get_db)):
    desk.change_status(db, user, order_id, action=body.action, version=body.version, reason=body.reason)
    return _detail(db, order_id)


@router.patch("/orders/{order_id}/items/{item_id}", response_model=DeskOrderDetail)
def correct_line(
    order_id: int, item_id: int, body: LineCorrection, user: User = Depends(require_desk), db: Session = Depends(get_db)
):
    if body.paid_qty is None and body.sku_code is None:
        raise AppError(422, "no_change", "Provide a new quantity or product.")
    desk.correct_line(
        db,
        user,
        order_id,
        item_id,
        version=body.version,
        paid_qty=body.paid_qty,
        sku_code=body.sku_code,
        reason=body.reason,
        save_alias=body.save_alias,
    )
    return _detail(db, order_id)


# ---------- Tally export ----------
@router.get("/exports/preview", response_model=ExportPreview)
def export_preview(_: User = Depends(require_desk), db: Session = Depends(get_db)):
    p = export.preview(db)
    p["orders"] = [
        {
            "id": o.id,
            "order_number": o.order_number,
            "shop_name": o.retailer.shop_name,
            "grand_total": o.grand_total,
            "line_count": len(o.items),
            "approved_at": o.approved_at,
        }
        for o in p["orders"]
    ]
    return p


def _batch_out(db: Session, b) -> dict:
    creator = db.get(User, b.created_by_user_id)
    return {
        "id": b.id,
        "batch_number": b.batch_number,
        "created_at": b.created_at,
        "created_by": creator.name if creator else None,
        "order_count": b.order_count,
        "row_count": b.row_count,
        "total_amount": b.total_amount,
        "order_numbers": b.order_numbers,
        "file_name": b.file_name,
    }


@router.post("/exports", response_model=ExportBatchOut)
def create_export(body: ExportCreate, user: User = Depends(require_desk), db: Session = Depends(get_db)):
    return _batch_out(db, export.create_export(db, user, body.order_ids))


@router.get("/exports", response_model=list[ExportBatchOut])
def export_history(_: User = Depends(require_desk), db: Session = Depends(get_db)):
    return [_batch_out(db, b) for b in export.list_batches(db)]


@router.get("/exports/{batch_id}/download")
def download(batch_id: int, user: User = Depends(require_desk), db: Session = Depends(get_db)):
    batch = export.get_batch(db, batch_id)
    audit.record(db, actor_user_id=user.id, entity_type="export_batch", entity_id=batch.id, action="downloaded")
    db.commit()
    return Response(
        content=batch.csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{batch.file_name}"'},
    )


# ---------- retailer aliases ----------
@router.get("/aliases", response_model=list[AliasOut])
def aliases(
    retailer_id: int | None = None,
    include_inactive: bool = False,
    _: User = Depends(require_desk),
    db: Session = Depends(get_db),
):
    shops = {r.id: r.shop_name for r in db.scalars(select(Retailer)).all()}
    users = {u.id: u.name for u in db.scalars(select(User)).all()}
    products = {p.id: f"{p.sku_code} · {p.name}" for p in db.scalars(select(Product)).all()}
    out: list[dict] = []
    for model, kind in ((RetailerSkuAlias, "sku"), (RetailerUnitAlias, "unit")):
        stmt = select(model)
        if retailer_id:
            stmt = stmt.where(model.retailer_id == retailer_id)
        if not include_inactive:
            stmt = stmt.where(model.is_active.is_(True))
        for a in db.scalars(stmt).all():
            out.append(
                {
                    "id": a.id,
                    "kind": kind,
                    "retailer_id": a.retailer_id,
                    "shop_name": shops.get(a.retailer_id, "?"),
                    "alias_text": a.alias_text,
                    "target": products.get(a.product_id, "?") if kind == "sku" else f"1 {a.unit}",
                    "source": a.source,
                    "confirmed_by": users.get(a.confirmed_by_user_id) if a.confirmed_by_user_id else None,
                    "created_at": a.created_at,
                    "is_active": a.is_active,
                }
            )
    out.sort(key=lambda a: a["created_at"], reverse=True)
    return out


@router.patch("/aliases/{kind}/{alias_id}", response_model=AliasOut)
def deactivate_alias(
    kind: str, alias_id: int, body: AliasUpdate, user: User = Depends(require_desk), db: Session = Depends(get_db)
):
    model = {"sku": RetailerSkuAlias, "unit": RetailerUnitAlias}.get(kind)
    if model is None:
        raise not_found("Alias")
    alias = db.get(model, alias_id)
    if alias is None:
        raise not_found("Alias")
    alias.is_active = False
    alias.deactivated_at = datetime.now(timezone.utc)
    alias.deactivated_by_user_id = user.id
    audit.record(db, actor_user_id=user.id, entity_type=f"{kind}_alias", entity_id=alias.id, action="deactivated")
    db.commit()
    retailer = db.get(Retailer, alias.retailer_id)
    product = db.get(Product, alias.product_id) if kind == "sku" else None
    confirmer = db.get(User, alias.confirmed_by_user_id) if alias.confirmed_by_user_id else None
    return {
        "id": alias.id,
        "kind": kind,
        "retailer_id": alias.retailer_id,
        "shop_name": retailer.shop_name if retailer else "?",
        "alias_text": alias.alias_text,
        "target": f"{product.sku_code} · {product.name}" if product else f"1 {getattr(alias, 'unit', '')}",
        "source": alias.source,
        "confirmed_by": confirmer.name if confirmer else None,
        "created_at": alias.created_at,
        "is_active": alias.is_active,
    }
