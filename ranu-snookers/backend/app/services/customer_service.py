"""Customers / CRM and the customer dues ledger (legacy "Credit (Due)")."""
from __future__ import annotations

import re
import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import PageParams, Principal
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.timeutil import utcnow
from app.models import Customer, CustomerLedgerEntry, GameSession, GameType, Invoice, Membership, Table
from app.models.base import money
from app.models.enums import LedgerEntryType, MembershipStatus, SessionStatus
from app.services.audit import audit, snapshot
from app.services.common import random_code

CUSTOMER_FIELDS = ["name", "phone", "email", "date_of_birth", "preferred_game_type_id", "notes", "marketing_opt_in"]


def normalize_phone(raw: str) -> str:
    """Digits only; Indian 10-digit numbers are prefixed with 91 (WhatsApp-ready)."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) < 10 or len(digits) > 15:
        raise ValidationFailed("Enter a valid phone number", code="INVALID_PHONE")
    return digits


def new_referral_code(db: Session) -> str:
    for _ in range(10):
        code = random_code(6, "R")
        if not db.scalar(select(Customer.id).where(Customer.referral_code == code)):
            return code
    return random_code(8, "R")


def get_customer(db: Session, actor: Principal, customer_id: uuid.UUID) -> Customer:
    c = db.get(Customer, customer_id)
    if not c or c.organization_id != actor.organization_id or c.deleted_at is not None:
        raise NotFound("Customer not found")
    return c


def find_or_create(db: Session, organization_id: uuid.UUID, *, name: str, phone: str, email: str | None = None, branch_id: uuid.UUID | None = None) -> Customer:
    """Used by public booking and walk-ins: the phone number is the identity."""
    phone_n = normalize_phone(phone)
    c = db.scalar(select(Customer).where(Customer.organization_id == organization_id, Customer.phone == phone_n))
    if c:
        if c.deleted_at is not None:
            c.deleted_at = None
        if email and not c.email:
            c.email = email
        return c
    c = Customer(organization_id=organization_id, name=name.strip(), phone=phone_n, email=email, home_branch_id=branch_id, referral_code=new_referral_code(db))
    db.add(c)
    db.flush()
    return c


def create(db: Session, actor: Principal, data: dict) -> Customer:
    actor.require("customers.manage")
    phone = normalize_phone(data["phone"])
    if db.scalar(select(Customer.id).where(Customer.organization_id == actor.organization_id, Customer.phone == phone, Customer.deleted_at.is_(None))):
        raise Conflict("A customer with this phone already exists", code="CUSTOMER_EXISTS")
    referred_by = None
    if data.get("referral_code_used"):
        referred_by = db.scalar(select(Customer).where(Customer.referral_code == data["referral_code_used"].upper()))
    c = Customer(
        organization_id=actor.organization_id, name=data["name"].strip(), phone=phone, email=data.get("email"),
        date_of_birth=data.get("date_of_birth"), preferred_game_type_id=data.get("preferred_game_type_id"), notes=data.get("notes"),
        home_branch_id=data.get("home_branch_id"), marketing_opt_in=bool(data.get("marketing_opt_in")),
        referral_code=new_referral_code(db), referred_by_id=referred_by.id if referred_by else None,
    )
    db.add(c)
    db.flush()
    if referred_by is not None:
        from app.services import loyalty_service

        loyalty_service.award_referral(db, referred_by, c, branch_id=data.get("home_branch_id"))
    audit(db, actor, "customer.create", "customer", c.id, after=snapshot(c, CUSTOMER_FIELDS))
    db.commit()
    return c


def update(db: Session, actor: Principal, customer_id: uuid.UUID, data: dict) -> Customer:
    actor.require("customers.manage")
    c = get_customer(db, actor, customer_id)
    before = snapshot(c, CUSTOMER_FIELDS)
    for k, v in data.items():
        if k == "phone" and v:
            v = normalize_phone(v)
        if k in CUSTOMER_FIELDS:
            setattr(c, k, v)
    audit(db, actor, "customer.update", "customer", c.id, before=before, after=snapshot(c, CUSTOMER_FIELDS))
    db.commit()
    return c


def search(db: Session, actor: Principal, q: str | None, page: PageParams) -> tuple[list[Customer], int]:
    stmt = select(Customer).where(Customer.organization_id == actor.organization_id, Customer.deleted_at.is_(None))
    if q:
        like = f"%{q.strip().lower()}%"
        digits = re.sub(r"\D", "", q)
        conds = [func.lower(Customer.name).like(like), func.lower(Customer.email).like(like)]
        if digits:
            conds.append(Customer.phone.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Customer.name).offset(page.offset).limit(page.size)).all()
    return list(rows), total


def outstanding(db: Session, customer_id: uuid.UUID) -> Decimal:
    return money(db.scalar(select(func.coalesce(func.sum(CustomerLedgerEntry.amount), 0)).where(CustomerLedgerEntry.customer_id == customer_id)))


def add_ledger(db: Session, *, branch_id, customer_id, entry_type: LedgerEntryType, amount: Decimal, actor: Principal | None = None,
               invoice_id=None, payment_id=None, note: str | None = None) -> CustomerLedgerEntry:
    e = CustomerLedgerEntry(
        branch_id=branch_id, customer_id=customer_id, entry_type=entry_type, amount=money(amount), invoice_id=invoice_id,
        payment_id=payment_id, note=note, created_by_id=actor.id if actor else None, created_at=utcnow(),
    )
    db.add(e)
    return e


def add_opening_due(db: Session, actor: Principal, customer_id: uuid.UUID, branch_id: uuid.UUID, amount: Decimal, note: str | None) -> CustomerLedgerEntry:
    actor.require("customers.manage", branch_id)
    get_customer(db, actor, customer_id)
    if amount <= 0:
        raise ValidationFailed("Amount must be positive")
    e = add_ledger(db, branch_id=branch_id, customer_id=customer_id, entry_type=LedgerEntryType.OPENING, amount=amount, actor=actor, note=note)
    audit(db, actor, "customer.opening_due", "customer", customer_id, branch_id=branch_id, after={"amount": amount, "note": note})
    db.commit()
    return e


def ledger(db: Session, actor: Principal, customer_id: uuid.UUID) -> list[CustomerLedgerEntry]:
    get_customer(db, actor, customer_id)
    return list(db.scalars(select(CustomerLedgerEntry).where(CustomerLedgerEntry.customer_id == customer_id).order_by(CustomerLedgerEntry.created_at)).all())


def outstanding_report(db: Session, actor: Principal, branch_id: uuid.UUID | None) -> list[dict]:
    stmt = (
        select(Customer.id, Customer.name, Customer.phone, func.sum(CustomerLedgerEntry.amount).label("balance"), func.max(CustomerLedgerEntry.created_at))
        .join(CustomerLedgerEntry, CustomerLedgerEntry.customer_id == Customer.id)
        .where(Customer.organization_id == actor.organization_id)
        .group_by(Customer.id, Customer.name, Customer.phone)
    )
    if branch_id:
        stmt = stmt.where(CustomerLedgerEntry.branch_id == branch_id)
    out = []
    for cid, name, phone, balance, last in db.execute(stmt).all():
        if balance and money(balance) > 0:
            out.append({"customer_id": cid, "name": name, "phone": phone, "balance": money(balance), "last_activity_at": last})
    return sorted(out, key=lambda r: r["balance"], reverse=True)


def profile(db: Session, actor: Principal, customer_id: uuid.UUID) -> dict:
    """CRM dashboard numbers for one customer."""
    c = get_customer(db, actor, customer_id)
    sessions = db.execute(
        select(GameSession.duration_seconds, GameType.name)
        .join(Table, Table.id == GameSession.table_id)
        .join(GameType, GameType.id == Table.game_type_id)
        .where(GameSession.customer_id == c.id, GameSession.status.in_([SessionStatus.COMPLETED, SessionStatus.AUTO_CLOSED]))
    ).all()
    fav: dict[str, int] = {}
    total_secs = 0
    for secs, gname in sessions:
        fav[gname] = fav.get(gname, 0) + 1
        total_secs += secs or 0
    membership = db.scalar(
        select(Membership).where(Membership.customer_id == c.id, Membership.status == MembershipStatus.ACTIVE).order_by(Membership.expires_on.desc())
    )
    invoices = db.scalar(select(func.count(Invoice.id)).where(Invoice.customer_id == c.id)) or 0
    return {
        "customer": c,
        "total_visits": c.total_visits,
        "total_spend": c.total_spend,
        "average_session_minutes": round(total_secs / 60 / len(sessions), 1) if sessions else 0,
        "favorite_game": max(fav, key=fav.get) if fav else None,
        "membership": membership,
        "last_visit_at": c.last_visit_at,
        "outstanding": outstanding(db, c.id),
        "loyalty_points": c.loyalty_points,
        "invoice_count": invoices,
    }


def record_visit(db: Session, customer_id: uuid.UUID | None, *, spend: Decimal, play_seconds: int) -> None:
    if not customer_id:
        return
    c = db.get(Customer, customer_id)
    if not c:
        return
    c.total_visits += 1
    c.total_spend = money(c.total_spend) + money(spend)
    c.total_play_minutes += int(play_seconds // 60)
    c.last_visit_at = utcnow()

