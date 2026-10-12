"""Organisation, branches, users & roles, settings, holidays, alerts, audit queries."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.security import hash_password
from app.core.timeutil import utcnow
from app.models import Alert, AuditLog, Branch, Club, Holiday, Permission, Role, RolePermission, User, UserRole
from app.schemas.settings import BranchSettings
from app.services.audit import audit, snapshot
from app.services.common import ensure_branch_access, get_branch

BRANCH_FIELDS = ["name", "code", "address", "phone", "email", "timezone", "currency", "opening_time", "closing_time", "is_active"]


def list_branches(db: Session, organization_id: uuid.UUID, *, active_only: bool = True) -> list[Branch]:
    stmt = select(Branch).where(Branch.organization_id == organization_id, Branch.deleted_at.is_(None))
    if active_only:
        stmt = stmt.where(Branch.is_active.is_(True))
    return list(db.scalars(stmt.order_by(Branch.name)).unique().all())


def create_branch(db: Session, actor: Principal, data: dict) -> Branch:
    actor.require("org.manage")
    club = db.scalar(select(Club).where(Club.organization_id == actor.organization_id)) if not data.get("club_id") else db.get(Club, data["club_id"])
    if not club:
        raise ValidationFailed("Club not found")
    if db.scalar(select(Branch.id).where(Branch.organization_id == actor.organization_id, Branch.code == data["code"].upper())):
        raise Conflict("Branch code already exists")
    b = Branch(organization_id=actor.organization_id, club_id=club.id, settings=BranchSettings().model_dump(mode="json"),
               **{k: v for k, v in data.items() if k in BRANCH_FIELDS and k != "code"}, code=data["code"].upper())
    db.add(b)
    db.flush()
    audit(db, actor, "branch.create", "branch", b.id, branch_id=b.id, after=snapshot(b, BRANCH_FIELDS))
    db.commit()
    return b


def update_branch(db: Session, actor: Principal, branch_id: uuid.UUID, data: dict) -> Branch:
    b = get_branch(db, branch_id)
    ensure_branch_access(actor, b, "settings.manage")
    before = snapshot(b, BRANCH_FIELDS)
    for k, v in data.items():
        if k in BRANCH_FIELDS and k != "code":
            setattr(b, k, v)
    audit(db, actor, "branch.update", "branch", b.id, branch_id=b.id, before=before, after=snapshot(b, BRANCH_FIELDS))
    db.commit()
    return b


def update_settings(db: Session, actor: Principal, branch_id: uuid.UUID, patch: dict) -> BranchSettings:
    """Deep-merge a partial settings patch, validate the whole document, audit the diff."""
    b = get_branch(db, branch_id)
    ensure_branch_access(actor, b, "settings.manage")
    if "billing" in patch or "booking" in patch:
        actor.require("pricing.manage", branch_id)
    current = BranchSettings.load(b.settings).model_dump(mode="json")
    merged = _deep_merge(current, patch)
    validated = BranchSettings.model_validate(merged)
    b.settings = validated.model_dump(mode="json")
    audit(db, actor, "branch.settings", "branch", b.id, branch_id=b.id, before=current, after=b.settings)
    db.commit()
    return validated


def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "weights" else v
        if k == "weights" and isinstance(v, dict):
            out[k] = {**a.get(k, {}), **v}
    return out


def add_holiday(db: Session, actor: Principal, branch_id: uuid.UUID, day: date, name: str) -> Holiday:
    ensure_branch_access(actor, get_branch(db, branch_id), "pricing.manage")
    h = Holiday(branch_id=branch_id, day=day, name=name)
    db.add(h)
    audit(db, actor, "holiday.add", "holiday", None, branch_id=branch_id, after={"day": day, "name": name})
    db.commit()
    return h


def remove_holiday(db: Session, actor: Principal, branch_id: uuid.UUID, holiday_id: uuid.UUID) -> None:
    ensure_branch_access(actor, get_branch(db, branch_id), "pricing.manage")
    db.execute(delete(Holiday).where(Holiday.id == holiday_id, Holiday.branch_id == branch_id))
    audit(db, actor, "holiday.remove", "holiday", holiday_id, branch_id=branch_id)
    db.commit()


# ------------------------------------------------------------------------------ users & roles
def list_users(db: Session, actor: Principal) -> list[User]:
    actor.require("users.manage")
    customer_role = db.scalar(select(Role.id).where(Role.organization_id == actor.organization_id, Role.code == "CUSTOMER"))
    users = db.scalars(select(User).where(User.organization_id == actor.organization_id).order_by(User.full_name)).all()
    return [u for u in users if not (u.customer_id and all(r.role_id == customer_role for r in u.roles))]


def create_user(db: Session, actor: Principal, data: dict) -> User:
    actor.require("users.manage")
    uname = data["username"].strip().lower()
    if db.scalar(select(User.id).where(User.organization_id == actor.organization_id, User.username == uname)):
        raise Conflict("Username already exists")
    u = User(organization_id=actor.organization_id, username=uname, email=(data.get("email") or None), phone=data.get("phone"), full_name=data["full_name"],
             password_hash=hash_password(data["password"]) if data.get("password") else None, pin_hash=hash_password(data["pin"]) if data.get("pin") else None)
    db.add(u)
    db.flush()
    for ra in data.get("roles", []):
        _assign(db, actor, u, ra["role_code"], ra.get("branch_id"))
    audit(db, actor, "user.create", "user", u.id, after={"username": uname, "roles": data.get("roles", [])})
    db.commit()
    db.refresh(u)
    return u


def update_user(db: Session, actor: Principal, user_id: uuid.UUID, data: dict) -> User:
    actor.require("users.manage")
    u = db.get(User, user_id)
    if not u or u.organization_id != actor.organization_id:
        raise NotFound("User not found")
    before = {"is_active": u.is_active, "roles": [(r.role.code, str(r.branch_id)) for r in u.roles]}
    for k in ("full_name", "email", "phone", "is_active"):
        if k in data:
            setattr(u, k, data[k])
    if data.get("password"):
        u.password_hash = hash_password(data["password"])
    if data.get("pin"):
        u.pin_hash = hash_password(data["pin"])
    if "roles" in data:
        if u.id == actor.id:
            raise Forbidden("You cannot change your own roles")
        db.execute(delete(UserRole).where(UserRole.user_id == u.id))
        db.flush()
        db.expire(u, ["roles"])
        for ra in data["roles"]:
            _assign(db, actor, u, ra["role_code"], ra.get("branch_id"))
    db.flush()
    db.refresh(u)
    audit(db, actor, "user.permissions" if "roles" in data else "user.update", "user", u.id, before=before,
          after={"is_active": u.is_active, "roles": [(r.role.code, str(r.branch_id)) for r in u.roles]})
    db.commit()
    return u


def _assign(db: Session, actor: Principal, u: User, role_code: str, branch_id) -> None:
    role = db.scalar(select(Role).where(Role.organization_id == actor.organization_id, Role.code == role_code))
    if not role:
        raise ValidationFailed(f"Unknown role {role_code}")
    if role.code == "SUPER_ADMIN" and not actor.has("roles.manage"):
        raise Forbidden("Only a Super Admin can grant Super Admin")
    db.add(UserRole(user_id=u.id, role_id=role.id, branch_id=uuid.UUID(str(branch_id)) if branch_id else None))


def list_roles(db: Session, actor: Principal) -> list[Role]:
    return list(db.scalars(select(Role).where(Role.organization_id == actor.organization_id).order_by(Role.name)).all())


def set_role_permissions(db: Session, actor: Principal, role_id: uuid.UUID, codes: list[str]) -> Role:
    actor.require("roles.manage")
    role = db.get(Role, role_id)
    if not role or role.organization_id != actor.organization_id:
        raise NotFound("Role not found")
    if role.code == "SUPER_ADMIN":
        raise Forbidden("Super Admin permissions cannot be reduced")
    perms = db.scalars(select(Permission).where(Permission.code.in_(codes))).all()
    before = sorted(p.code for p in role.permissions)
    db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for p in perms:
        db.add(RolePermission(role_id=role.id, permission_id=p.id))
    db.flush()
    db.expire(role)
    audit(db, actor, "role.permissions", "role", role.id, before={"permissions": before}, after={"permissions": sorted(codes)})
    db.commit()
    return role


# ------------------------------------------------------------------------------ alerts & audit
def list_alerts(db: Session, actor: Principal, branch_id: uuid.UUID, open_only: bool = True) -> list[Alert]:
    actor.require("tables.view", branch_id)
    stmt = select(Alert).where(Alert.branch_id == branch_id)
    if open_only:
        stmt = stmt.where(Alert.acknowledged_at.is_(None))
    return list(db.scalars(stmt.order_by(Alert.created_at.desc()).limit(200)).all())


def ack_alert(db: Session, actor: Principal, alert_id: uuid.UUID) -> Alert:
    a = db.get(Alert, alert_id)
    if not a:
        raise NotFound("Alert not found")
    actor.require("alerts.manage", a.branch_id) if a.severity == "CRITICAL" else actor.require("tables.view", a.branch_id)
    a.acknowledged_at, a.acknowledged_by_id = utcnow(), actor.id
    audit(db, actor, "alert.ack", "alert", a.id, branch_id=a.branch_id)
    db.commit()
    return a


def audit_logs(db: Session, actor: Principal, *, branch_id: uuid.UUID | None, entity_type: str | None, entity_id: str | None, action: str | None,
               user_id: uuid.UUID | None, frm: datetime | None, to: datetime | None, offset: int, limit: int) -> tuple[list[AuditLog], int]:
    actor.require("audit.view", branch_id)
    stmt = select(AuditLog).where((AuditLog.organization_id == actor.organization_id) | AuditLog.organization_id.is_(None))
    if branch_id:
        stmt = stmt.where(AuditLog.branch_id == branch_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if frm:
        stmt = stmt.where(AuditLog.created_at >= frm)
    if to:
        stmt = stmt.where(AuditLog.created_at < to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    return list(db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)).all()), total
