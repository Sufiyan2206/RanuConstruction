from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutil import utcnow
from app.models.base import Money, SoftDeleteMixin, TimestampMixin, UTCDateTime, pk
from app.models.enums import LedgerEntryType, check_in


class Customer(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("organization_id", "phone"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    home_branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("branches.id"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)  # E.164-ish, digits only (also WhatsApp)
    email: Mapped[str | None] = mapped_column(String(160), index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    preferred_game_type_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("game_types.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    # Denormalised CRM counters, updated transactionally on invoice payment.
    total_visits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_spend: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    total_play_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_visit_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    referral_code: Mapped[str | None] = mapped_column(String(12), unique=True)
    referred_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("customers.id"))
    marketing_opt_in: Mapped[bool] = mapped_column(default=False, nullable=False)


class CustomerLedgerEntry(Base):
    """Customer dues ("Credit (Due)" in the legacy app). Append-only.

    amount > 0  => customer owes more (credit sale / opening due)
    amount < 0  => customer paid / due reduced
    Outstanding balance = SUM(amount).
    """

    __tablename__ = "customer_ledger"
    __table_args__ = (
        CheckConstraint(check_in("entry_type", LedgerEntryType), name="entry_type"),
        Index("ix_customer_ledger_customer_created", "customer_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id"))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("payments.id"))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
