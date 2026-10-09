from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Rate, SoftDeleteMixin, TimestampMixin, UTCDateTime, pk
from app.models.enums import DetectionState, TableStatus, check_in


class GameType(Base, TimestampMixin):
    """Snooker, Pool, Billiards, PS5 ... fully configurable."""

    __tablename__ = "game_types"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    default_hourly_rate: Mapped[Decimal] = mapped_column(Rate, default=0, nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#146c3a", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Table(Base, TimestampMixin, SoftDeleteMixin):
    """A bookable/playable resource (snooker table, pool table, PS5 console...)."""

    __tablename__ = "tables"
    __table_args__ = (
        UniqueConstraint("branch_id", "table_number"),
        CheckConstraint(check_in("status", TableStatus), name="status"),
        CheckConstraint("minimum_booking_duration > 0", name="min_duration"),
        CheckConstraint("maximum_booking_duration >= minimum_booking_duration", name="max_duration"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    table_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    game_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("game_types.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=TableStatus.AVAILABLE, nullable=False)
    # Base rates. Time-window/member/holiday rules live in pricing_rules.
    hourly_rate: Mapped[Decimal] = mapped_column(Rate, nullable=False)
    peak_rate: Mapped[Decimal | None] = mapped_column(Rate)
    off_peak_rate: Mapped[Decimal | None] = mapped_column(Rate)
    minimum_booking_duration: Mapped[int] = mapped_column(Integer, default=30, nullable=False)  # minutes
    maximum_booking_duration: Mapped[int] = mapped_column(Integer, default=240, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_online_bookable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    qr_token: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    game_type = relationship("GameType", lazy="joined")


class PricingRule(Base, TimestampMixin):
    """Configurable price override. The most specific/highest-priority rule that
    matches a given minute wins; otherwise the table's base hourly_rate applies.

    Scope:      branch (required) → optional game_type → optional table
    When:       day_type (ANY/WEEKDAY/WEEKEND/HOLIDAY), days_of_week, time window, date range
    Who:        customer_segment (ANY/MEMBER/NON_MEMBER)
    Price:      rate_per_hour (absolute)  OR  rate_multiplier (e.g. 0.8 for 20% off)
    """

    __tablename__ = "pricing_rules"
    __table_args__ = (
        CheckConstraint("day_type IN ('ANY','WEEKDAY','WEEKEND','HOLIDAY')", name="day_type"),
        CheckConstraint("customer_segment IN ('ANY','MEMBER','NON_MEMBER')", name="segment"),
        CheckConstraint("rate_per_hour IS NOT NULL OR rate_multiplier IS NOT NULL", name="has_price"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="STANDARD", nullable=False)  # PEAK/OFF_PEAK/HAPPY_HOUR/HOLIDAY/PROMO/MEMBER
    game_type_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("game_types.id"))
    table_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tables.id"))
    day_type: Mapped[str] = mapped_column(String(10), default="ANY", nullable=False)
    days_of_week: Mapped[list | None] = mapped_column(JSON)  # [0..6], Monday=0; NULL = all
    start_time: Mapped[str | None] = mapped_column(String(5))  # local "HH:MM"; NULL = all day
    end_time: Mapped[str | None] = mapped_column(String(5))  # may be < start_time (crosses midnight)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    customer_segment: Mapped[str] = mapped_column(String(12), default="ANY", nullable=False)
    rate_per_hour: Mapped[Decimal | None] = mapped_column(Rate)
    rate_multiplier: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TableDetectionState(Base):
    """Persistent per-table state of the activity-detection state machine.

    Persisted (not in-memory) so a server restart does not lose partially
    confirmed activity and multiple API instances agree on the state.
    """

    __tablename__ = "table_detection_states"
    __table_args__ = (CheckConstraint(check_in("state", DetectionState), name="state"),)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tables.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(20), default=DetectionState.IDLE, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    first_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    activity_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    identified_customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("customers.id"))
    identified_membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("memberships.id"))
    identified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    signals: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # recent signals in window
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
