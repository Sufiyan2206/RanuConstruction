"""Password hashing (Argon2id), JWT access tokens, opaque refresh tokens, HMAC helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.errors import Unauthorized

_ph = PasswordHasher()


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(raw: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _ph.verify(hashed, raw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, *, extra: dict | None = None) -> tuple[str, int]:
    now = datetime.now(UTC)
    exp_seconds = settings.ACCESS_TOKEN_MINUTES * 60
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM), exp_seconds


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise Unauthorized("Access token expired", code="TOKEN_EXPIRED") from e
    except jwt.PyJWTError as e:
        raise Unauthorized("Invalid access token", code="TOKEN_INVALID") from e
    if payload.get("typ") != "access":
        raise Unauthorized("Invalid token type", code="TOKEN_INVALID")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def sha256_hex(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def hmac_sha256_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def new_device_secret() -> str:
    return secrets.token_hex(32)
