"""Seed data.

`seed_reference` (permissions + default roles) is idempotent and runs on every
deploy. `seed_demo` creates a ready-to-use RANU Snookers club for development /
demo, based on the legacy RS Sales & Expense app configuration (10 tables,
4 PS5 consoles, ₹150/h with ₹100/h happy hour 14:00–18:00, 15-minute billing
blocks, 30h/50h membership packs, expense categories...).

    python -m app.seed            # reference data only
    python -m app.seed --demo     # + demo club, users, tables, products, devices
"""
from __future__ import annotations

import secrets
import sys
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.permissions import DEFAULT_ROLES, PERMISSIONS
from app.core.security import hash_password, sha256_hex
from app.models import (
    Branch,
    Club,
    Customer,
    Device,
    ExpenseCategory,
    GameType,
    InventoryTransaction,
    MembershipPlan,
    Organization,
    Permission,
    PricingRule,
    Product,
    ProductCategory,
    Role,
    RolePermission,
    StockLevel,
    Table,
    User,
    UserRole,
)
from app.schemas.settings import BranchSettings

DEMO_PASSWORD = "Ranu@12345"


def seed_reference(db: Session, org: Organization) -> None:
    perms = {p.code: p for p in db.scalars(select(Permission)).all()}
    for code, desc in PERMISSIONS.items():
        if code not in perms:
            perms[code] = Permission(code=code, description=desc)
            db.add(perms[code])
    db.flush()
    for code, spec in DEFAULT_ROLES.items():
        role = db.scalar(select(Role).where(Role.organization_id == org.id, Role.code == code))
        if role is None:
            role = Role(organization_id=org.id, code=code, name=spec["name"], is_system=True)
            db.add(role)
            db.flush()
            for pc in spec["permissions"]:
                db.add(RolePermission(role_id=role.id, permission_id=perms[pc].id))
        elif code == "SUPER_ADMIN":  # super admin always gets new permissions
            have = {p.code for p in role.permissions}
            for pc in PERMISSIONS:
                if pc not in have:
                    db.add(RolePermission(role_id=role.id, permission_id=perms[pc].id))
    db.flush()


def ensure_org(db: Session) -> Organization:
    org = db.scalar(select(Organization).order_by(Organization.created_at))
    if org is None:
        org = Organization(name="RANU Snookers", slug="ranu")
        db.add(org)
        db.flush()
    return org


def seed_demo(db: Session, org: Organization) -> dict:
    if db.scalar(select(Branch.id).where(Branch.organization_id == org.id)):
        return {"skipped": "demo data already present"}
    club = Club(organization_id=org.id, name="RANU Snookers", brand_color="#146c3a")
    db.add(club)
    db.flush()
    settings = BranchSettings().model_dump(mode="json")
    branch = Branch(organization_id=org.id, club_id=club.id, code="MAIN", name="RANU Snookers – Main", address="Main Road, Hyderabad",
                    phone="+91 90000 00000", timezone="Asia/Kolkata", opening_time="10:00", closing_time="02:00", settings=settings)
    db.add(branch)
    db.flush()

    roles = {r.code: r for r in db.scalars(select(Role).where(Role.organization_id == org.id)).all()}
    users = [
        ("superadmin", "Super Admin", "SUPER_ADMIN", None, None),
        ("admin", "Club Admin", "CLUB_ADMIN", branch.id, "7860"),
        ("manager", "Floor Manager", "MANAGER", branch.id, "4321"),
        ("reception", "Reception Desk", "RECEPTIONIST", branch.id, "1234"),
        ("staff1", "Staff 1", "STAFF", branch.id, "1111"),
    ]
    for username, name, role, bid, pin in users:
        u = User(organization_id=org.id, username=username, full_name=name, email=f"{username}@ranu.local",
                 password_hash=hash_password(DEMO_PASSWORD), pin_hash=hash_password(pin) if pin else None)
        db.add(u)
        db.flush()
        db.add(UserRole(user_id=u.id, role_id=roles[role].id, branch_id=bid))

    gts = {}
    for code, name, rate, color in [("SNOOKER", "Snooker", 150, "#146c3a"), ("POOL", "Pool", 150, "#1d4ed8"), ("BILLIARDS", "Billiards", 150, "#7c2d12"), ("PS5", "PS5", 100, "#6d28d9")]:
        gts[code] = GameType(organization_id=org.id, code=code, name=name, default_hourly_rate=Decimal(rate), color=color)
        db.add(gts[code])
    db.flush()
    layout = [("SNOOKER", 1, 6), ("POOL", 7, 9), ("BILLIARDS", 10, 10)]
    for code, a, b in layout:
        for n in range(a, b + 1):
            db.add(Table(branch_id=branch.id, table_number=n, name=f"Table {n}", game_type_id=gts[code].id, hourly_rate=Decimal(150),
                         off_peak_rate=Decimal(100), peak_rate=Decimal(180), minimum_booking_duration=30, maximum_booking_duration=240,
                         qr_token=secrets.token_urlsafe(12), sort_order=n))
    for i in range(1, 5):
        db.add(Table(branch_id=branch.id, table_number=100 + i, name=f"PS5 #{i}", game_type_id=gts["PS5"].id, hourly_rate=Decimal(100),
                     off_peak_rate=Decimal(70), minimum_booking_duration=30, maximum_booking_duration=240, qr_token=secrets.token_urlsafe(12), sort_order=100 + i))
    db.flush()

    db.add_all([
        PricingRule(branch_id=branch.id, name="Happy Hour", kind="HAPPY_HOUR", day_type="ANY", start_time="14:00", end_time="18:00", rate_multiplier=0.667, priority=200),
        PricingRule(branch_id=branch.id, name="Weekend Evening Peak", kind="PEAK", day_type="WEEKEND", start_time="18:00", end_time="23:00", rate_multiplier=1.2, priority=150),
        PricingRule(branch_id=branch.id, name="Holiday Pricing", kind="HOLIDAY", day_type="HOLIDAY", rate_multiplier=1.2, priority=160),
    ])

    db.add_all([
        MembershipPlan(organization_id=org.id, code="H30", name="30 Hours Pack", tier="SILVER", price=Decimal(3000), validity_days=30, included_minutes=30 * 60,
                       deduction_block_minutes=30, benefits=["30 hours of table time", "Valid 30 days", "Priority booking"]),
        MembershipPlan(organization_id=org.id, code="H50", name="50 Hours Pack", tier="GOLD", price=Decimal(5000), validity_days=60, included_minutes=50 * 60,
                       deduction_block_minutes=30, product_discount_percent=Decimal(5), benefits=["50 hours of table time", "Valid 60 days", "5% off food & drinks"]),
        MembershipPlan(organization_id=org.id, code="PREMIUM", name="Premium Monthly", tier="PREMIUM", price=Decimal(1500), validity_days=30, included_minutes=0,
                       table_discount_percent=Decimal(20), product_discount_percent=Decimal(10), benefits=["20% off all table time", "10% off food & drinks", "Free RFID card"]),
    ])

    cats = {}
    for i, name in enumerate(["Soft Drinks", "Water", "Snacks", "Food", "Accessories"]):
        cats[name] = ProductCategory(organization_id=org.id, name=name, sort_order=i)
        db.add(cats[name])
    db.flush()
    products = [("COKE", "Coke 300ml", "Soft Drinks", 60, 35), ("SPRITE", "Sprite 300ml", "Soft Drinks", 60, 35), ("WATER1L", "Water 1L", "Water", 30, 12),
                ("CHIPS", "Chips", "Snacks", 40, 20), ("SAMOSA", "Samosa (2 pcs)", "Food", 50, 18), ("TEA", "Tea", "Food", 20, 6),
                ("CHALK", "Cue Chalk", "Accessories", 50, 20), ("GLOVE", "Snooker Glove", "Accessories", 250, 120)]
    for sku, name, cat, price, cost in products:
        p = Product(organization_id=org.id, sku=sku, name=name, category_id=cats[cat].id, price=Decimal(price), cost_price=Decimal(cost),
                    track_stock=sku != "TEA", low_stock_threshold=5)
        db.add(p)
        db.flush()
        if p.track_stock:
            db.add(StockLevel(branch_id=branch.id, product_id=p.id, quantity=Decimal(48)))
            db.add(InventoryTransaction(branch_id=branch.id, product_id=p.id, txn_type="OPENING", quantity=Decimal(48), unit_cost=Decimal(cost),
                                        balance_after=Decimal(48), note="Opening stock (seed)"))

    for code, name, color in [("GROCERY", "Grocery", "#c2410c"), ("GENERAL", "General", "#0369a1"), ("POLICE", "Police", "#4338ca"),
                              ("SALARY", "Salary", "#0f766e"), ("CHARITY", "Charity", "#a21caf"), ("MAINTENANCE", "Maintenance", "#475569")]:
        db.add(ExpenseCategory(organization_id=org.id, code=code, name=name, color=color))

    db.add(Customer(organization_id=org.id, name="Demo Customer", phone="919876543210", email="demo@ranu.local", referral_code="RDEMO01", home_branch_id=branch.id))

    device_keys = {}
    t4 = db.scalar(select(Table).where(Table.branch_id == branch.id, Table.table_number == 4))
    t1 = db.scalar(select(Table).where(Table.branch_id == branch.id, Table.table_number == 1))
    for dev_id, name, dtype, table in [("TABLE4_SENSOR", "Table 4 Motion Sensor", "MOTION_SENSOR", t4), ("TABLE4_RFID", "Table 4 RFID Reader", "RFID_READER", t4),
                                       ("TABLE1_CAMERA", "Table 1 Camera (edge CV)", "CAMERA", t1)]:
        key = f"rdk_demo_{dev_id.lower()}_{secrets.token_hex(6)}"
        device_keys[dev_id] = key
        db.add(Device(branch_id=branch.id, table_id=table.id, device_id=dev_id, name=name, device_type=dtype, api_key_hash=sha256_hex(key), api_key_prefix=key[:8]))
    db.flush()
    return {"branch_id": str(branch.id), "password": DEMO_PASSWORD, "device_keys": device_keys}


def run(demo: bool) -> dict:
    with SessionLocal() as db:
        org = ensure_org(db)
        seed_reference(db, org)
        out = seed_demo(db, org) if demo else {}
        db.commit()
        return out


if __name__ == "__main__":  # pragma: no cover
    result = run("--demo" in sys.argv)
    print(result)
