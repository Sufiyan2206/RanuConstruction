"""Membership plans, selling/renewing memberships, cards (RFID/NFC UID), balance
ledger and expiry processing."""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import for_update
from app.core.deps import Principal
from app.core.errors import Conflict, InvalidState, NotFound, ValidationFailed
from app.core.timeutil import utcnow
from app.models import Membership, MembershipPlan, MembershipTransaction, Payment
from app.models.base import money
from app.models.enums import MembershipStatus, MembershipTxnType, PaymentMethod, PaymentPurpose, PaymentStatus
from app.services import customer_service
from app.services.audit import audit, snapshot
from app.services.common import ensure_branch_access, get_branch, random_code

PLAN_FIELDS = ["code", "name", "tier", "price", "validity_days", "included_minutes", "deduction_block_minutes", "table_discount_percent",
               "product_discount_percent", "game_type_ids", "max_minutes_per_day", "benefits", "is_active", "is_public"]


def upsert_plan(db: Session, actor: Principal, data: dict, plan_id: uuid.UUID | None = None) -> MembershipPlan:
    actor.require("memberships.manage")
    if "game_type_ids" in data and data["game_type_ids"] is not None:
        data["game_type_ids"] = [str(x) for x in data["game_type_ids"]]
    if plan_id:
        p = db.get(MembershipPlan, plan_id)
        if not p or p.organization_id != actor.organization_id:
            raise NotFound("Plan not found")
        before = snapshot(p, PLAN_FIELDS)
        for k, v in data.items():
            if k in PLAN_FIELDS:
                setattr(p, k, v)
        audit(db, actor, "membership_plan.update", "membership_plan", p.id, before=before, after=snapshot(p, PLAN_FIELDS))
    else:
        if db.scalar(select(MembershipPlan.id).where(MembershipPlan.organization_id == actor.organization_id, MembershipPlan.code == data["code"])):
            raise Conflict("Plan code already exists")
        p = MembershipPlan(organization_id=actor.organization_id, **{k: v for k, v in data.items() if k in PLAN_FIELDS})
        db.add(p)
        db.flush()
        audit(db, actor, "membership_plan.create", "membership_plan", p.id, after=snapshot(p, PLAN_FIELDS))
    db.commit()
    return p


def list_plans(db: Session, organization_id: uuid.UUID, public_only: bool = False) -> list[MembershipPlan]:
    stmt = select(MembershipPlan).where(MembershipPlan.organization_id == organization_id, MembershipPlan.is_active.is_(True))
    if public_only:
        stmt = stmt.where(MembershipPlan.is_public.is_(True))
    return list(db.scalars(stmt.order_by(MembershipPlan.price)).all())


def _new_code(db: Session) -> str:
    for _ in range(30):
        code = random_code(5, "M")
        if not db.scalar(select(Membership.id).where(Membership.code == code)):
            return code
    raise Conflict("Could not allocate membership code")


def sell(db: Session, actor: Principal, *, branch_id: uuid.UUID, customer_id: uuid.UUID, plan_id: uuid.UUID, payment_method: PaymentMethod,
         amount: Decimal | None = None, reference: str | None = None, card_uid: str | None = None) -> Membership:
    """Sell a membership at the counter: membership + payment + ledger rows in ONE transaction."""
    branch = get_branch(db, branch_id)
    ensure_branch_access(actor, branch, "memberships.manage")
    cust = customer_service.get_customer(db, actor, customer_id)
    plan = db.get(MembershipPlan, plan_id)
    if not plan or plan.organization_id != actor.organization_id or not plan.is_active:
        raise NotFound("Plan not found")
    if card_uid and db.scalar(select(Membership.id).where(Membership.card_uid == card_uid.upper())):
        raise Conflict("This card is already linked to another membership", code="CARD_IN_USE")
    price = money(amount if amount is not None else plan.price)
    if price != money(plan.price):
        actor.require("billing.discount", branch_id)
    today = utcnow().date()
    m = Membership(organization_id=actor.organization_id, branch_id=branch_id, customer_id=cust.id, plan_id=plan.id, code=_new_code(db),
                   card_uid=card_uid.upper() if card_uid else None, status=MembershipStatus.ACTIVE, starts_on=today,
                   expires_on=today + timedelta(days=plan.validity_days), minutes_total=plan.included_minutes, minutes_used=0, price_paid=price)
    db.add(m)
    db.flush()
    db.add(MembershipTransaction(membership_id=m.id, txn_type=MembershipTxnType.PURCHASE, minutes=plan.included_minutes, amount=price, created_by_id=actor.id, created_at=utcnow()))
    from app.services import shift_service

    p = Payment(branch_id=branch_id, purpose=PaymentPurpose.MEMBERSHIP, method=payment_method, status=PaymentStatus.PAID, amount=price, customer_id=cust.id,
                membership_id=m.id, reference=reference, received_by_id=actor.id, paid_at=utcnow(), shift_id=shift_service.current_shift_id(db, actor))
    db.add(p)
    db.flush()
    if payment_method == PaymentMethod.CREDIT:
        from app.models.enums import LedgerEntryType

        customer_service.add_ledger(db, branch_id=branch_id, customer_id=cust.id, entry_type=LedgerEntryType.CREDIT_SALE, amount=price, actor=actor,
                                    payment_id=p.id, note=f"Membership {m.code}")
    audit(db, actor, "membership.sell", "membership", m.id, branch_id=branch_id, after={"plan": plan.name, "price": price, "code": m.code, "method": payment_method})
    from app.services import notification_service

    notification_service.enqueue(db, event="membership.purchased", customer=cust, branch_id=branch_id,
                                 context={"name": cust.name, "plan": plan.name, "code": m.code, "expires_on": m.expires_on.isoformat()}, dedupe=f"mship:{m.id}")
    db.commit()
    return m


def renew(db: Session, actor: Principal, membership_id: uuid.UUID, payment_method: PaymentMethod, reference: str | None = None) -> Membership:
    m = _get(db, membership_id, lock=True)
    ensure_branch_access(actor, get_branch(db, m.branch_id), "memberships.manage")
    plan = m.plan
    today = utcnow().date()
    base = m.expires_on if m.expires_on >= today and m.status == MembershipStatus.ACTIVE else today
    before = snapshot(m, ["expires_on", "minutes_total", "status"])
    m.expires_on = base + timedelta(days=plan.validity_days)
    m.minutes_total += plan.included_minutes
    m.status = MembershipStatus.ACTIVE
    db.add(MembershipTransaction(membership_id=m.id, txn_type=MembershipTxnType.RENEWAL, minutes=plan.included_minutes, amount=plan.price, created_by_id=actor.id, created_at=utcnow()))
    db.add(Payment(branch_id=m.branch_id, purpose=PaymentPurpose.MEMBERSHIP, method=payment_method, status=PaymentStatus.PAID, amount=money(plan.price),
                   customer_id=m.customer_id, membership_id=m.id, reference=reference, received_by_id=actor.id, paid_at=utcnow()))
    audit(db, actor, "membership.renew", "membership", m.id, branch_id=m.branch_id, before=before, after=snapshot(m, ["expires_on", "minutes_total", "status"]))
    db.commit()
    return m


def adjust_minutes(db: Session, actor: Principal, membership_id: uuid.UUID, minutes: int, reason: str) -> Membership:
    m = _get(db, membership_id, lock=True)
    ensure_branch_access(actor, get_branch(db, m.branch_id), "memberships.manage")
    actor.require("billing.adjust", m.branch_id)
    if not reason:
        raise ValidationFailed("Reason is required")
    if m.minutes_total + minutes < m.minutes_used:
        raise ValidationFailed("Adjustment would make the balance negative")
    before = {"minutes_total": m.minutes_total}
    m.minutes_total += minutes
    db.add(MembershipTransaction(membership_id=m.id, txn_type=MembershipTxnType.ADJUSTMENT, minutes=minutes, note=reason, created_by_id=actor.id, created_at=utcnow()))
    audit(db, actor, "membership.adjust", "membership", m.id, branch_id=m.branch_id, before=before, after={"minutes_total": m.minutes_total}, reason=reason)
    db.commit()
    return m


def set_status(db: Session, actor: Principal, membership_id: uuid.UUID, status: MembershipStatus, reason: str) -> Membership:
    m = _get(db, membership_id, lock=True)
    ensure_branch_access(actor, get_branch(db, m.branch_id), "memberships.manage")
    if m.status == MembershipStatus.CANCELLED:
        raise InvalidState("Membership already cancelled")
    before = m.status
    m.status = status
    if status == MembershipStatus.CANCELLED:
        db.add(MembershipTransaction(membership_id=m.id, txn_type=MembershipTxnType.CANCELLATION, minutes=-m.minutes_remaining, note=reason, created_by_id=actor.id, created_at=utcnow()))
    audit(db, actor, "membership.status", "membership", m.id, branch_id=m.branch_id, before={"status": before}, after={"status": status}, reason=reason)
    db.commit()
    return m


def link_card(db: Session, actor: Principal, membership_id: uuid.UUID, card_uid: str) -> Membership:
    m = _get(db, membership_id, lock=True)
    ensure_branch_access(actor, get_branch(db, m.branch_id), "memberships.manage")
    uid = card_uid.strip().upper()
    other = db.scalar(select(Membership).where(Membership.card_uid == uid, Membership.id != m.id))
    if other:
        raise Conflict("Card already linked to another membership", code="CARD_IN_USE")
    before = m.card_uid
    m.card_uid = uid
    audit(db, actor, "membership.link_card", "membership", m.id, branch_id=m.branch_id, before={"card_uid": before}, after={"card_uid": uid})
    db.commit()
    return m


def find_by_card(db: Session, card_uid: str) -> Membership | None:
    return db.scalar(select(Membership).where(Membership.card_uid == card_uid.strip().upper()))


def activate_after_payment(db: Session, m: Membership) -> None:
    if m and m.status == MembershipStatus.SUSPENDED:
        m.status = MembershipStatus.ACTIVE


def expire_due(db: Session) -> int:
    today = utcnow().date()
    rows = db.scalars(select(Membership).where(Membership.status == MembershipStatus.ACTIVE, Membership.expires_on < today)).unique().all()
    for m in rows:
        m.status = MembershipStatus.EXPIRED
        audit(db, None, "membership.expire", "membership", m.id, branch_id=m.branch_id, after={"status": m.status})
    db.commit()
    return len(rows)


def _get(db: Session, membership_id: uuid.UUID, lock: bool = False) -> Membership:
    stmt = select(Membership).where(Membership.id == membership_id)
    m = db.scalar(for_update(stmt, db) if lock else stmt)
    if not m:
        raise NotFound("Membership not found")
    return m


def statement(db: Session, actor: Principal, membership_id: uuid.UUID) -> dict:
    """Member hours statement (legacy 'Member statement' print)."""
    m = _get(db, membership_id)
    actor.require("customers.view", m.branch_id)
    txns = db.scalars(select(MembershipTransaction).where(MembershipTransaction.membership_id == m.id).order_by(MembershipTransaction.created_at)).all()
    return {"membership": m, "transactions": list(txns)}


def list_memberships(db: Session, actor: Principal, *, customer_id: uuid.UUID | None, status: str | None, expiring_days: int | None) -> list[Membership]:
    stmt = select(Membership).where(Membership.organization_id == actor.organization_id)
    if customer_id:
        stmt = stmt.where(Membership.customer_id == customer_id)
    if status:
        stmt = stmt.where(Membership.status == status)
    if expiring_days:
        today = utcnow().date()
        stmt = stmt.where(Membership.status == MembershipStatus.ACTIVE, Membership.expires_on <= today + timedelta(days=expiring_days))
    return list(db.scalars(stmt.order_by(Membership.expires_on)).unique().all())
