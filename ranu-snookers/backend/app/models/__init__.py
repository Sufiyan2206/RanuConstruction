"""Import every model so Base.metadata is complete (Alembic autogenerate, tests)."""
from app.models.auth import Permission, RefreshToken, Role, RolePermission, User, UserRole  # noqa: F401
from app.models.billing import Invoice, InvoiceAdjustment, InvoiceLine  # noqa: F401
from app.models.booking import Booking, BookingHold  # noqa: F401
from app.models.customer import Customer, CustomerLedgerEntry  # noqa: F401
from app.models.device import Device, DeviceEvent, DeviceHeartbeat  # noqa: F401
from app.models.membership import Coupon, LoyaltyTransaction, Membership, MembershipPlan, MembershipTransaction  # noqa: F401
from app.models.ops import (  # noqa: F401
    Alert,
    ApprovalRequest,
    AuditLog,
    Expense,
    ExpenseCategory,
    Notification,
    NotificationTemplate,
    Shift,
    Tournament,
    TournamentMatch,
    TournamentPlayer,
)
from app.models.org import Branch, Club, DocumentSequence, Holiday, Organization, SystemSetting  # noqa: F401
from app.models.payment import IdempotencyRecord, Payment, PaymentWebhookEvent  # noqa: F401
from app.models.pos import InventoryTransaction, Order, OrderItem, Product, ProductCategory, StockLevel, Supplier  # noqa: F401
from app.models.session import GameSession, SessionEvent, SessionPause  # noqa: F401
from app.models.table import GameType, PricingRule, Table, TableDetectionState  # noqa: F401
