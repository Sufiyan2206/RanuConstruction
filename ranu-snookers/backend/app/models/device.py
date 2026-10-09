from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow
from app.models.base import TimestampMixin, UTCDateTime, pk
from app.models.enums import DeviceStatus, DeviceType, check_in


class Device(Base, TimestampMixin):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(check_in("device_type", DeviceType), name="device_type"),
        CheckConstraint(check_in("status", DeviceStatus), name="status"),
    )
    id: Mapped[uuid.UUID] = pk()
    device_id: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)  # e.g. TABLE4_SENSOR
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    table_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tables.id"), index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    device_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=DeviceStatus.OFFLINE, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    firmware_version: Mapped[str | None] = mapped_column(String(30))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    # Per-device tuning: {"weight": 0.6, "confidence_threshold": 0.85, ...}
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    table = relationship("Table", lazy="joined")


class DeviceEvent(Base):
    __tablename__ = "device_events"
    __table_args__ = (
        UniqueConstraint("device_pk", "event_id"),  # idempotency: duplicate sends are ignored
        Index("ix_device_events_table_time", "table_id", "occurred_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    device_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    table_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tables.id"))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(40))  # e.g. SIGNAL_ACCEPTED / SESSION_STARTED / IGNORED_STALE
    detail: Mapped[str | None] = mapped_column(Text)


class DeviceHeartbeat(Base):
    __tablename__ = "device_heartbeats"
    __table_args__ = (Index("ix_device_heartbeats_device_time", "device_pk", "received_at"),)
    id: Mapped[uuid.UUID] = pk()
    device_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    firmware_version: Mapped[str | None] = mapped_column(String(30))
    uptime_seconds: Mapped[int | None] = mapped_column()
    queue_depth: Mapped[int | None] = mapped_column()  # gateway's unsent-event backlog
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
