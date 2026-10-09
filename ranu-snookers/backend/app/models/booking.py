from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Money, TimestampMixin, UTCDateTime, pk
from app.models.enums import BookingSource, BookingStatus, PaymentStatus, check_in


class Booking(Base, TimestampMixin):
    """A reservation of a table for [start_at, end_at).

    Overlap protection (see BookingService):
      1. the target `tables` row is locked (SELECT ... FOR UPDATE) for the whole transaction,
      2. overlapping blocking bookings / open sessions are checked under that lock,
      3. on PostgreSQL an EXCLUDE USING gist constraint (migration 0002) is a final
         database-level guarantee.
    """

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(check_in("status", BookingStatus), name="status"),
        CheckConstraint(check_in("source", BookingSource), name="source"),
        CheckConstraint(check_in("payment_status", PaymentStatus), name="payment_status"),
        CheckConstraint("end_at > start_at", name="time_order"),
        CheckConstraint("deposit_amount >= 0 AND booking_amount >= 0", name="amounts"),
        Index("ix_bookings_table_window", "table_id", "start_at", "end_at"),
        Index("ix_bookings_branch_start", "branch_id", "start_at"),
        Index("ix_bookings_status_hold", "status", "hold_expires_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tables.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    reference: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(12), default=BookingSource.ONLINE, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    hold_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Money snapshot (quote computed by backend pricing engine at booking time)
    booking_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    deposit_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    discount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    remaining_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    payment_status: Mapped[str] = mapped_column(String(16), default=PaymentStatus.PENDING, nullable=False)
    coupon_code: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    checked_in_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    refund_amount: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("bookings.id"))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))

    table = relationship("Table", lazy="joined")
    customer = relationship("Customer", lazy="joined")


class BookingHold(Base):
    """Audit trail of checkout holds (abandoned-checkout analytics)."""

    __tablename__ = "booking_holds"
    id: Mapped[uuid.UUID] = pk()
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    outcome: Mapped[str | None] = mapped_column(String(20))  # CONFIRMED / EXPIRED / CANCELLED
