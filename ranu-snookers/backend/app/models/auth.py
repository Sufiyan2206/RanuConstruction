from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, pk


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = pk()
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class Role(Base, TimestampMixin):
    """Roles are data, not code. Seeded defaults can be edited by a Super Admin."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    permissions = relationship("Permission", secondary="role_permissions", lazy="selectin")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("organization_id", "username"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(60), nullable=False)
    email: Mapped[str | None] = mapped_column(String(160), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Short PIN for quick staff login on the shared counter tablet (replaces the
    # passcode login of the legacy RS Sales app). Hashed with Argon2 like passwords.
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("customers.id"), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failed_logins: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)

    roles = relationship("UserRole", lazy="selectin", cascade="all, delete-orphan")


class UserRole(Base):
    """Role assignment, optionally scoped to one branch (NULL = all branches)."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", "branch_id"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("branches.id"), nullable=True)

    role = relationship("Role", lazy="selectin")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    user_agent: Mapped[str | None] = mapped_column(String(200))
    ip: Mapped[str | None] = mapped_column(String(64))
