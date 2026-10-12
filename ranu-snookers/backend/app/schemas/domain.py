"""API contracts (Pydantic v2). Input models validate; output models shape responses."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import (
    BookingSource,
    DetectionMethod,
    DeviceType,
    InventoryTxnType,
    MembershipStatus,
    PaymentMethod,
    TableStatus,
    TournamentFormat,
)
from app.schemas.common import ORM, CustomerIn

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


# ============================================================================ auth
class LoginIn(BaseModel):
    identifier: str = Field(min_length=2, max_length=160, description="username, email or phone")
    password: str = Field(min_length=1, max_length=200)


class PinLoginIn(BaseModel):
    username: str
    pin: str = Field(min_length=4, max_length=8)


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class RoleAssignment(BaseModel):
    role_code: str
    branch_id: uuid.UUID | None = None


class UserOut(ORM):
    id: uuid.UUID
    username: str
    full_name: str
    email: str | None
    phone: str | None
    is_active: bool
    customer_id: uuid.UUID | None
    last_login_at: datetime | None


class MeOut(BaseModel):
    user: UserOut
    roles: list[dict]
    permissions: list[str]
    branch_ids: list[uuid.UUID] | None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None
    user: UserOut


class UserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[a-zA-Z0-9_.-]+$")
    full_name: str
    email: EmailStr | None = None
    phone: str | None = None
    password: str | None = Field(default=None, min_length=8)
    pin: str | None = Field(default=None, pattern=r"^\d{4,8}$")
    roles: list[RoleAssignment] = []


class UserUpdateIn(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)
    pin: str | None = Field(default=None, pattern=r"^\d{4,8}$")
    roles: list[RoleAssignment] | None = None


class RoleOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    description: str
    is_system: bool
    permissions: list[PermissionOut]


class PermissionOut(ORM):
    code: str
    description: str


class UserWithRolesOut(UserOut):
    roles: list[dict] = []


# ============================================================================ org
class BranchOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    address: str | None
    phone: str | None
    email: str | None
    timezone: str
    currency: str
    opening_time: str
    closing_time: str
    is_active: bool


class BranchIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    timezone: str = "Asia/Kolkata"
    currency: str = "INR"
    opening_time: str = Field("10:00", pattern=HHMM)
    closing_time: str = Field("02:00", pattern=HHMM)
    club_id: uuid.UUID | None = None


class BranchUpdateIn(BaseModel):
    name: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    timezone: str | None = None
    opening_time: str | None = Field(None, pattern=HHMM)
    closing_time: str | None = Field(None, pattern=HHMM)
    is_active: bool | None = None


class HolidayIn(BaseModel):
    day: date
    name: str


# ============================================================================ tables & pricing
class GameTypeOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    default_hourly_rate: Decimal
    color: str
    is_active: bool


class GameTypeIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    name: str
    description: str | None = None
    default_hourly_rate: Decimal = Field(ge=0)
    color: str = "#146c3a"


class TableOut(ORM):
    id: uuid.UUID
    branch_id: uuid.UUID
    table_number: int
    name: str
    game_type_id: uuid.UUID
    game_type: GameTypeOut
    status: str
    hourly_rate: Decimal
    peak_rate: Decimal | None
    off_peak_rate: Decimal | None
    minimum_booking_duration: int
    maximum_booking_duration: int
    is_active: bool
    is_online_bookable: bool
    status_changed_at: datetime | None


class TableAdminOut(TableOut):
    qr_token: str


class PublicTableOut(ORM):
    id: uuid.UUID
    table_number: int
    name: str
    game_type: GameTypeOut
    hourly_rate: Decimal
    minimum_booking_duration: int
    maximum_booking_duration: int


class TableIn(BaseModel):
    table_number: int = Field(ge=1, le=999)
    name: str
    game_type_id: uuid.UUID
    hourly_rate: Decimal | None = Field(default=None, ge=0)
    peak_rate: Decimal | None = Field(default=None, ge=0)
    off_peak_rate: Decimal | None = Field(default=None, ge=0)
    minimum_booking_duration: int = Field(30, ge=5, le=720)
    maximum_booking_duration: int = Field(240, ge=5, le=1440)
    is_online_bookable: bool = True
    sort_order: int = 0


class TableUpdateIn(BaseModel):
    name: str | None = None
    game_type_id: uuid.UUID | None = None
    hourly_rate: Decimal | None = Field(default=None, ge=0)
    peak_rate: Decimal | None = Field(default=None, ge=0)
    off_peak_rate: Decimal | None = Field(default=None, ge=0)
    minimum_booking_duration: int | None = Field(None, ge=5)
    maximum_booking_duration: int | None = Field(None, ge=5)
    is_active: bool | None = None
    is_online_bookable: bool | None = None
    sort_order: int | None = None
    reason: str | None = None


class TableStatusIn(BaseModel):
    status: Literal[TableStatus.AVAILABLE, TableStatus.MAINTENANCE, TableStatus.BLOCKED]
    reason: str | None = None


class PricingRuleIn(BaseModel):
    name: str
    kind: Literal["STANDARD", "PEAK", "OFF_PEAK", "HAPPY_HOUR", "HOLIDAY", "PROMO", "MEMBER", "WEEKEND"] = "STANDARD"
    game_type_id: uuid.UUID | None = None
    table_id: uuid.UUID | None = None
    day_type: Literal["ANY", "WEEKDAY", "WEEKEND", "HOLIDAY"] = "ANY"
    days_of_week: list[int] | None = None
    start_time: str | None = Field(None, pattern=HHMM)
    end_time: str | None = Field(None, pattern=HHMM)
    valid_from: date | None = None
    valid_to: date | None = None
    customer_segment: Literal["ANY", "MEMBER", "NON_MEMBER"] = "ANY"
    rate_per_hour: Decimal | None = Field(None, ge=0)
    rate_multiplier: float | None = Field(None, gt=0, le=10)
    priority: int = 100
    is_active: bool = True

    @field_validator("days_of_week")
    @classmethod
    def _dow(cls, v):
        if v is not None and any(d < 0 or d > 6 for d in v):
            raise ValueError("days_of_week must contain 0 (Mon) .. 6 (Sun)")
        return v


class PricingRuleOut(ORM, PricingRuleIn):
    id: uuid.UUID
    branch_id: uuid.UUID


class PriceSegmentOut(BaseModel):
    start: datetime
    end: datetime
    minutes: int
    rate_per_hour: Decimal
    rule: str
    amount: Decimal


class QuoteOut(BaseModel):
    amount: Decimal
    deposit: Decimal
    tax: Decimal
    segments: list[PriceSegmentOut]


# ============================================================================ customers
class CustomerCreateIn(CustomerIn):
    date_of_birth: date | None = None
    preferred_game_type_id: uuid.UUID | None = None
    notes: str | None = None
    home_branch_id: uuid.UUID | None = None
    marketing_opt_in: bool = False
    referral_code_used: str | None = None


class CustomerUpdateIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    date_of_birth: date | None = None
    preferred_game_type_id: uuid.UUID | None = None
    notes: str | None = None
    marketing_opt_in: bool | None = None


class CustomerOut(ORM):
    id: uuid.UUID
    name: str
    phone: str
    email: str | None
    date_of_birth: date | None
    notes: str | None
    total_visits: int
    total_spend: Decimal
    total_play_minutes: int
    last_visit_at: datetime | None
    loyalty_points: int
    referral_code: str | None
    marketing_opt_in: bool
    created_at: datetime


class LedgerEntryOut(ORM):
    id: uuid.UUID
    entry_type: str
    amount: Decimal
    invoice_id: uuid.UUID | None
    note: str | None
    created_at: datetime


class OpeningDueIn(BaseModel):
    branch_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    note: str | None = None


class DuePaymentIn(BaseModel):
    branch_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    method: PaymentMethod
    reference: str | None = None


# ============================================================================ bookings
class AvailabilityOut(BaseModel):
    table: PublicTableOut
    status: str
    quote: QuoteOut | None
    next_available_at: datetime | None
    reason: str | None = None


class HoldIn(BaseModel):
    branch_id: uuid.UUID
    table_id: uuid.UUID
    start_at: datetime
    duration_minutes: int = Field(ge=15, le=720)
    customer: CustomerIn
    coupon_code: str | None = None


class StaffBookingIn(BaseModel):
    branch_id: uuid.UUID
    table_id: uuid.UUID
    start_at: datetime
    duration_minutes: int = Field(ge=15, le=720)
    customer_id: uuid.UUID | None = None
    customer: CustomerIn | None = None
    deposit_method: PaymentMethod | None = None
    deposit_amount: Decimal | None = Field(default=None, ge=0)
    deposit_reference: str | None = None
    source: BookingSource = BookingSource.STAFF
    notes: str | None = None


class BookingOut(ORM):
    id: uuid.UUID
    reference: str
    branch_id: uuid.UUID
    table_id: uuid.UUID
    table: PublicTableOut
    customer_id: uuid.UUID
    customer_name: str | None = None
    customer_phone: str | None = None
    source: str
    status: str
    start_at: datetime
    end_at: datetime
    duration_minutes: int
    hold_expires_at: datetime | None
    booking_amount: Decimal
    deposit_amount: Decimal
    discount: Decimal
    tax: Decimal
    amount_paid: Decimal
    remaining_amount: Decimal
    payment_status: str
    refund_amount: Decimal
    checked_in_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    notes: str | None
    created_at: datetime


class CheckoutOut(BaseModel):
    booking: BookingOut
    payment_id: uuid.UUID | None
    checkout: dict | None


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
    refund_amount: Decimal | None = Field(default=None, ge=0)


class RescheduleIn(BaseModel):
    start_at: datetime
    duration_minutes: int | None = Field(default=None, ge=15, le=720)
    table_id: uuid.UUID | None = None
    reason: str | None = None


class GuestLookupIn(BaseModel):
    reference: str
    phone: str


# ============================================================================ sessions & billing
class SessionStartIn(BaseModel):
    table_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    customer: CustomerIn | None = None
    booking_id: uuid.UUID | None = None
    planned_minutes: int | None = Field(default=None, ge=5, le=720)
    player_count: int = Field(2, ge=1, le=12)
    override_reservation: bool = False


class SessionOut(ORM):
    id: uuid.UUID
    branch_id: uuid.UUID
    table_id: uuid.UUID
    booking_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    membership_id: uuid.UUID | None
    status: str
    billing_status: str
    started_at: datetime | None
    ended_at: datetime | None
    paused_at: datetime | None
    total_paused_seconds: int
    planned_end_at: datetime | None
    duration_seconds: int | None
    detection_method: str
    confidence_score: float | None
    last_activity_at: datetime | None
    player_count: int


class SessionEventOut(ORM):
    event_type: str
    from_status: str | None
    to_status: str | None
    source: str
    payload: dict
    created_at: datetime


class ExtendIn(BaseModel):
    minutes: int = Field(ge=5, le=240)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class AdjustSessionIn(BaseModel):
    started_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=300)


class LiveChargeOut(BaseModel):
    session_id: uuid.UUID
    elapsed_seconds: int
    billed_minutes: int
    covered_minutes: int
    time_amount: Decimal
    member_discount: Decimal
    products_total: Decimal
    product_discount: Decimal
    deposit: Decimal
    estimated_total: Decimal
    segments: list[PriceSegmentOut]
    membership_code: str | None
    membership_minutes_remaining: int | None


class InvoiceLineOut(ORM):
    line_type: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class InvoiceAdjustmentOut(ORM):
    amount: Decimal
    reason: str
    created_at: datetime


class InvoiceOut(ORM):
    id: uuid.UUID
    number: str
    branch_id: uuid.UUID
    status: str
    session_id: uuid.UUID | None
    order_id: uuid.UUID | None
    booking_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    customer_name: str | None
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    deposit_applied: Decimal
    adjustments_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    issued_at: datetime | None
    paid_at: datetime | None
    lines: list[InvoiceLineOut]
    adjustments: list[InvoiceAdjustmentOut]


class StopOut(BaseModel):
    session: SessionOut
    invoice: InvoiceOut


class PaymentSplitIn(BaseModel):
    method: PaymentMethod
    amount: Decimal = Field(gt=0)
    reference: str | None = None
    customer_id: uuid.UUID | None = None


class PayIn(BaseModel):
    splits: list[PaymentSplitIn] = Field(min_length=1, max_length=5)


class DiscountIn(BaseModel):
    amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=3)


class AdjustmentIn(BaseModel):
    amount: Decimal
    reason: str = Field(min_length=3)


class PaymentOut(ORM):
    id: uuid.UUID
    purpose: str
    method: str
    status: str
    amount: Decimal
    reference: str | None
    paid_at: datetime | None
    provider: str | None


class ApprovalOut(ORM):
    id: uuid.UUID
    approval_type: str
    status: str
    amount: Decimal | None
    reason: str
    invoice_id: uuid.UUID | None
    order_item_id: uuid.UUID | None
    requested_by_id: uuid.UUID
    resolved_by_id: uuid.UUID | None
    created_at: datetime
    resolution_note: str | None


class ResolveIn(BaseModel):
    approve: bool
    note: str | None = None


# ============================================================================ POS
class CategoryIn(BaseModel):
    name: str
    sort_order: int = 0


class CategoryOut(ORM):
    id: uuid.UUID
    name: str
    sort_order: int


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str
    category_id: uuid.UUID | None = None
    price: Decimal = Field(ge=0)
    cost_price: Decimal = Field(Decimal("0"), ge=0)
    tax_rate: Decimal = Field(Decimal("0"), ge=0, le=50)
    track_stock: bool = True
    low_stock_threshold: int = Field(5, ge=0)
    is_active: bool = True


class ProductUpdateIn(BaseModel):
    name: str | None = None
    category_id: uuid.UUID | None = None
    price: Decimal | None = Field(None, ge=0)
    cost_price: Decimal | None = Field(None, ge=0)
    track_stock: bool | None = None
    low_stock_threshold: int | None = None
    is_active: bool | None = None


class ProductOut(ORM):
    id: uuid.UUID
    sku: str
    name: str
    category_id: uuid.UUID | None
    price: Decimal
    cost_price: Decimal
    track_stock: bool
    low_stock_threshold: int
    is_active: bool


class ProductStockOut(BaseModel):
    product: ProductOut
    stock: Decimal | None


class OrderItemIn(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(Decimal("1"), gt=0, le=100)


class OrderItemsIn(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1)


class CounterSaleIn(OrderItemsIn):
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None = None


class OrderItemOut(ORM):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    status: str
    created_at: datetime


class OrderOut(ORM):
    id: uuid.UUID
    number: str
    session_id: uuid.UUID | None
    status: str
    subtotal: Decimal
    items: list[OrderItemOut]


class StockInIn(BaseModel):
    branch_id: uuid.UUID
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    txn_type: Literal[InventoryTxnType.OPENING, InventoryTxnType.PURCHASE, InventoryTxnType.RETURN] = InventoryTxnType.PURCHASE
    unit_cost: Decimal | None = Field(None, ge=0)
    supplier_id: uuid.UUID | None = None
    reference: str | None = None
    note: str | None = None


class StockOutIn(BaseModel):
    branch_id: uuid.UUID
    product_id: uuid.UUID
    quantity: Decimal
    txn_type: Literal[InventoryTxnType.DAMAGED, InventoryTxnType.SUPPLIER_RETURN, InventoryTxnType.ADJUSTMENT]
    reason: str = Field(min_length=3)
    supplier_id: uuid.UUID | None = None


class InventoryTxnOut(ORM):
    id: uuid.UUID
    product_id: uuid.UUID
    txn_type: str
    quantity: Decimal
    unit_cost: Decimal | None
    balance_after: Decimal
    reference: str | None
    note: str | None
    created_at: datetime


class SupplierIn(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    gstin: str | None = None
    address: str | None = None


class SupplierOut(ORM, SupplierIn):
    id: uuid.UUID


# ============================================================================ membership & loyalty
class PlanIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    name: str
    tier: str = "SILVER"
    price: Decimal = Field(ge=0)
    validity_days: int = Field(ge=1, le=3650)
    included_minutes: int = Field(0, ge=0)
    deduction_block_minutes: int = Field(30, ge=1, le=120)
    table_discount_percent: Decimal = Field(Decimal("0"), ge=0, le=100)
    product_discount_percent: Decimal = Field(Decimal("0"), ge=0, le=100)
    game_type_ids: list[uuid.UUID] | None = None
    max_minutes_per_day: int | None = Field(None, ge=1)
    benefits: list[str] = []
    is_public: bool = True
    is_active: bool = True


class PlanOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    tier: str
    price: Decimal
    validity_days: int
    included_minutes: int
    deduction_block_minutes: int
    table_discount_percent: Decimal
    product_discount_percent: Decimal
    game_type_ids: list[Any] | None
    max_minutes_per_day: int | None
    benefits: list[str]
    is_public: bool
    is_active: bool


class SellMembershipIn(BaseModel):
    branch_id: uuid.UUID
    customer_id: uuid.UUID
    plan_id: uuid.UUID
    payment_method: PaymentMethod
    amount: Decimal | None = Field(None, ge=0)
    reference: str | None = None
    card_uid: str | None = None


class CustomerMini(ORM):
    id: uuid.UUID
    name: str
    phone: str


class MembershipOut(ORM):
    id: uuid.UUID
    code: str
    customer: CustomerMini | None = None
    card_uid: str | None
    customer_id: uuid.UUID
    plan: PlanOut
    status: str
    starts_on: date
    expires_on: date
    minutes_total: int
    minutes_used: int
    minutes_remaining: int
    price_paid: Decimal


class MembershipTxnOut(ORM):
    txn_type: str
    minutes: int
    amount: Decimal
    session_id: uuid.UUID | None
    note: str | None
    created_at: datetime


class MinutesAdjustIn(BaseModel):
    minutes: int
    reason: str = Field(min_length=3)


class MembershipStatusIn(BaseModel):
    status: Literal[MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED, MembershipStatus.CANCELLED]
    reason: str = Field(min_length=3)


class CardIn(BaseModel):
    card_uid: str = Field(min_length=4, max_length=40)


class RenewIn(BaseModel):
    payment_method: PaymentMethod
    reference: str | None = None


class RedeemIn(BaseModel):
    invoice_id: uuid.UUID
    points: int = Field(gt=0)


class CouponIn(BaseModel):
    code: str
    description: str | None = None
    discount_type: Literal["PERCENT", "FLAT"]
    value: Decimal = Field(gt=0)
    min_amount: Decimal = Decimal("0")
    max_discount: Decimal | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    max_uses: int | None = None


class CouponOut(ORM, CouponIn):
    id: uuid.UUID
    used_count: int
    is_active: bool


# ============================================================================ devices
class DeviceIn(BaseModel):
    device_id: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str
    device_type: DeviceType
    table_id: uuid.UUID | None = None
    firmware_version: str | None = None
    configuration: dict = {}


class DeviceUpdateIn(BaseModel):
    name: str | None = None
    table_id: uuid.UUID | None = None
    status: Literal["ONLINE", "OFFLINE", "ERROR", "MAINTENANCE"] | None = None
    configuration: dict | None = None
    is_enabled: bool | None = None


class DeviceOut(ORM):
    id: uuid.UUID
    device_id: str
    name: str
    device_type: str
    table_id: uuid.UUID | None
    status: str
    last_seen_at: datetime | None
    firmware_version: str | None
    configuration: dict
    is_enabled: bool
    api_key_prefix: str


class DeviceWithKeyOut(BaseModel):
    device: DeviceOut
    api_key: str = Field(description="Shown once. Store it on the device/gateway.")


class DeviceEventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=64, description="Unique per device; used for idempotency")
    event: str = Field(description="e.g. ACTIVITY_DETECTED, CARD_TAP, GAME_ACTIVITY, NO_ACTIVITY, START_REQUEST")
    timestamp: datetime | None = None
    table_id: int | str | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    card_uid: str | None = None
    payload: dict = {}


class DeviceEventBatchIn(BaseModel):
    events: list[DeviceEventIn] = Field(min_length=1, max_length=500)


class HeartbeatIn(BaseModel):
    firmware_version: str | None = None
    uptime_seconds: int | None = None
    queue_depth: int | None = None
    status: Literal["OK", "ERROR"] = "OK"
    error: str | None = None
    meta: dict = {}


class DeviceEventOut(ORM):
    id: uuid.UUID
    event_id: str
    event_type: str
    confidence: float | None
    occurred_at: datetime
    received_at: datetime
    outcome: str | None
    detail: str | None
    table_id: uuid.UUID | None


class QrStartIn(BaseModel):
    name: str | None = None
    phone: str | None = None


class SimulateIn(BaseModel):
    table_id: uuid.UUID
    source: Literal["MOTION", "PRESSURE", "IR", "VIBRATION", "CAMERA", "RFID", "CONTROLLER"]
    confidence: float = Field(1.0, ge=0, le=1)
    card_uid: str | None = None
    seconds_ago: int = Field(0, ge=0, le=3600)


# ============================================================================ ops
class ShiftOpenIn(BaseModel):
    branch_id: uuid.UUID
    opening_cash: Decimal = Field(ge=0)
    notes: str | None = None


class ShiftCloseIn(BaseModel):
    counted_cash: Decimal = Field(ge=0)
    notes: str | None = None


class ShiftOut(ORM):
    id: uuid.UUID
    branch_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    opened_at: datetime
    closed_at: datetime | None
    opening_cash: Decimal
    cash_sales: Decimal
    cash_expenses: Decimal
    expected_cash: Decimal
    counted_cash: Decimal | None
    variance: Decimal | None
    notes: str | None


class ExpenseCategoryOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    color: str


class ExpenseIn(BaseModel):
    category_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    description: str = Field(min_length=1, max_length=200)
    paid_to: str | None = None
    method: Literal["CASH", "UPI", "CARD", "BANK"] = "CASH"
    expense_date: date | None = None


class ExpenseOut(ORM):
    id: uuid.UUID
    category: ExpenseCategoryOut
    amount: Decimal
    description: str
    paid_to: str | None
    method: str
    expense_date: date
    is_void: bool
    void_reason: str | None
    created_at: datetime


class AlertOut(ORM):
    id: uuid.UUID
    alert_type: str
    severity: str
    message: str
    table_id: uuid.UUID | None
    session_id: uuid.UUID | None
    data: dict
    acknowledged_at: datetime | None
    created_at: datetime


class AuditOut(ORM):
    id: uuid.UUID
    username: str | None
    action: str
    entity_type: str
    entity_id: str | None
    before: dict | None
    after: dict | None
    reason: str | None
    ip: str | None
    request_id: str | None
    created_at: datetime


class TournamentIn(BaseModel):
    game_type_id: uuid.UUID
    name: str
    format: TournamentFormat = TournamentFormat.KNOCKOUT
    entry_fee: Decimal = Decimal("0")
    prize_pool: Decimal = Decimal("0")
    max_players: int = Field(32, ge=2, le=256)
    group_count: int = Field(0, ge=0, le=16)
    starts_on: date | None = None
    rules: str | None = None


class TournamentOut(ORM):
    id: uuid.UUID
    name: str
    format: str
    status: str
    entry_fee: Decimal
    prize_pool: Decimal
    max_players: int
    starts_on: date | None
    winner_player_id: uuid.UUID | None
    game_type_id: uuid.UUID


class PlayerIn(BaseModel):
    customer_id: uuid.UUID
    seed: int | None = Field(None, ge=1)
    fee_paid: bool = False


class PlayerOut(ORM):
    id: uuid.UUID
    display_name: str
    seed: int | None
    group_no: int | None
    wins: int
    losses: int
    eliminated: bool
    fee_paid: bool


class MatchOut(ORM):
    id: uuid.UUID
    stage: str
    round_no: int
    match_no: int
    group_no: int | None
    player1_id: uuid.UUID | None
    player2_id: uuid.UUID | None
    score1: int | None
    score2: int | None
    winner_id: uuid.UUID | None
    status: str
    table_id: uuid.UUID | None


class ResultIn(BaseModel):
    score1: int = Field(ge=0, le=99)
    score2: int = Field(ge=0, le=99)
    table_id: uuid.UUID | None = None


class PromoIn(BaseModel):
    subject: str
    message: str = Field(min_length=3, max_length=1000)


class SessionManualStart(BaseModel):
    method: DetectionMethod = DetectionMethod.MANUAL


RoleOut.model_rebuild()


class OutstandingRow(BaseModel):
    customer_id: uuid.UUID
    name: str
    phone: str
    balance: Decimal
    last_activity_at: datetime | str | None = None


class CustomerProfileOut(BaseModel):
    customer: CustomerOut
    total_visits: int
    total_spend: Decimal
    average_session_minutes: float
    favorite_game: str | None
    membership: MembershipOut | None
    last_visit_at: datetime | None
    outstanding: Decimal
    loyalty_points: int
    invoice_count: int
