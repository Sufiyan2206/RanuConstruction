"""Permission catalogue and DEFAULT role templates.

Business code only ever checks *permissions* (e.g. ``sessions.operate``), never
role names. Roles and their permission sets live in the database and are
seeded from ``DEFAULT_ROLES`` below; a Super Admin can edit them at runtime.
"""
from __future__ import annotations

PERMISSIONS: dict[str, str] = {
    "org.manage": "Manage organisation, clubs and branches",
    "users.manage": "Create users and assign roles",
    "roles.manage": "Edit roles and permissions",
    "settings.manage": "Change branch settings (billing, booking policy, detection)",
    "pricing.manage": "Change table rates and pricing rules",
    "tables.view": "View tables and live status",
    "tables.manage": "Create/edit tables, set maintenance/blocked",
    "bookings.view": "View bookings",
    "bookings.manage": "Create, check-in, cancel, reschedule bookings",
    "sessions.view": "View game sessions",
    "sessions.operate": "Start / pause / resume / stop sessions",
    "sessions.adjust": "Adjust session times after the fact",
    "billing.operate": "Generate bills and take payments",
    "billing.discount": "Apply discounts without approval",
    "billing.adjust": "Create invoice adjustments (credit/debit notes)",
    "payments.refund": "Issue refunds",
    "customers.view": "View customers",
    "customers.manage": "Create/edit customers, dues ledger",
    "memberships.manage": "Sell and manage memberships and plans",
    "pos.sell": "Add products to tables and make counter sales",
    "products.manage": "Manage products, categories, suppliers",
    "inventory.manage": "Receive stock and adjust inventory",
    "devices.view": "View devices and health",
    "devices.manage": "Register/configure devices",
    "reports.view": "View reports and analytics",
    "audit.view": "View audit logs",
    "approvals.resolve": "Approve / reject staff requests",
    "alerts.manage": "Acknowledge alerts",
    "expenses.manage": "Record expenses",
    "shifts.operate": "Open / close own cash shift",
    "shifts.view_all": "View every staff member's shifts",
    "tournaments.manage": "Manage tournaments",
    "notifications.manage": "Manage notification templates",
    # customer self-service
    "self.bookings": "Customer: book, view and cancel own bookings",
}

_ALL = list(PERMISSIONS)
_STAFF_BASE = ["tables.view", "sessions.view", "sessions.operate", "pos.sell", "bookings.view", "customers.view", "devices.view", "shifts.operate"]

DEFAULT_ROLES: dict[str, dict] = {
    "SUPER_ADMIN": {"name": "Super Admin", "permissions": _ALL},
    "CLUB_ADMIN": {
        "name": "Club Admin",
        "permissions": [p for p in _ALL if p not in ("org.manage", "roles.manage", "self.bookings")],
    },
    "MANAGER": {
        "name": "Manager",
        "permissions": _STAFF_BASE
        + [
            "bookings.manage", "billing.operate", "billing.discount", "billing.adjust", "customers.manage",
            "memberships.manage", "reports.view", "approvals.resolve", "alerts.manage", "expenses.manage",
            "inventory.manage", "shifts.view_all", "sessions.adjust", "tables.manage", "tournaments.manage", "audit.view",
        ],
    },
    "RECEPTIONIST": {
        "name": "Receptionist",
        "permissions": _STAFF_BASE + ["bookings.manage", "billing.operate", "customers.manage", "memberships.manage", "expenses.manage"],
    },
    "STAFF": {"name": "Staff", "permissions": _STAFF_BASE},
    "CUSTOMER": {"name": "Customer", "permissions": ["self.bookings"]},
}
