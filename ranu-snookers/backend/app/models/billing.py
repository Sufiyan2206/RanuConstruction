from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow
from app.models.base import Money, TimestampMixin, UTCDateTime, pk
from app.models.enums import InvoiceLineType, InvoiceStatus, check_in


class Invoice(Base, TimestampMixin):
    """Final bill. Once ISSUED, lines are immutable; corrections are made through
    InvoiceAdjustment rows (credit/debit notes) and totals are re-derived."""

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(check_in("status", InvoiceStatus), name="status"),
        Index("ix_invoices_branch_issued", "branch_id", "issued_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=InvoiceStatus.DRAFT, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("game_sessions.id"), unique=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("orders.id"))
    booking_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("bookings.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("customers.id"), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(120))
    subtotal: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    discount_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    deposit_applied: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    adjustments_total: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    balance_due: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    notes: Mapped[str | None] = mapped_column(String(300))

    lines = relationship("InvoiceLine", lazy="selectin", order_by="InvoiceLine.position", cascade="all, delete-orphan")
    adjustments = relationship("InvoiceAdjustment", lazy="selectin", order_by="InvoiceAdjustment.created_at")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (CheckConstraint(check_in("line_type", InvoiceLineType), name="line_type"),)
    id: Mapped[uuid.UUID] = pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(default=0, nullable=False)
    line_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("products.id"))
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class InvoiceAdjustment(Base):
    """Credit (negative) / debit (positive) note against an issued invoice."""

    __tablename__ = "invoice_adjustments"
    id: Mapped[uuid.UUID] = pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
