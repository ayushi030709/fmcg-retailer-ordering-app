"""Tally-friendly CSV export of approved orders.

Assumption A7: the client's Tally import format is not specified. This export
uses stable, documented columns (one row per order line) that map naturally
onto a Tally sales-order voucher; the final import mapping must be confirmed
against the client's Tally configuration.

Duplicate prevention: an order can be in at most one export batch. Exported
orders move to status ``exported``; re-downloading a past batch returns the
identical stored file and never re-exports orders.
"""

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError, not_found
from app.core.money import ZERO
from app.models import ExportBatch, Order, OrderStatus, User
from app.services import audit

IST = ZoneInfo("Asia/Kolkata")

CSV_COLUMNS = [
    "Voucher Date",
    "Voucher Number",
    "Voucher Type",
    "Party Code",
    "Party Name",
    "Item Code",
    "Item Name",
    "Billed Qty",
    "Free Qty",
    "Actual Qty",
    "Unit",
    "Rate",
    "Gross Amount",
    "Discount %",
    "Discount Amount",
    "Taxable Value",
    "GST Rate %",
    "GST Amount",
    "Line Amount",
    "Order Total",
    "Order Source",
]


def _safe_cell(value) -> str:
    """Neutralise spreadsheet formula injection in text cells."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def eligible_orders(db: Session, *, lock: bool = False) -> list[Order]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.retailer))
        .where(Order.status == OrderStatus.APPROVED, Order.export_batch_id.is_(None))
        .order_by(Order.approved_at, Order.id)
    )
    if lock:
        stmt = stmt.with_for_update(of=Order).execution_options(populate_existing=True)
    return list(db.scalars(stmt).all())


def build_csv(orders: list[Order]) -> tuple[str, int]:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    rows = 0
    for order in orders:
        voucher_date = order.created_at.astimezone(IST).strftime("%d-%m-%Y")
        for item in order.items:
            writer.writerow(
                [
                    _safe_cell(voucher_date),
                    _safe_cell(order.order_number),
                    "Sales Order",
                    _safe_cell(order.retailer.code),
                    _safe_cell(order.retailer.shop_name),
                    _safe_cell(item.sku_code),
                    _safe_cell(item.product_name),
                    item.paid_qty,
                    item.free_qty,
                    item.paid_qty + item.free_qty,
                    "case",
                    _safe_cell(item.unit_price),
                    _safe_cell(item.gross_amount),
                    _safe_cell(item.discount_percent),
                    _safe_cell(item.discount_amount),
                    _safe_cell(item.taxable_amount),
                    _safe_cell(item.gst_rate),
                    _safe_cell(item.tax_amount),
                    _safe_cell(item.line_total),
                    _safe_cell(order.grand_total),
                    order.source,
                ]
            )
            rows += 1
    return buf.getvalue(), rows


def preview(db: Session) -> dict:
    orders = eligible_orders(db)
    csv_text, rows = build_csv(orders)
    return {
        "orders": orders,
        "order_count": len(orders),
        "row_count": rows,
        "total_amount": sum((o.grand_total for o in orders), ZERO),
        "columns": CSV_COLUMNS,
        "csv_preview": "\r\n".join(csv_text.split("\r\n")[:21]),
    }


def create_export(db: Session, desk_user: User, order_ids: list[int] | None) -> ExportBatch:
    try:
        orders = eligible_orders(db, lock=True)
        if order_ids:
            wanted = set(order_ids)
            found = {o.id for o in orders}
            missing = sorted(wanted - found)
            if missing:
                raise AppError(
                    409,
                    "not_exportable",
                    "Some selected orders are not approved or were already exported.",
                    details={"order_ids": missing},
                )
            orders = [o for o in orders if o.id in wanted]
        if not orders:
            raise AppError(409, "nothing_to_export", "There are no approved orders waiting for export.")

        csv_text, rows = build_csv(orders)
        now = datetime.now(timezone.utc)
        batch = ExportBatch(
            created_by_user_id=desk_user.id,
            created_at=now,
            order_count=len(orders),
            row_count=rows,
            total_amount=sum((o.grand_total for o in orders), ZERO),
            order_numbers=[o.order_number for o in orders],
            file_name="pending.csv",
            csv_content=csv_text,
        )
        db.add(batch)
        db.flush()
        batch.batch_number = f"EXP-{now.astimezone(IST):%y%m%d}-{batch.id:04d}"
        batch.file_name = f"tally-orders-{batch.batch_number}.csv"
        for o in orders:
            o.status = OrderStatus.EXPORTED
            o.export_batch_id = batch.id
            o.exported_at = now
            o.version += 1
            audit.record(
                db,
                actor_user_id=desk_user.id,
                entity_type="order",
                entity_id=o.id,
                action="exported",
                before={"status": OrderStatus.APPROVED},
                after={"status": OrderStatus.EXPORTED, "batch": batch.batch_number},
            )
        audit.record(
            db,
            actor_user_id=desk_user.id,
            entity_type="export_batch",
            entity_id=batch.id,
            action="created",
            after={"orders": batch.order_numbers, "rows": rows, "total": batch.total_amount},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return batch


def list_batches(db: Session) -> list[ExportBatch]:
    return list(db.scalars(select(ExportBatch).order_by(ExportBatch.created_at.desc(), ExportBatch.id.desc())).all())


def get_batch(db: Session, batch_id: int) -> ExportBatch:
    batch = db.get(ExportBatch, batch_id)
    if batch is None:
        raise not_found("Export batch")
    return batch
