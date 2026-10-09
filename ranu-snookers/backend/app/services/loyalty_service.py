"""Loyalty points, referrals and coupons — all rules come from branch settings / DB."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import for_update
from app.core.deps import Principal
from app.core.errors import NotFound, ValidationFailed
from app.core.timeutil import utcnow
from app.models import Branch, Coupon, Customer, Invoice, LoyaltyTransaction
from app.models.base import money
from app.services.audit import audit
from app.services.common import branch_settings


def earn_for_invoice(db: Session, inv: Invoice) -> int:
    cfg = branch_settings(db.get(Branch, inv.branch_id)).loyalty
    if not cfg.enabled or not inv.customer_id:
        return 0
    if db.scalar(select(LoyaltyTransaction.id).where(LoyaltyTransaction.invoice_id == inv.id, LoyaltyTransaction.reason == "EARN")):
        return 0  # idempotent
    points = int((money(inv.total) / Decimal(str(cfg.spend_per_point))).to_integral_value(rounding=ROUND_FLOOR))
    if points <= 0:
        return 0
    c = db.scalar(for_update(select(Customer).where(Customer.id == inv.customer_id), db))
    c.loyalty_points += points
    db.add(LoyaltyTransaction(customer_id=c.id, branch_id=inv.branch_id, points=points, reason="EARN", invoice_id=inv.id, created_at=utcnow()))
    return points


def award_referral(db: Session, referrer: Customer, new_customer: Customer, branch_id: uuid.UUID | None) -> None:
    if branch_id is None:
        branch = db.scalar(select(Branch).where(Branch.organization_id == referrer.organization_id))
        branch_id = branch.id if branch else None
    if branch_id is None:
        return
    cfg = branch_settings(db.get(Branch, branch_id)).loyalty
    if not cfg.enabled or cfg.referral_bonus_points <= 0:
        return
    referrer.loyalty_points += cfg.referral_bonus_points
    db.add(LoyaltyTransaction(customer_id=referrer.id, branch_id=branch_id, points=cfg.referral_bonus_points, reason="REFERRAL", created_at=utcnow()))


def redeem(db: Session, actor: Principal, customer_id: uuid.UUID, invoice_id: uuid.UUID, points: int) -> Invoice:
    """Redeem points as a discount (credit note) on an open invoice."""
    from app.services import billing_service

    inv = billing_service.get_invoice(db, invoice_id, lock=True)
    actor.require("billing.operate", inv.branch_id)
    cfg = branch_settings(db.get(Branch, inv.branch_id)).loyalty
    c = db.scalar(for_update(select(Customer).where(Customer.id == customer_id), db))
    if not c or inv.customer_id != c.id:
        raise ValidationFailed("Invoice belongs to another customer")
    if points < cfg.min_redeem_points or points > c.loyalty_points:
        raise ValidationFailed(f"Redeem between {cfg.min_redeem_points} and {c.loyalty_points} points")
    value = money(Decimal(points) * Decimal(str(cfg.point_value)))
    value = min(value, money(inv.balance_due))
    c.loyalty_points -= points
    db.add(LoyaltyTransaction(customer_id=c.id, branch_id=inv.branch_id, points=-points, reason="REDEEM", invoice_id=inv.id, created_at=utcnow()))
    billing_service._add_adjustment(db, actor, inv, -value, f"Loyalty redemption ({points} pts)", approved_by=actor.id)
    db.commit()
    return inv


def coupon_discount(db: Session, organization_id: uuid.UUID, code: str, amount: Decimal, *, on: date) -> Decimal:
    c = db.scalar(select(Coupon).where(Coupon.organization_id == organization_id, Coupon.code == code.strip().upper(), Coupon.is_active.is_(True)))
    if not c:
        raise NotFound("Coupon not found or inactive", code="COUPON_INVALID")
    if (c.valid_from and on < c.valid_from) or (c.valid_to and on > c.valid_to):
        raise ValidationFailed("Coupon not valid for this date", code="COUPON_INVALID")
    if c.max_uses is not None and c.used_count >= c.max_uses:
        raise ValidationFailed("Coupon fully redeemed", code="COUPON_INVALID")
    if amount < money(c.min_amount):
        raise ValidationFailed(f"Minimum amount for this coupon is {c.min_amount}", code="COUPON_INVALID")
    d = money(amount * Decimal(str(c.value)) / 100) if c.discount_type == "PERCENT" else money(c.value)
    if c.max_discount is not None:
        d = min(d, money(c.max_discount))
    c.used_count += 1
    return min(d, amount)


def create_coupon(db: Session, actor: Principal, data: dict) -> Coupon:
    actor.require("pricing.manage")
    c = Coupon(organization_id=actor.organization_id, **{**data, "code": data["code"].strip().upper()})
    db.add(c)
    db.flush()
    audit(db, actor, "coupon.create", "coupon", c.id, after=data)
    db.commit()
    return c


def history(db: Session, customer_id: uuid.UUID) -> list[LoyaltyTransaction]:
    return list(db.scalars(select(LoyaltyTransaction).where(LoyaltyTransaction.customer_id == customer_id).order_by(LoyaltyTransaction.created_at.desc())).all())
