"""Authentication: password / PIN login, refresh-token rotation with reuse
detection, customer self-registration, lockout after repeated failures."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import Principal, build_principal
from app.core.errors import Conflict, Unauthorized
from app.core.security import create_access_token, hash_password, new_refresh_token, sha256_hex, verify_password
from app.core.timeutil import utcnow
from app.models import Customer, Organization, RefreshToken, Role, User, UserRole
from app.services.audit import audit
from app.services.customer_service import normalize_phone

MAX_FAILED = 5
LOCK_MINUTES = 15


@dataclass
class TokenPair:
    access_token: str
    expires_in: int
    refresh_token: str
    user: User


def _issue(db: Session, user: User, *, family_id: uuid.UUID | None = None, ip: str | None = None, ua: str | None = None) -> TokenPair:
    access, exp = create_access_token(user.id, extra={"org": str(user.organization_id)})
    raw = new_refresh_token()
    now = utcnow()
    db.add(
        RefreshToken(
            user_id=user.id, token_hash=sha256_hex(raw), family_id=family_id or uuid.uuid4(), issued_at=now,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_DAYS), user_agent=(ua or "")[:200], ip=ip,
        )
    )
    return TokenPair(access, exp, raw, user)


def _check_lock(user: User) -> None:
    if user.locked_until and user.locked_until > utcnow():
        raise Unauthorized("Account temporarily locked after failed attempts. Try again later.", code="ACCOUNT_LOCKED")


def _fail(db: Session, user: User) -> None:
    user.failed_logins += 1
    if user.failed_logins >= MAX_FAILED:
        user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
        user.failed_logins = 0
    db.commit()


def login(db: Session, identifier: str, password: str, *, ip: str | None = None, ua: str | None = None) -> TokenPair:
    ident = identifier.strip().lower()
    try:
        phone = normalize_phone(identifier)
    except Exception:
        phone = None
    conds = [User.username == ident, User.email == ident]
    if phone:
        conds.append(User.phone == phone)
    user = db.scalar(select(User).where(or_(*conds)))
    if not user or not user.is_active:
        raise Unauthorized("Invalid credentials", code="INVALID_CREDENTIALS")
    _check_lock(user)
    if not verify_password(password, user.password_hash):
        _fail(db, user)
        raise Unauthorized("Invalid credentials", code="INVALID_CREDENTIALS")
    return _success(db, user, "auth.login", ip, ua)


def pin_login(db: Session, username: str, pin: str, *, ip: str | None = None, ua: str | None = None) -> TokenPair:
    """Quick login for counter staff on a shared tablet (legacy passcode login)."""
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if not user or not user.is_active or not user.pin_hash:
        raise Unauthorized("Invalid PIN", code="INVALID_CREDENTIALS")
    _check_lock(user)
    if not verify_password(pin, user.pin_hash):
        _fail(db, user)
        raise Unauthorized("Invalid PIN", code="INVALID_CREDENTIALS")
    return _success(db, user, "auth.pin_login", ip, ua)


def _success(db: Session, user: User, action: str, ip, ua) -> TokenPair:
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    pair = _issue(db, user, ip=ip, ua=ua)
    p = build_principal(user)
    p.ip, p.user_agent = ip, ua
    audit(db, p, action, "user", user.id)
    db.commit()
    return pair


def refresh(db: Session, raw_token: str, *, ip: str | None = None, ua: str | None = None) -> TokenPair:
    """Rotate refresh token. Presenting an already-rotated token revokes the whole
    token family (stolen-token reuse detection)."""
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token)))
    if not row:
        raise Unauthorized("Invalid refresh token", code="REFRESH_INVALID")
    now = utcnow()
    if row.revoked_at is not None:
        db.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=now))
        db.commit()
        raise Unauthorized("Refresh token reuse detected; please log in again", code="REFRESH_REUSED")
    if row.expires_at < now:
        raise Unauthorized("Refresh token expired", code="REFRESH_EXPIRED")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise Unauthorized("User inactive")
    row.revoked_at = now
    pair = _issue(db, user, family_id=row.family_id, ip=ip, ua=ua)
    db.commit()
    return pair


def logout(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token)))
    if row and row.revoked_at is None:
        db.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
        db.commit()


def register_customer(db: Session, *, organization: Organization, name: str, phone: str, email: str | None, password: str) -> TokenPair:
    phone_n = normalize_phone(phone)
    if db.scalar(select(User).where(or_(User.phone == phone_n, User.email == (email or "").lower() or None))):
        raise Conflict("An account with this phone/email already exists", code="ACCOUNT_EXISTS")
    customer = db.scalar(select(Customer).where(Customer.organization_id == organization.id, Customer.phone == phone_n))
    if customer is None:
        from app.services.customer_service import new_referral_code

        customer = Customer(organization_id=organization.id, name=name.strip(), phone=phone_n, email=(email or None), referral_code=new_referral_code(db))
        db.add(customer)
        db.flush()
    role = db.scalar(select(Role).where(Role.organization_id == organization.id, Role.code == "CUSTOMER"))
    user = User(
        organization_id=organization.id, username=f"c{phone_n}", email=(email.lower() if email else None), phone=phone_n,
        full_name=name.strip(), password_hash=hash_password(password), customer_id=customer.id,
    )
    db.add(user)
    db.flush()
    if role:
        db.add(UserRole(user_id=user.id, role_id=role.id, branch_id=None))
    db.flush()
    db.refresh(user)
    pair = _issue(db, user)
    audit(db, build_principal(user), "auth.register", "user", user.id)
    db.commit()
    return pair


def change_password(db: Session, actor: Principal, current: str, new: str) -> None:
    if not verify_password(current, actor.user.password_hash):
        raise Unauthorized("Current password is incorrect", code="INVALID_CREDENTIALS")
    actor.user.password_hash = hash_password(new)
    db.execute(update(RefreshToken).where(RefreshToken.user_id == actor.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    audit(db, actor, "auth.change_password", "user", actor.id)
    db.commit()
