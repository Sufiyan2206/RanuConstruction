"""Domain enumerations. Stored as short strings (portable across PG/MySQL/SQLite)
and guarded by CHECK constraints generated from these classes."""
from __future__ import annotations

from enum import StrEnum


class TableStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"  # customer checked in / ready, clock not running yet
    GAME_STARTED = "GAME_STARTED"
    PAUSED = "PAUSED"
    MAINTENANCE = "MAINTENANCE"
    BLOCKED = "BLOCKED"


class BookingStatus(StrEnum):
    HELD = "HELD"  # temporary hold during checkout
    CONFIRMED = "CONFIRMED"  # deposit paid (or staff-confirmed)
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"  # hold expired before payment
    NO_SHOW = "NO_SHOW"


BLOCKING_BOOKING_STATUSES = (BookingStatus.HELD, BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN, BookingStatus.IN_PROGRESS)


class BookingSource(StrEnum):
    ONLINE = "ONLINE"
    STAFF = "STAFF"
    PHONE = "PHONE"
    TOURNAMENT = "TOURNAMENT"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class PaymentMethod(StrEnum):
    CASH = "CASH"
    UPI = "UPI"
    CARD = "CARD"
    ONLINE = "ONLINE"
    WALLET = "WALLET"
    CREDIT = "CREDIT"  # "Credit (Due)" — adds to the customer's outstanding ledger
    MEMBERSHIP = "MEMBERSHIP"


class PaymentPurpose(StrEnum):
    BOOKING_DEPOSIT = "BOOKING_DEPOSIT"
    INVOICE = "INVOICE"
    MEMBERSHIP = "MEMBERSHIP"
    DUE_SETTLEMENT = "DUE_SETTLEMENT"
    TOURNAMENT_FEE = "TOURNAMENT_FEE"
    REFUND = "REFUND"


class SessionStatus(StrEnum):
    CREATED = "CREATED"  # READY: customer at table, clock not running
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    AUTO_CLOSED = "AUTO_CLOSED"


OPEN_SESSION_STATUSES = (SessionStatus.CREATED, SessionStatus.ACTIVE, SessionStatus.PAUSED)


class BillingStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    INVOICED = "INVOICED"


class DetectionMethod(StrEnum):
    MANUAL = "MANUAL"
    QR = "QR"
    RFID = "RFID"
    NFC = "NFC"
    SENSOR = "SENSOR"
    CAMERA = "CAMERA"
    HYBRID = "HYBRID"
    BOOKING = "BOOKING"


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceLineType(StrEnum):
    TABLE_TIME = "TABLE_TIME"
    MEMBERSHIP_COVERED = "MEMBERSHIP_COVERED"
    PRODUCT = "PRODUCT"
    DISCOUNT = "DISCOUNT"
    TAX = "TAX"
    DEPOSIT_CREDIT = "DEPOSIT_CREDIT"
    FEE = "FEE"
    ADJUSTMENT = "ADJUSTMENT"


class DeviceType(StrEnum):
    RFID_READER = "RFID_READER"
    NFC_READER = "NFC_READER"
    QR_CODE = "QR_CODE"
    MOTION_SENSOR = "MOTION_SENSOR"
    PRESSURE_SENSOR = "PRESSURE_SENSOR"
    IR_SENSOR = "IR_SENSOR"
    VIBRATION_SENSOR = "VIBRATION_SENSOR"
    CAMERA = "CAMERA"
    TABLE_CONTROLLER = "TABLE_CONTROLLER"
    CUSTOM = "CUSTOM"


class DeviceStatus(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    MAINTENANCE = "MAINTENANCE"


class DetectionState(StrEnum):
    IDLE = "IDLE"
    ACTIVITY_DETECTED = "ACTIVITY_DETECTED"
    CONFIRMING = "CONFIRMING"
    GAME_STARTED = "GAME_STARTED"


class InventoryTxnType(StrEnum):
    OPENING = "OPENING"
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    RETURN = "RETURN"  # customer return -> stock back
    SUPPLIER_RETURN = "SUPPLIER_RETURN"
    DAMAGED = "DAMAGED"
    ADJUSTMENT = "ADJUSTMENT"
    SALE_REVERSAL = "SALE_REVERSAL"


class OrderStatus(StrEnum):
    OPEN = "OPEN"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class MembershipTxnType(StrEnum):
    PURCHASE = "PURCHASE"
    RENEWAL = "RENEWAL"
    USAGE = "USAGE"
    USAGE_REVERSAL = "USAGE_REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"
    CANCELLATION = "CANCELLATION"


class LedgerEntryType(StrEnum):
    OPENING = "OPENING"
    CREDIT_SALE = "CREDIT_SALE"  # customer owes more
    PAYMENT = "PAYMENT"  # customer paid off dues
    ADJUSTMENT = "ADJUSTMENT"
    WALLET_TOPUP = "WALLET_TOPUP"


class ApprovalType(StrEnum):
    DISCOUNT = "DISCOUNT"
    CANCEL_ITEM = "CANCEL_ITEM"
    INVOICE_ADJUSTMENT = "INVOICE_ADJUSTMENT"
    SESSION_ADJUSTMENT = "SESSION_ADJUSTMENT"
    REFUND = "REFUND"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class TournamentFormat(StrEnum):
    KNOCKOUT = "KNOCKOUT"
    ROUND_ROBIN = "ROUND_ROBIN"
    GROUPS_KNOCKOUT = "GROUPS_KNOCKOUT"


class TournamentStatus(StrEnum):
    DRAFT = "DRAFT"
    REGISTRATION = "REGISTRATION"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MatchStatus(StrEnum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    WALKOVER = "WALKOVER"


class NotificationChannel(StrEnum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"
    PUSH = "PUSH"


class NotificationStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ShiftStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


def check_in(column: str, enum_cls) -> str:
    values = ", ".join(f"'{v.value}'" for v in enum_cls)
    return f"{column} IN ({values})"
