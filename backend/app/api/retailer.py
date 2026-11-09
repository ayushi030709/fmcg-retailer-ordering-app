from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_retailer, require_role
from app.core.errors import not_found
from app.db import get_db
from app.models import Order, Retailer, Role, User
from app.schemas import (
    CatalogueResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    OrderOut,
    OrderPreviewRequest,
    OrderPreviewResponse,
    RetailerOrdersResponse,
)
from app.services.catalogue import list_catalogue
from app.services.orders import LineInput, create_order, preview_order

router = APIRouter(tags=["retailer"])

GST_NOTE = (
    "Dealer prices are per case and EXCLUDE GST (demo assumption A1). GST is added at checkout at the "
    "product's configured demo rate."
)


def order_summary(o: Order) -> dict:
    return {
        "id": o.id,
        "order_number": o.order_number,
        "status": o.status,
        "source": o.source,
        "grand_total": o.grand_total,
        "hold_reason": o.hold_reason,
        "created_at": o.created_at,
        "line_count": len(o.items),
        "retailer": o.retailer,
    }


def _lines(body) -> list[LineInput]:
    return [LineInput(**line.model_dump()) for line in body.lines]


@router.get("/retailer/catalogue", response_model=CatalogueResponse)
def catalogue(
    q: str | None = Query(default=None, max_length=80),
    retailer: Retailer = Depends(get_current_retailer),
    db: Session = Depends(get_db),
):
    return {"items": list_catalogue(db, retailer, q), "gst_note": GST_NOTE}


@router.post("/orders/preview", response_model=OrderPreviewResponse)
def preview(body: OrderPreviewRequest, retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    return preview_order(db, retailer, _lines(body))


@router.post("/orders", response_model=OrderCreateResponse)
def place_order(
    body: OrderCreateRequest,
    user: User = Depends(require_role(Role.RETAILER)),
    retailer: Retailer = Depends(get_current_retailer),
    db: Session = Depends(get_db),
):
    order, created = create_order(
        db,
        user,
        retailer,
        client_request_id=body.client_request_id,
        lines=_lines(body),
        ai_extraction_id=body.ai_extraction_id,
    )
    if not created:
        msg = "This order was already placed — showing the original order."
    elif order.status == "on_hold":
        msg = "Order placed and held for credit review by the order desk."
    else:
        msg = "Order placed. The order desk will review it shortly."
    return {"order": order, "created": created, "message": msg}


@router.get("/retailer/orders", response_model=RetailerOrdersResponse)
def my_orders(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.retailer))
        .where(Order.retailer_id == retailer.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(100)
    ).all()
    return {"items": [order_summary(o) for o in orders]}


@router.get("/retailer/orders/{order_id}", response_model=OrderOut)
def my_order(order_id: int, retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    order = db.scalar(
        select(Order).options(selectinload(Order.items)).where(Order.id == order_id, Order.retailer_id == retailer.id)
    )
    if order is None:
        raise not_found("Order")
    return order
