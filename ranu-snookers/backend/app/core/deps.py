"""FastAPI dependencies: authenticated principal, permission checks, pagination."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_access_token
from app.models import User

bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """The authenticated caller, resolved once per request.

    permissions_by_branch maps branch_id (or None = every branch) to a set of
    permission codes.
    """

    user: User
    permissions_by_branch: dict[uuid.UUID | None, set[str]] = field(default_factory=dict)
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def organization_id(self) -> uuid.UUID:
        return self.user.organization_id

    @property
    def role_codes(self) -> list[str]:
        return sorted({ur.role.code for ur in self.user.roles})

    def has(self, perm: str, branch_id: uuid.UUID | None = None) -> bool:
        if perm in self.permissions_by_branch.get(None, set()):
            return True
        if branch_id is not None and perm in self.permissions_by_branch.get(branch_id, set()):
            return True
        if branch_id is None:  # "anywhere" check
            return any(perm in s for s in self.permissions_by_branch.values())
        return False

    def require(self, perm: str, branch_id: uuid.UUID | None = None) -> None:
        """Service-level authorisation check (defence in depth behind route deps)."""
        if not self.has(perm, branch_id):
            raise Forbidden(f"Missing permission '{perm}'" + (" for this branch" if branch_id else ""))

    def branch_ids(self) -> set[uuid.UUID] | None:
        """None => all branches."""
        if None in self.permissions_by_branch and self.permissions_by_branch[None] - {"self.bookings"}:
            return None
        return {b for b in self.permissions_by_branch if b is not None}

    def all_permissions(self) -> set[str]:
        out: set[str] = set()
        for s in self.permissions_by_branch.values():
            out |= s
        return out


def build_principal(user: User, request: Request | None = None) -> Principal:
    perms: dict[uuid.UUID | None, set[str]] = {}
    for ur in user.roles:
        perms.setdefault(ur.branch_id, set()).update(p.code for p in ur.role.permissions)
    p = Principal(user=user, permissions_by_branch=perms)
    if request is not None:
        p.ip = request.client.host if request.client else None
        p.user_agent = (request.headers.get("user-agent") or "")[:200]
        p.request_id = getattr(request.state, "request_id", None)
    return p


def get_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    if not creds:
        raise Unauthorized("Authentication required")
    payload = decode_access_token(creds.credentials)
    user = db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise Unauthorized("User inactive or not found")
    return build_principal(user, request)


def get_optional_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal | None:
    if not creds:
        return None
    try:
        return get_principal(request, creds, db)
    except Unauthorized:
        return None


def require(perm: str):
    """Route-level guard: caller must hold `perm` in at least one branch.
    Branch-specific checks happen again in the service layer."""

    def _dep(p: Principal = Depends(get_principal)) -> Principal:
        if not p.has(perm):
            raise Forbidden(f"Missing permission '{perm}'")
        return p

    return _dep


@dataclass
class PageParams:
    page: int
    size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def page_params(page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)) -> PageParams:
    return PageParams(page=page, size=size)
