from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow
from app.models.base import TimestampMixin, UTCDateTime, pk
from app.models.enums import BillingStatus, DetectionMethod, SessionStatus, check_in


class GameSession(Base, TimestampMixin):
    """One play session on one table.

    `active_table_key` holds the table id while the session is open
    (CREATED/ACTIVE/PAUSED) and NULL once closed. Its UNIQUE constraint makes
    "only one open session per table" a database guarantee on every dialect
    (portable alternative to a PostgreSQL partial unique index).
    """

    __tablename__ = "game_sessions"
    __table_args__ = (
        CheckConstraint(check_in("status", SessionStatus), name="status"),
        CheckConstraint(check_in("billing_status", BillingStatus), name="billing_status"),
        CheckConstraint(check_in("detection_method", DetectionMethod), name="detection_method"),
        Index("ix_game_sessions_branch_started", "branch_id", "started_at"),
        Index("ix_game_sessions_table_status", "table_id", "status"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tables.id"), nullable=False)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("bookings.id"), unique=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("customers.id"), index=True)
    membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("memberships.id"))
    active_table_key: Mapped[str | None] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    billing_status: Mapped[str] = mapped_column(String(12), default=BillingStatus.NOT_STARTED, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # current pause start
    total_paused_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    planned_end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)  # billable, excluding pauses
    started_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    ended_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    detection_method: Mapped[str] = mapped_column(String(10), default=DetectionMethod.MANUAL, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    player_count: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))

    table = relationship("Table", lazy="joined")
    customer = relationship("Customer", lazy="joined")
    pauses = relationship("SessionPause", lazy="selectin", order_by="SessionPause.paused_at")


class SessionEvent(Base):
    """Append-only timeline of a session (state transitions, detections, adjustments)."""

    __tablename__ = "session_events"
    id: Mapped[uuid.UUID] = pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(12))
    to_status: Mapped[str | None] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(String(12), default="MANUAL", nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class SessionPause(Base):
    __tablename__ = "session_pauses"
    id: Mapped[uuid.UUID] = pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    paused_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    resumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reason: Mapped[str | None] = mapped_column(String(200))
    paused_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
