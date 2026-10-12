from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow
from app.models.base import Money, TimestampMixin, UTCDateTime, pk
from app.models.enums import MembershipStatus, MembershipTxnType, check_in


class MembershipPlan(Base, TimestampMixin):
    """E.g. Silver / Gold / Premium, or legacy "30 Hours ₹3000 / 30 days".

    A plan can grant any combination of:
      * prepaid play minutes (included_minutes) deducted in blocks,
      * a percentage discount on paid table time and/or products,
      * member-segment pricing rules (PricingRule.customer_segment = MEMBER).
    """

    __tablename__ = "membership_plans"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), default="SILVER", nullable=False)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False)
    included_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deduction_block_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    table_discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    product_discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    game_type_ids: Mapped[list | None] = mapped_column(JSON)  # NULL = all game types
    max_minutes_per_day: Mapped[int | None] = mapped_column(Integer)
    benefits: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # display bullets
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint(check_in("status", MembershipStatus), name="status"),
        CheckConstraint("minutes_used >= 0", name="minutes_used"),
    )
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)  # selling branch
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("membership_plans.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)  # printed on card, e.g. M7K2QX
    card_uid: Mapped[str | None] = mapped_column(String(40), unique=True)  # RFID/NFC chip UID
    status: Mapped[str] = mapped_column(String(12), default=MembershipStatus.ACTIVE, nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    minutes_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    minutes_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_paid: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    expiry_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    plan = relationship("MembershipPlan", lazy="joined")
    customer = relationship("Customer", lazy="joined")

    @property
    def minutes_remaining(self) -> int:
        return max(0, (self.minutes_total or 0) - (self.minutes_used or 0))


class MembershipTransaction(Base):
    """Ledger of membership minutes/money (append-only)."""

    __tablename__ = "membership_transactions"
    __table_args__ = (CheckConstraint(check_in("txn_type", MembershipTxnType), name="txn_type"),)
    id: Mapped[uuid.UUID] = pk()
    membership_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memberships.id"), index=True, nullable=False)
    txn_type: Mapped[str] = mapped_column(String(20), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # signed (+ added, - used)
    amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("game_sessions.id"))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class LoyaltyTransaction(Base):
    __tablename__ = "loyalty_transactions"
    id: Mapped[uuid.UUID] = pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)  # signed
    reason: Mapped[str] = mapped_column(String(40), nullable=False)  # EARN / REDEEM / REFERRAL / ADJUST
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Coupon(Base, TimestampMixin):
    __tablename__ = "coupons"
    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        CheckConstraint("discount_type IN ('PERCENT','FLAT')", name="discount_type"),
    )
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    discount_type: Mapped[str] = mapped_column(String(8), nullable=False)
    value: Mapped[Decimal] = mapped_column(Money, nullable=False)
    min_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    max_discount: Mapped[Decimal | None] = mapped_column(Money)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
