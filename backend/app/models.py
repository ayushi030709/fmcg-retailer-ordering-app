"""SQLAlchemy models.

Money is always ``Numeric`` (mapped to ``Decimal``) — never float.
Enumerations are stored as short strings and validated in the service layer,
which keeps Alembic migrations simple and portable.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every database.

    PostgreSQL keeps the offset natively; SQLite (tests / quick local demo) does not,
    so values are normalised to UTC on write and re-labelled as UTC on read.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


MONEY = Numeric(14, 2)
RATE = Numeric(5, 2)


class Role:
    RETAILER = "retailer"
    ORDER_DESK = "order_desk"
    ALL = (RETAILER, ORDER_DESK)


class OrderStatus:
    PENDING_REVIEW = "pending_review"
    ON_HOLD = "on_hold"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPORTED = "exported"
    ALL = (PENDING_REVIEW, ON_HOLD, APPROVED, REJECTED, EXPORTED)
    # Orders that count against a retailer's credit exposure.
    CREDIT_EXPOSURE = (PENDING_REVIEW, APPROVED)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    retailer: Mapped["Retailer | None"] = relationship(back_populates="user", uselist=False)

    __table_args__ = (CheckConstraint("role in ('retailer','order_desk')", name="ck_users_role"),)


class OtpChallenge(Base):
    """A one-time-password challenge. Only a salted HMAC of the code is stored."""

    __tablename__ = "otp_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    otp_hash: Mapped[str] = mapped_column(String(128))
    salt: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Retailer(Base):
    __tablename__ = "retailers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    shop_name: Mapped[str] = mapped_column(String(160))
    owner_name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80))
    credit_limit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    outstanding_balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="retailer")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    pack_size_value: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    pack_size_unit: Mapped[str] = mapped_column(String(10))  # g | kg | ml | l
    units_per_case: Mapped[int] = mapped_column(Integer)
    sell_unit: Mapped[str] = mapped_column(String(10), default="case")
    dealer_price: Mapped[Decimal] = mapped_column(MONEY)  # per case
    gst_rate: Mapped[Decimal] = mapped_column(RATE)
    gst_inclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    image_url: Mapped[str | None] = mapped_column(String(500))
    # Deterministic matching vocabulary (common English/Hinglish product words).
    match_keywords: Mapped[list] = mapped_column(JSON, default=list)
    # "client_brief" for the three supplied SKUs; "synthetic_demo" for anything added.
    data_source: Mapped[str] = mapped_column(String(20), default="client_brief")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    inventory: Mapped["Inventory"] = relationship(back_populates="product", uselist=False)
    schemes: Mapped[list["Scheme"]] = relationship(back_populates="product")

    @property
    def pack_size_label(self) -> str:
        v = self.pack_size_value.normalize()
        v_str = format(v, "f")
        return f"{v_str} {self.pack_size_unit}"


class RetailerPrice(Base):
    """Optional retailer-specific dealer price override (per case)."""

    __tablename__ = "retailer_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    price: Mapped[Decimal] = mapped_column(MONEY)
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("retailer_id", "product_id", name="uq_retailer_price"),)


class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True)
    available_cases: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    product: Mapped[Product] = relationship(back_populates="inventory")

    __table_args__ = (CheckConstraint("available_cases >= 0", name="ck_inventory_non_negative"),)


class Scheme(Base):
    __tablename__ = "schemes"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    scheme_type: Mapped[str] = mapped_column(String(30))  # buy_x_get_y_free | percent_discount
    threshold_qty: Mapped[int] = mapped_column(Integer)
    free_qty: Mapped[int | None] = mapped_column(Integer)
    discount_percent: Mapped[Decimal | None] = mapped_column(RATE)
    description: Mapped[str] = mapped_column(String(200))
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[Product] = relationship(back_populates="schemes")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str | None] = mapped_column(String(30), unique=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(10))  # manual | ai
    client_request_id: Mapped[str] = mapped_column(String(64))
    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    discount_total: Mapped[Decimal] = mapped_column(MONEY)
    taxable_total: Mapped[Decimal] = mapped_column(MONEY)
    tax_total: Mapped[Decimal] = mapped_column(MONEY)
    grand_total: Mapped[Decimal] = mapped_column(MONEY)
    hold_reason: Mapped[str | None] = mapped_column(String(500))
    status_note: Mapped[str | None] = mapped_column(String(500))
    credit_snapshot: Mapped[dict | None] = mapped_column(JSON)
    ai_extraction_id: Mapped[int | None] = mapped_column(ForeignKey("ai_extractions.id"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    export_batch_id: Mapped[int | None] = mapped_column(ForeignKey("export_batches.id"))
    exported_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1)

    retailer: Mapped[Retailer] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )

    __table_args__ = (
        UniqueConstraint("retailer_id", "client_request_id", name="uq_orders_idempotency"),
        CheckConstraint(
            "status in ('pending_review','on_hold','approved','rejected','exported')", name="ck_orders_status"
        ),
        CheckConstraint("source in ('manual','ai')", name="ck_orders_source"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    sku_code: Mapped[str] = mapped_column(String(40))
    product_name: Mapped[str] = mapped_column(String(160))
    paid_qty: Mapped[int] = mapped_column(Integer)
    free_qty: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY)
    discount_percent: Mapped[Decimal] = mapped_column(RATE, default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(MONEY)
    taxable_amount: Mapped[Decimal] = mapped_column(MONEY)
    gst_rate: Mapped[Decimal] = mapped_column(RATE)
    gst_inclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_amount: Mapped[Decimal] = mapped_column(MONEY)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    scheme_applied: Mapped[str | None] = mapped_column(String(200))
    original_phrase: Mapped[str | None] = mapped_column(String(500))

    order: Mapped[Order] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("paid_qty > 0", name="ck_order_items_paid_qty_positive"),
        CheckConstraint("free_qty >= 0", name="ck_order_items_free_qty_non_negative"),
    )


class AiExtraction(Base):
    __tablename__ = "ai_extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    original_message: Mapped[str] = mapped_column(Text)
    language_hint: Mapped[str | None] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))  # extracted | failed | confirmed
    llm_output: Mapped[dict | None] = mapped_column(JSON)  # validated model output
    result: Mapped[dict | None] = mapped_column(JSON)  # lines returned to the UI after matching
    error_message: Mapped[str | None] = mapped_column(String(500))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    order_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RetailerSkuAlias(Base):
    """A retailer's own phrase for a product, learned only from confirmed corrections."""

    __tablename__ = "retailer_sku_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"), index=True)
    alias_text: Mapped[str] = mapped_column(String(200))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    source: Mapped[str] = mapped_column(String(30))  # retailer_confirmed | desk_correction | seed_demo
    confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deactivated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    product: Mapped[Product] = relationship()


class RetailerUnitAlias(Base):
    """A retailer's own word for a selling unit (e.g. 'peti' meaning one case)."""

    __tablename__ = "retailer_unit_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"), index=True)
    alias_text: Mapped[str] = mapped_column(String(40))
    unit: Mapped[str] = mapped_column(String(10))  # case
    source: Mapped[str] = mapped_column(String(30))
    confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deactivated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ExportBatch(Base):
    __tablename__ = "export_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_number: Mapped[str | None] = mapped_column(String(30), unique=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    order_count: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    total_amount: Mapped[Decimal] = mapped_column(MONEY)
    order_numbers: Mapped[list] = mapped_column(JSON, default=list)
    file_name: Mapped[str] = mapped_column(String(80))
    csv_content: Mapped[str] = mapped_column(Text)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(40))
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
