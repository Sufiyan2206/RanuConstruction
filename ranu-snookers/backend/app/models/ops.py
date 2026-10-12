"""Operational models: audit, alerts, approvals, shifts, expenses, tournaments, notifications."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow
from app.models.base import Money, TimestampMixin, UTCDateTime, pk
from app.models.enums import (
    AlertSeverity,
    ApprovalStatus,
    ApprovalType,
    MatchStatus,
    NotificationChannel,
    NotificationStatus,
    ShiftStatus,
    TournamentFormat,
    TournamentStatus,
    check_in,
)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_branch_time", "branch_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("organizations.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("branches.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    username: Mapped[str | None] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. booking.cancel
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(40))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    request_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Alert(Base):
    """Operational / anti-fraud alerts shown on the dashboard."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(check_in("severity", AlertSeverity), name="severity"),
        Index("ix_alerts_branch_open", "branch_id", "acknowledged_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default=AlertSeverity.WARNING, nullable=False)
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    table_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tables.id"))
    device_pk: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("devices.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("game_sessions.id"))
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class ApprovalRequest(Base, TimestampMixin):
    """Maker-checker: staff requests (discounts, item cancellation, bill adjustments)
    that a manager/admin must approve. Carried over from the legacy app."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(check_in("approval_type", ApprovalType), name="approval_type"),
        CheckConstraint(check_in("status", ApprovalStatus), name="status"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    approval_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default=ApprovalStatus.PENDING, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("game_sessions.id"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id"))
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("order_items.id"))
    amount: Mapped[Decimal | None] = mapped_column(Money)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolution_note: Mapped[str | None] = mapped_column(String(300))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Shift(Base, TimestampMixin):
    """Cash-drawer shift (legacy 'Shift' tab): opening float, expected vs counted cash."""

    __tablename__ = "shifts"
    __table_args__ = (CheckConstraint(check_in("status", ShiftStatus), name="status"),)
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    open_key: Mapped[str | None] = mapped_column(String(36), unique=True)  # user_id while OPEN -> one open shift per user
    status: Mapped[str] = mapped_column(String(8), default=ShiftStatus.OPEN, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    opening_cash: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    cash_sales: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    cash_expenses: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    expected_cash: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    counted_cash: Mapped[Decimal | None] = mapped_column(Money)
    variance: Mapped[Decimal | None] = mapped_column(Money)
    notes: Mapped[str | None] = mapped_column(String(300))


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#0369a1", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"
    __table_args__ = (Index("ix_expenses_branch_date", "branch_id", "expense_date"), CheckConstraint("amount > 0", name="amount"))
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expense_categories.id"), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    paid_to: Mapped[str | None] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(12), default="CASH", nullable=False)
    shift_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("shifts.id"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    is_void: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    void_reason: Mapped[str | None] = mapped_column(String(200))

    category = relationship("ExpenseCategory", lazy="joined")


class Tournament(Base, TimestampMixin):
    __tablename__ = "tournaments"
    __table_args__ = (
        CheckConstraint(check_in("format", TournamentFormat), name="format"),
        CheckConstraint(check_in("status", TournamentStatus), name="status"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    game_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("game_types.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    format: Mapped[str] = mapped_column(String(20), default=TournamentFormat.KNOCKOUT, nullable=False)
    status: Mapped[str] = mapped_column(String(14), default=TournamentStatus.DRAFT, nullable=False)
    entry_fee: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    prize_pool: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    max_players: Mapped[int] = mapped_column(Integer, default=32, nullable=False)
    group_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    starts_on: Mapped[date | None] = mapped_column(Date)
    winner_player_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tournament_players.id", use_alter=True))
    rules: Mapped[str | None] = mapped_column(Text)


class TournamentPlayer(Base):
    __tablename__ = "tournament_players"
    __table_args__ = (UniqueConstraint("tournament_id", "customer_id"),)
    id: Mapped[uuid.UUID] = pk()
    tournament_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer)
    group_no: Mapped[int | None] = mapped_column(Integer)
    fee_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    frames_for: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    frames_against: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    eliminated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TournamentMatch(Base):
    __tablename__ = "tournament_matches"
    __table_args__ = (
        CheckConstraint(check_in("status", MatchStatus), name="status"),
        UniqueConstraint("tournament_id", "stage", "round_no", "match_no"),
    )
    id: Mapped[uuid.UUID] = pk()
    tournament_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(10), default="KO", nullable=False)  # GROUP / KO
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    match_no: Mapped[int] = mapped_column(Integer, nullable=False)
    group_no: Mapped[int | None] = mapped_column(Integer)
    player1_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tournament_players.id"))
    player2_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tournament_players.id"))
    score1: Mapped[int | None] = mapped_column(Integer)
    score2: Mapped[int | None] = mapped_column(Integer)
    winner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tournament_players.id"))
    table_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tables.id"))
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(12), default=MatchStatus.PENDING, nullable=False)
    next_match_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tournament_matches.id"))
    next_slot: Mapped[int | None] = mapped_column(Integer)  # 1 or 2


class NotificationTemplate(Base, TimestampMixin):
    __tablename__ = "notification_templates"
    __table_args__ = (UniqueConstraint("organization_id", "event", "channel"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    event: Mapped[str] = mapped_column(String(40), nullable=False)  # booking.confirmed, session.ending ...
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, nullable=False)  # str.format-style {placeholders}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(check_in("channel", NotificationChannel), name="channel"),
        CheckConstraint(check_in("status", NotificationStatus), name="status"),
        UniqueConstraint("dedupe_key"),
        Index("ix_notifications_status", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("branches.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("customers.id"))
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    recipient: Mapped[str] = mapped_column(String(160), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default=NotificationStatus.QUEUED, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(300))
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
