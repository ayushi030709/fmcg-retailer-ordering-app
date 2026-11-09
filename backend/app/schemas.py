"""Request/response schemas. Money fields are Decimal and serialise as strings."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Qty = Annotated[int, Field(strict=True, ge=1, le=5000)]
Sku = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class OtpRequest(BaseModel):
    identifier: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class OtpRequestResponse(BaseModel):
    challenge_id: str
    expires_in: int
    message: str
    demo_mode: bool
    demo_hint: str | None = None


class OtpVerify(BaseModel):
    challenge_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    otp: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{4,8}$")]


class RetailerProfile(ORM):
    id: int
    code: str
    shop_name: str
    owner_name: str
    city: str
    credit_limit: Decimal
    outstanding_balance: Decimal
    is_demo_data: bool


class CreditSummary(BaseModel):
    credit_limit: Decimal
    outstanding_balance: Decimal
    open_orders_total: Decimal
    available_credit: Decimal
    order_total: Decimal
    within_limit: bool


class Me(BaseModel):
    id: int
    name: str
    role: str
    phone: str | None
    email: str | None
    retailer: RetailerProfile | None = None
    credit: CreditSummary | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Me


# ---------- catalogue ----------
class SchemeOut(BaseModel):
    type: str
    description: str
    threshold_qty: int
    free_qty: int | None
    discount_percent: Decimal | None


class CatalogueItem(BaseModel):
    product_id: int
    sku_code: str
    name: str
    description: str
    pack_size: str
    units_per_case: int
    sell_unit: str
    dealer_price: Decimal
    gst_rate: Decimal
    gst_inclusive: bool
    image_url: str | None
    available_cases: int
    stock_status: Literal["in_stock", "low_stock", "out_of_stock"]
    scheme: SchemeOut | None
    data_source: str


class CatalogueResponse(BaseModel):
    items: list[CatalogueItem]
    gst_note: str


# ---------- orders ----------
class OrderLineIn(BaseModel):
    sku_code: Sku
    paid_qty: Qty
    original_phrase: Annotated[str, StringConstraints(max_length=500)] | None = None
    unit_confirmed: bool = True
    remember_product_alias: bool = False
    unit_alias: Annotated[str, StringConstraints(max_length=40)] | None = None
    remember_unit_alias: bool = False


class OrderPreviewRequest(BaseModel):
    lines: list[OrderLineIn] = Field(max_length=50)


class OrderCreateRequest(BaseModel):
    client_request_id: Annotated[str, StringConstraints(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    lines: list[OrderLineIn] = Field(min_length=1, max_length=50)
    ai_extraction_id: int | None = None


class PricedLineOut(BaseModel):
    sku_code: str
    product_id: int
    name: str
    pack_size: str
    paid_qty: int
    free_qty: int
    fulfil_qty: int
    unit_price: Decimal
    gross_amount: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    gst_rate: Decimal
    gst_inclusive: bool
    tax_amount: Decimal
    line_total: Decimal
    scheme_applied: str | None
    hints: list[str]
    available_cases: int
    stock_status: str
    original_phrase: str | None


class IssueOut(BaseModel):
    code: str
    message: str
    sku_code: str | None
    blocking: bool


class Totals(BaseModel):
    subtotal: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    paid_cases: int
    free_cases: int


class OrderPreviewResponse(BaseModel):
    lines: list[PricedLineOut]
    issues: list[IssueOut]
    totals: Totals
    credit: CreditSummary
    can_submit: bool
    will_be_held: bool
    warnings: list[str]


class OrderItemOut(ORM):
    id: int
    product_id: int
    sku_code: str
    product_name: str
    paid_qty: int
    free_qty: int
    unit_price: Decimal
    gross_amount: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    gst_rate: Decimal
    gst_inclusive: bool
    tax_amount: Decimal
    line_total: Decimal
    scheme_applied: str | None
    original_phrase: str | None


class RetailerBrief(ORM):
    id: int
    code: str
    shop_name: str
    city: str


class OrderOut(ORM):
    id: int
    order_number: str
    status: str
    source: str
    subtotal: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    hold_reason: str | None
    status_note: str | None
    created_at: datetime
    approved_at: datetime | None
    exported_at: datetime | None
    version: int
    items: list[OrderItemOut]


class OrderCreateResponse(BaseModel):
    order: OrderOut
    created: bool
    message: str


class OrderSummary(ORM):
    id: int
    order_number: str
    status: str
    source: str
    grand_total: Decimal
    hold_reason: str | None
    created_at: datetime
    line_count: int
    retailer: RetailerBrief


class RetailerOrdersResponse(BaseModel):
    items: list[OrderSummary]


# ---------- AI ----------
class ExtractRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    language_hint: Literal["hi", "hi-Latn", "en", "mixed"] | None = None


class Clarification(BaseModel):
    type: Literal["unit", "sku", "quantity"]
    question: str
    unit_text: str | None = None


class Alternative(BaseModel):
    sku_code: str
    name: str
    pack_size: str
    score: float
    stock_status: str
    available_cases: int


class ExtractedLine(BaseModel):
    line_id: int
    original_text: str
    product_phrase: str
    ai_description: str | None
    ai_reasoning: str | None
    ai_suggested_sku: str | None
    quantity: int | None
    unit: Literal["case", "piece", "unknown"]
    unit_text: str | None
    unit_confirmed: bool
    unit_source: str
    candidate: CatalogueItem | None
    confidence: float
    confidence_band: Literal["high", "medium", "low", "none"]
    evidence: list[str]
    alternatives: list[Alternative]
    needs_sku_choice: bool
    clarifications: list[Clarification]
    out_of_stock: bool
    status: Literal["ready", "needs_attention", "no_match", "out_of_stock"]


class ExtractResponse(BaseModel):
    extraction_id: int
    provider: str
    model: str | None
    is_fallback: bool
    message_language: str | None
    original_message: str
    lines: list[ExtractedLine]
    warnings: list[str]
    status: str = "extracted"
    order_id: int | None = None


class AiStatus(BaseModel):
    provider: str
    model: str | None
    configured: bool
    sample_message: str


# ---------- desk ----------
class DeskOrdersResponse(BaseModel):
    items: list[OrderSummary]
    total: int
    counts: dict[str, int]


class AuditOut(BaseModel):
    id: int
    action: str
    actor: str | None
    actor_role: str | None
    before: dict | None
    after: dict | None
    note: str | None
    created_at: datetime


class AiMessageOut(BaseModel):
    message: str
    provider: str
    model: str | None


class DeskOrderDetail(BaseModel):
    order: OrderOut
    retailer: RetailerProfile
    credit: CreditSummary
    audit: list[AuditOut]
    ai_message: AiMessageOut | None
    stock: dict[int, int]
    allowed_actions: list[str]


class StatusChange(BaseModel):
    action: Literal["approve", "hold", "release", "reject"]
    version: int
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class LineCorrection(BaseModel):
    version: int
    paid_qty: Qty | None = None
    sku_code: Sku | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    save_alias: bool = False


class ProductOption(BaseModel):
    sku_code: str
    name: str
    pack_size: str
    available_cases: int


class RetailerOption(BaseModel):
    id: int
    code: str
    shop_name: str


class ExportOrderOut(BaseModel):
    id: int
    order_number: str
    shop_name: str
    grand_total: Decimal
    line_count: int
    approved_at: datetime | None


class ExportPreview(BaseModel):
    orders: list[ExportOrderOut]
    order_count: int
    row_count: int
    total_amount: Decimal
    columns: list[str]
    csv_preview: str


class ExportCreate(BaseModel):
    order_ids: list[int] | None = Field(default=None, max_length=500)


class ExportBatchOut(ORM):
    id: int
    batch_number: str
    created_at: datetime
    created_by: str | None = None
    order_count: int
    row_count: int
    total_amount: Decimal
    order_numbers: list[str]
    file_name: str


class AliasOut(BaseModel):
    id: int
    kind: Literal["sku", "unit"]
    retailer_id: int
    shop_name: str
    alias_text: str
    target: str
    source: str
    confirmed_by: str | None
    created_at: datetime
    is_active: bool


class AliasUpdate(BaseModel):
    is_active: Literal[False]


class DateRange(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
