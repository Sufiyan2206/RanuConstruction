"""Shared column types and mixins for every model."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, TypeDecorator, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import ensure_utc, utcnow


class UTCDateTime(TypeDecorator):
    """Stores UTC; always returns timezone-aware UTC datetimes on every dialect.

    PostgreSQL keeps `timestamptz`; MySQL/SQLite store naive UTC values.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = ensure_utc(value)
        if dialect.name != "postgresql":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return ensure_utc(value) if value is not None else None


Money = Numeric(12, 2)
Rate = Numeric(10, 2)


def money(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SoftDeleteMixin:
    """Only for master data (products, customers...). NEVER for financial records."""

    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


def enum_str(length: int = 24):
    return String(length)
