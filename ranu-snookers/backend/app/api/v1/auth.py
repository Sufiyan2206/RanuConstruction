"""Authentication endpoints. Access token in body; refresh token in an httpOnly,
SameSite=Strict cookie scoped to /api/v1/auth (also returned in the body for
native mobile apps that cannot use cookies)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import Principal, get_principal
from app.core.errors import NotFound
from app.core.ratelimit import rate_limit
from app.models import Organization
from app.schemas.common import Message
from app.schemas.domain import ChangePasswordIn, LoginIn, MeOut, PinLoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "ranu_refresh"


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, httponly=True, secure=settings.COOKIE_SECURE, samesite="strict", path=f"{settings.API_PREFIX}/auth",
                    max_age=settings.REFRESH_TOKEN_DAYS * 86400, domain=settings.COOKIE_DOMAIN)


def _out(resp: Response, pair) -> TokenOut:
    _set_cookie(resp, pair.refresh_token)
    return TokenOut(access_token=pair.access_token, expires_in=pair.expires_in, refresh_token=pair.refresh_token, user=UserOut.model_validate(pair.user))


def _client(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None), (request.headers.get("user-agent") or "")[:200]


@router.post("/login", response_model=TokenOut, dependencies=[Depends(rate_limit("auth", settings.RATE_LIMIT_AUTH_PER_MINUTE))])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip, ua = _client(request)
    return _out(response, auth_service.login(db, body.identifier, body.password, ip=ip, ua=ua))


@router.post("/pin-login", response_model=TokenOut, dependencies=[Depends(rate_limit("auth", settings.RATE_LIMIT_AUTH_PER_MINUTE))])
def pin_login(body: PinLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip, ua = _client(request)
    return _out(response, auth_service.pin_login(db, body.username, body.pin, ip=ip, ua=ua))


@router.post("/register", response_model=TokenOut, dependencies=[Depends(rate_limit("auth", settings.RATE_LIMIT_AUTH_PER_MINUTE))])
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    org = db.scalar(select(Organization).order_by(Organization.created_at))
    if not org:
        raise NotFound("Organisation not configured")
    return _out(response, auth_service.register_customer(db, organization=org, name=body.name, phone=body.phone, email=body.email, password=body.password))


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(rate_limit("refresh", 30))])
def refresh(request: Request, response: Response, body: RefreshIn | None = None, db: Session = Depends(get_db)):
    raw = (body.refresh_token if body else None) or request.cookies.get(COOKIE)
    ip, ua = _client(request)
    if not raw:
        from app.core.errors import Unauthorized

        raise Unauthorized("No refresh token", code="REFRESH_INVALID")
    return _out(response, auth_service.refresh(db, raw, ip=ip, ua=ua))


@router.post("/logout", response_model=Message)
def logout(request: Request, response: Response, body: RefreshIn | None = None, db: Session = Depends(get_db)):
    auth_service.logout(db, (body.refresh_token if body else None) or request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path=f"{settings.API_PREFIX}/auth")
    return Message(message="Logged out")


@router.get("/me", response_model=MeOut)
def me(p: Principal = Depends(get_principal)):
    b = p.branch_ids()
    return MeOut(
        user=UserOut.model_validate(p.user),
        roles=[{"code": ur.role.code, "name": ur.role.name, "branch_id": ur.branch_id} for ur in p.user.roles],
        permissions=sorted(p.all_permissions()),
        branch_ids=sorted(b) if b is not None else None,
    )


@router.post("/change-password", response_model=Message)
def change_password(body: ChangePasswordIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    auth_service.change_password(db, p, body.current_password, body.new_password)
    return Message(message="Password changed; other sessions were signed out")
