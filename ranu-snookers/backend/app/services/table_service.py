"""Tables, game types, pricing rules and the live table-status board."""
from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.core.errors import Conflict, InvalidState, NotFound, ValidationFailed
from app.core.realtime import PendingEvents
from app.core.timeutil import utcnow
from app.models import Booking, Branch, Device, GameSession, GameType, Holiday, PricingRule, Table
from app.models.enums import BLOCKING_BOOKING_STATUSES, OPEN_SESSION_STATUSES, BookingStatus, SessionStatus, TableStatus
from app.services.audit import audit, snapshot
from app.services.common import ensure_branch_access, get_branch
from app.services.pricing import PricingContext, RuleSpec

TABLE_FIELDS = ["name", "table_number", "game_type_id", "status", "hourly_rate", "peak_rate", "off_peak_rate",
                "minimum_booking_duration", "maximum_booking_duration", "is_active", "is_online_bookable", "sort_order"]
PRICE_FIELDS = ["hourly_rate", "peak_rate", "off_peak_rate"]


# ----------------------------------------------------------------------------- lookups
def get_table(db: Session, table_id: uuid.UUID) -> Table:
    t = db.get(Table, table_id)
    if not t or t.deleted_at is not None:
        raise NotFound("Table not found")
    return t


def list_tables(db: Session, branch_id: uuid.UUID, *, include_inactive: bool = False, game_type_id: uuid.UUID | None = None) -> list[Table]:
    stmt = select(Table).where(Table.branch_id == branch_id, Table.deleted_at.is_(None))
    if not include_inactive:
        stmt = stmt.where(Table.is_active.is_(True))
    if game_type_id:
        stmt = stmt.where(Table.game_type_id == game_type_id)
    return list(db.scalars(stmt.order_by(Table.sort_order, Table.table_number)).unique().all())


# ----------------------------------------------------------------------------- pricing context
def pricing_context(db: Session, table: Table, *, is_member: bool, days: tuple[date, date] | None = None) -> PricingContext:
    branch = db.get(Branch, table.branch_id)
    rules = db.scalars(select(PricingRule).where(PricingRule.branch_id == table.branch_id, PricingRule.is_active.is_(True))).all()
    hol_stmt = select(Holiday.day).where(Holiday.branch_id == table.branch_id)
    if days:
        hol_stmt = hol_stmt.where(Holiday.day >= days[0] - timedelta(days=1), Holiday.day <= days[1] + timedelta(days=1))
    holidays = set(db.scalars(hol_stmt).all())
    return PricingContext(
        tz=branch.timezone, base_rate=Decimal(str(table.hourly_rate)), table_id=table.id, game_type_id=table.game_type_id,
        peak_rate=Decimal(str(table.peak_rate)) if table.peak_rate is not None else None,
        off_peak_rate=Decimal(str(table.off_peak_rate)) if table.off_peak_rate is not None else None,
        rules=[RuleSpec.from_model(r) for r in rules], holidays=holidays, is_member=is_member,
    )


# ----------------------------------------------------------------------------- status
def set_status(db: Session, table: Table, status: TableStatus, events: PendingEvents | None, *, reason: str | None = None) -> None:
    if table.status == status:
        return
    table.status = status
    table.status_changed_at = utcnow()
    if events is not None:
        events.add(
            table.branch_id, "table.status",
            {"table_id": table.id, "table_number": table.table_number, "status": status, "reason": reason},
            public={"table_id": table.id, "table_number": table.table_number, "status": _public_status(status)},
        )


def _public_status(status: str) -> str:
    return {"AVAILABLE": "AVAILABLE", "MAINTENANCE": "MAINTENANCE", "BLOCKED": "UNAVAILABLE", "RESERVED": "RESERVED"}.get(status, "IN_USE")


def recompute_status(db: Session, table: Table, events: PendingEvents | None) -> None:
    """Derive the operational status from the source of truth (sessions + bookings).
    MAINTENANCE / BLOCKED are manual states and are never overridden here."""
    if table.status in (TableStatus.MAINTENANCE, TableStatus.BLOCKED):
        return
    session = db.scalar(select(GameSession).where(GameSession.table_id == table.id, GameSession.status.in_(OPEN_SESSION_STATUSES)))
    if session:
        new = {SessionStatus.ACTIVE: TableStatus.GAME_STARTED, SessionStatus.PAUSED: TableStatus.PAUSED}.get(session.status, TableStatus.OCCUPIED)
        set_status(db, table, new, events)
        return
    branch = db.get(Branch, table.branch_id)
    from app.services.common import branch_settings

    lead = branch_settings(branch).booking.reserve_lead_minutes
    now = utcnow()
    upcoming = db.scalar(
        select(Booking.id).where(
            Booking.table_id == table.id,
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
            Booking.start_at <= now + timedelta(minutes=lead),
            Booking.end_at > now,
        )
    )
    set_status(db, table, TableStatus.RESERVED if upcoming else TableStatus.AVAILABLE, events)


# ----------------------------------------------------------------------------- admin CRUD
def create_table(db: Session, actor: Principal, branch_id: uuid.UUID, data: dict) -> Table:
    branch = get_branch(db, branch_id)
    ensure_branch_access(actor, branch, "tables.manage")
    if db.scalar(select(Table.id).where(Table.branch_id == branch_id, Table.table_number == data["table_number"])):
        raise Conflict("Table number already exists in this branch", code="TABLE_EXISTS")
    gt = db.get(GameType, data["game_type_id"])
    if not gt or gt.organization_id != branch.organization_id:
        raise ValidationFailed("Unknown game type")
    t = Table(branch_id=branch_id, qr_token=secrets.token_urlsafe(12), status=TableStatus.AVAILABLE, **{k: v for k, v in data.items() if k in TABLE_FIELDS and k != "status"})
    if t.hourly_rate is None:
        t.hourly_rate = gt.default_hourly_rate
    db.add(t)
    db.flush()
    audit(db, actor, "table.create", "table", t.id, branch_id=branch_id, after=snapshot(t, TABLE_FIELDS))
    db.commit()
    return t


def update_table(db: Session, actor: Principal, table_id: uuid.UUID, data: dict, reason: str | None = None) -> Table:
    t = get_table(db, table_id)
    branch = get_branch(db, t.branch_id)
    ensure_branch_access(actor, branch, "tables.manage")
    if any(k in data for k in PRICE_FIELDS):
        actor.require("pricing.manage", branch.id)
    before = snapshot(t, TABLE_FIELDS)
    for k, v in data.items():
        if k in TABLE_FIELDS and k != "status":
            setattr(t, k, v)
    action = "table.price_change" if any(k in data and before[k] != str(data[k]) for k in PRICE_FIELDS) else "table.update"
    audit(db, actor, action, "table", t.id, branch_id=branch.id, before=before, after=snapshot(t, TABLE_FIELDS), reason=reason)
    db.commit()
    return t


def set_manual_status(db: Session, actor: Principal, table_id: uuid.UUID, status: TableStatus, reason: str | None) -> Table:
    """Maintenance / blocked / back to service."""
    t = get_table(db, table_id)
    branch = get_branch(db, t.branch_id)
    ensure_branch_access(actor, branch, "tables.manage")
    if status not in (TableStatus.MAINTENANCE, TableStatus.BLOCKED, TableStatus.AVAILABLE):
        raise ValidationFailed("Only MAINTENANCE, BLOCKED or AVAILABLE can be set manually")
    open_session = db.scalar(select(GameSession.id).where(GameSession.table_id == t.id, GameSession.status.in_(OPEN_SESSION_STATUSES)))
    if open_session and status != TableStatus.AVAILABLE:
        raise InvalidState("Stop the running session before taking the table out of service")
    events = PendingEvents()
    before = t.status
    if status == TableStatus.AVAILABLE:
        t.status = TableStatus.AVAILABLE  # leave manual state, then derive
        recompute_status(db, t, events)
        if t.status == before:
            set_status(db, t, TableStatus.AVAILABLE, events)
    else:
        set_status(db, t, status, events, reason=reason)
    audit(db, actor, "table.status", "table", t.id, branch_id=t.branch_id, before={"status": before}, after={"status": t.status}, reason=reason)
    db.commit()
    events.flush()
    return t


def rotate_qr(db: Session, actor: Principal, table_id: uuid.UUID) -> Table:
    t = get_table(db, table_id)
    ensure_branch_access(actor, get_branch(db, t.branch_id), "tables.manage")
    t.qr_token = secrets.token_urlsafe(12)
    audit(db, actor, "table.qr_rotate", "table", t.id, branch_id=t.branch_id)
    db.commit()
    return t


def create_game_type(db: Session, actor: Principal, data: dict) -> GameType:
    actor.require("tables.manage")
    if db.scalar(select(GameType.id).where(GameType.organization_id == actor.organization_id, GameType.code == data["code"].upper())):
        raise Conflict("Game type code already exists")
    gt = GameType(organization_id=actor.organization_id, **{**data, "code": data["code"].upper()})
    db.add(gt)
    db.flush()
    audit(db, actor, "game_type.create", "game_type", gt.id, after=data)
    db.commit()
    return gt


def list_game_types(db: Session, organization_id: uuid.UUID, active_only: bool = True) -> list[GameType]:
    stmt = select(GameType).where(GameType.organization_id == organization_id)
    if active_only:
        stmt = stmt.where(GameType.is_active.is_(True))
    return list(db.scalars(stmt.order_by(GameType.name)).all())


RULE_FIELDS = ["name", "kind", "game_type_id", "table_id", "day_type", "days_of_week", "start_time", "end_time", "valid_from",
               "valid_to", "customer_segment", "rate_per_hour", "rate_multiplier", "priority", "is_active"]


def upsert_pricing_rule(db: Session, actor: Principal, branch_id: uuid.UUID, data: dict, rule_id: uuid.UUID | None = None) -> PricingRule:
    branch = get_branch(db, branch_id)
    ensure_branch_access(actor, branch, "pricing.manage")
    if data.get("rate_per_hour") is None and data.get("rate_multiplier") is None and rule_id is None:
        raise ValidationFailed("Provide rate_per_hour or rate_multiplier")
    if rule_id:
        rule = db.get(PricingRule, rule_id)
        if not rule or rule.branch_id != branch_id:
            raise NotFound("Pricing rule not found")
        before = snapshot(rule, RULE_FIELDS)
        for k, v in data.items():
            if k in RULE_FIELDS:
                setattr(rule, k, v)
        audit(db, actor, "pricing_rule.update", "pricing_rule", rule.id, branch_id=branch_id, before=before, after=snapshot(rule, RULE_FIELDS))
    else:
        rule = PricingRule(branch_id=branch_id, **{k: v for k, v in data.items() if k in RULE_FIELDS})
        db.add(rule)
        db.flush()
        audit(db, actor, "pricing_rule.create", "pricing_rule", rule.id, branch_id=branch_id, after=snapshot(rule, RULE_FIELDS))
    db.commit()
    return rule


def list_pricing_rules(db: Session, branch_id: uuid.UUID) -> list[PricingRule]:
    return list(db.scalars(select(PricingRule).where(PricingRule.branch_id == branch_id).order_by(PricingRule.priority.desc(), PricingRule.name)).all())


# ----------------------------------------------------------------------------- board
def status_board(db: Session, branch_id: uuid.UUID) -> list[dict]:
    """Everything the receptionist needs per table in ONE round-trip (no N+1)."""
    tables = list_tables(db, branch_id, include_inactive=False)
    ids = [t.id for t in tables]
    now = utcnow()
    sessions = {s.table_id: s for s in db.scalars(select(GameSession).where(GameSession.table_id.in_(ids), GameSession.status.in_(OPEN_SESSION_STATUSES))).unique().all()} if ids else {}
    upcoming: dict = {}
    if ids:
        for b in db.scalars(
            select(Booking).where(
                Booking.table_id.in_(ids), Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN, BookingStatus.HELD]),
                Booking.end_at > now, Booking.start_at < now + timedelta(hours=24),
            ).order_by(Booking.start_at)
        ).unique().all():
            upcoming.setdefault(b.table_id, b)
    devices: dict = {}
    if ids:
        for d in db.scalars(select(Device).where(Device.table_id.in_(ids))).unique().all():
            devices.setdefault(d.table_id, []).append({"device_id": d.device_id, "type": d.device_type, "status": d.status, "last_seen_at": d.last_seen_at})
    out = []
    for t in tables:
        s = sessions.get(t.id)
        b = upcoming.get(t.id)
        elapsed = None
        if s and s.started_at:
            ref = s.paused_at or now
            elapsed = int((ref - s.started_at).total_seconds()) - (s.total_paused_seconds or 0)
        out.append({
            "table": t,
            "session": s,
            "elapsed_seconds": elapsed,
            "next_booking": b,
            "devices": devices.get(t.id, []),
        })
    return out


def next_blocking_start(db: Session, table_id: uuid.UUID, after: datetime) -> datetime | None:
    return db.scalar(
        select(Booking.start_at).where(
            and_(Booking.table_id == table_id, Booking.status.in_(BLOCKING_BOOKING_STATUSES), Booking.start_at >= after)
        ).order_by(Booking.start_at).limit(1)
    )


def local_day_bounds(branch: Branch, day: date) -> tuple[datetime, datetime]:
    """Business day in UTC: opening_time local on `day` → closing_time (may be next day)."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(branch.timezone)
    oh, om = map(int, branch.opening_time.split(":"))
    ch, cm = map(int, branch.closing_time.split(":"))
    start = datetime(day.year, day.month, day.day, oh, om, tzinfo=tz)
    end = datetime(day.year, day.month, day.day, ch, cm, tzinfo=tz)
    if end <= start:
        end += timedelta(days=1)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))

