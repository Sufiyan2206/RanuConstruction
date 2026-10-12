from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutil import utcnow
from app.models.base import Money, TimestampMixin, UTCDateTime, pk
from app.models.enums import PaymentMethod, PaymentPurpose, PaymentStatus, check_in


class Payment(Base, TimestampMixin):
    """Money movement. Never updated destructively: refunds are separate rows
    (purpose=REFUND, negative amount, refund_of_id -> original)."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(check_in("status", PaymentStatus), name="status"),
        CheckConstraint(check_in("method", PaymentMethod), name="method"),
        CheckConstraint(check_in("purpose", PaymentPurpose), name="purpose"),
        UniqueConstraint("provider", "provider_payment_id"),
        Index("ix_payments_branch_paid", "branch_id", "paid_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    method: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("bookings.id"), index=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("customers.id"), index=True)
    membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("memberships.id"))
    provider: Mapped[str | None] = mapped_column(String(20))
    provider_order_id: Mapped[str | None] = mapped_column(String(80), index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(80))
    reference: Mapped[str | None] = mapped_column(String(80))  # UPI ref / card slip no.
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    refund_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("payments.id"))
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    shift_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("shifts.id"))
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_reason: Mapped[str | None] = mapped_column(String(300))
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class PaymentWebhookEvent(Base):
    """Every provider webhook is stored once (idempotency on provider+event_id)."""

    __tablename__ = "payment_webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)
    id: Mapped[uuid.UUID] = pk()
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    result: Mapped[str | None] = mapped_column(Text)


class IdempotencyRecord(Base):
    """Generic API idempotency: same (scope, key) returns the stored response."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key"),)
    id: Mapped[uuid.UUID] = pk()
    scope: Mapped[str] = mapped_column(String(60), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    response: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
