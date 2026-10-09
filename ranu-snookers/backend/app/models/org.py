from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import JSON, Boolean, Date, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, pk


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)


class Club(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "clubs"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    brand_color: Mapped[str | None] = mapped_column(String(16))


class Branch(Base, TimestampMixin, SoftDeleteMixin):
    """A physical location. Every transactional row references a branch."""

    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    club_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clubs.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Kolkata", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    opening_time: Mapped[str] = mapped_column(String(5), default="10:00", nullable=False)  # local HH:MM
    closing_time: Mapped[str] = mapped_column(String(5), default="02:00", nullable=False)  # may cross midnight
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Structured, validated by app.schemas.settings.BranchSettings (billing, booking policy, detection, tax...)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    club = relationship("Club", lazy="joined")


class Holiday(Base, TimestampMixin):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("branch_id", "day"),)
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class SystemSetting(Base, TimestampMixin):
    """Key/value settings; branch_id NULL = organisation-wide default."""

    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("organization_id", "branch_id", "key"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("branches.id"), nullable=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class DocumentSequence(Base):
    """Gap-less, per-branch document numbering (invoices, orders, bookings).

    Incremented under a row lock inside the business transaction.
    """

    __tablename__ = "document_sequences"
    __table_args__ = (UniqueConstraint("branch_id", "name", "period"),)
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    period: Mapped[str] = mapped_column(String(8), nullable=False)  # e.g. "2026"
    next_value: Mapped[int] = mapped_column(default=1, nullable=False)
