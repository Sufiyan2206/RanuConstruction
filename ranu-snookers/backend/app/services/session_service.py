"""Game sessions: the state machine that drives table billing.

    CREATED(READY) --start--> ACTIVE --pause--> PAUSED --resume--> ACTIVE
          |                     |                  |
          +--cancel--> CANCELLED +--stop--> COMPLETED <--stop--+
                                +--auto_close--> AUTO_CLOSED

Invalid transitions raise 409 INVALID_STATE_TRANSITION. Every transition is
written to `session_events` and `audit_logs` in the same DB transaction.

"Only one open session per table" is guaranteed by
  (1) a row lock on the table during start, and
  (2) the UNIQUE `game_sessions.active_table_key` column (DB-level backstop),
so Receptionist A, Receptionist B and a sensor starting Table 5 at the same
moment produce exactly one session.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import for_update
from app.core.deps import Principal
from app.core.errors import Conflict, InvalidState, NotFound, ValidationFailed
from app.core.realtime import PendingEvents
from app.core.timeutil import ensure_utc, utcnow
from app.models import Booking, Branch, GameSession, Invoice, Membership, SessionEvent, SessionPause, Table
from app.models.enums import (
    OPEN_SESSION_STATUSES,
    AlertSeverity,
    BillingStatus,
    BookingStatus,
    DetectionMethod,
    SessionStatus,
    TableStatus,
)
from app.services import table_service
from app.services.audit import audit, raise_alert
from app.services.common import branch_settings

TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.ACTIVE, SessionStatus.CANCELLED},
    SessionStatus.ACTIVE: {SessionStatus.PAUSED, SessionStatus.COMPLETED, SessionStatus.AUTO_CLOSED, SessionStatus.CANCELLED},
    SessionStatus.PAUSED: {SessionStatus.ACTIVE, SessionStatus.COMPLETED, SessionStatus.AUTO_CLOSED, SessionStatus.CANCELLED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.CANCELLED: set(),
    SessionStatus.AUTO_CLOSED: set(),
}


def assert_transition(current: str, target: SessionStatus) -> None:
    if target not in TRANSITIONS[SessionStatus(current)]:
        raise InvalidState(f"Cannot move session from {current} to {target}")


def _event(db: Session, s: GameSession, event_type: str, frm: str | None, to: str | None, actor: Principal | None, source: str, payload: dict | None = None) -> None:
    db.add(SessionEvent(session_id=s.id, event_type=event_type, from_status=frm, to_status=to, source=source,
                        actor_id=actor.id if actor else None, payload=payload or {}, created_at=utcnow()))


def _publish(events: PendingEvents, s: GameSession, kind: str) -> None:
    events.add(s.branch_id, f"session.{kind}", {
        "session_id": s.id, "table_id": s.table_id, "status": s.status, "started_at": s.started_at, "customer_id": s.customer_id,
        "planned_end_at": s.planned_end_at, "detection_method": s.detection_method,
    })


def get_session(db: Session, session_id: uuid.UUID, *, lock: bool = False) -> GameSession:
    stmt = select(GameSession).where(GameSession.id == session_id)
    s = db.scalar(for_update(stmt, db) if lock else stmt)
    if not s:
        raise NotFound("Session not found")
    return s


def open_session_for_table(db: Session, table_id: uuid.UUID) -> GameSession | None:
    return db.scalar(select(GameSession).where(GameSession.table_id == table_id, GameSession.status.in_(OPEN_SESSION_STATUSES)))


def _pick_membership(db: Session, customer_id: uuid.UUID | None, table: Table) -> Membership | None:
    if not customer_id:
        return None
    today = utcnow().date()
    for m in db.scalars(select(Membership).where(Membership.customer_id == customer_id, Membership.status == "ACTIVE",
                                                 Membership.starts_on <= today, Membership.expires_on >= today).order_by(Membership.expires_on)).unique().all():
        ids = m.plan.game_type_ids
        if ids is None or str(table.game_type_id) in [str(x) for x in ids]:
            return m
    return None


# ------------------------------------------------------------------------------ create/start
def create_ready_session(db: Session, actor: Principal | None, table: Table, *, booking: Booking | None, events: PendingEvents,
                         customer_id: uuid.UUID | None = None) -> GameSession:
    cust = booking.customer_id if booking else customer_id
    m = _pick_membership(db, cust, table)
    s = GameSession(
        branch_id=table.branch_id, table_id=table.id, booking_id=booking.id if booking else None, customer_id=cust,
        membership_id=m.id if m else None, active_table_key=str(table.id), status=SessionStatus.CREATED,
        billing_status=BillingStatus.NOT_STARTED, planned_end_at=booking.end_at if booking else None,
        detection_method=DetectionMethod.BOOKING if booking else DetectionMethod.MANUAL,
    )
    db.add(s)
    db.flush()
    _event(db, s, "created", None, s.status, actor, "BOOKING" if booking else "MANUAL")
    table_service.set_status(db, table, TableStatus.OCCUPIED, events)
    _publish(events, s, "ready")
    return s


def start(
    db: Session,
    actor: Principal | None,
    table_id: uuid.UUID,
    *,
    method: DetectionMethod = DetectionMethod.MANUAL,
    customer_id: uuid.UUID | None = None,
    booking_id: uuid.UUID | None = None,
    planned_minutes: int | None = None,
    confidence: float | None = None,
    player_count: int = 2,
    override_reservation: bool = False,
    source_detail: dict | None = None,
    events: PendingEvents | None = None,
    commit: bool = True,
) -> tuple[GameSession, bool]:
    """Start billing on a table. Returns (session, created_now).

    Idempotent for automatic detection: if the table already has an ACTIVE
    session, that session is returned unchanged (duplicate sensor/QR events
    never create a second session)."""
    own = events is None
    events = events or PendingEvents()
    if actor is not None:
        actor.require("sessions.operate", _table_branch(db, table_id))
    try:
        table = db.scalar(for_update(select(Table).where(Table.id == table_id, Table.deleted_at.is_(None)), db))
        if not table:
            raise NotFound("Table not found")
        if table.status in (TableStatus.MAINTENANCE, TableStatus.BLOCKED):
            raise Conflict(f"Table {table.table_number} is {table.status.lower()}", code="TABLE_UNAVAILABLE")
        now = utcnow()
        existing = open_session_for_table(db, table.id)
        if existing and existing.status in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
            if method != DetectionMethod.MANUAL:
                return existing, False
            raise Conflict(f"Table {table.table_number} already has a running session", code="SESSION_ALREADY_ACTIVE")

        booking = None
        if booking_id:
            booking = db.get(Booking, booking_id)
            if not booking or booking.table_id != table.id:
                raise ValidationFailed("Booking does not belong to this table")
        elif existing and existing.booking_id:
            booking = db.get(Booking, existing.booking_id)
        if booking is None and not existing:
            # Walk-in: never silently steal a reserved slot.
            booking = _current_booking(db, table.id, now)
            if booking and booking.customer_id != customer_id and method == DetectionMethod.MANUAL and not override_reservation:
                raise Conflict(
                    f"Table {table.table_number} is reserved ({booking.reference}) at this time. Check in the booking or override.",
                    code="TABLE_RESERVED", details={"booking_id": str(booking.id), "reference": booking.reference},
                )
            if booking and booking.customer_id != customer_id:
                booking = None

        s = existing
        if s is None:
            s = create_ready_session(db, actor, table, booking=booking, events=events, customer_id=customer_id)
        if customer_id and not s.customer_id:
            s.customer_id = customer_id
            m = _pick_membership(db, customer_id, table)
            s.membership_id = m.id if m else None
        assert_transition(s.status, SessionStatus.ACTIVE)
        frm = s.status
        s.status = SessionStatus.ACTIVE
        s.billing_status = BillingStatus.RUNNING
        s.started_at = now
        s.last_activity_at = now
        s.detection_method = method
        s.confidence_score = confidence
        s.player_count = player_count
        s.started_by_id = actor.id if actor else None
        if planned_minutes:
            s.planned_end_at = now + timedelta(minutes=planned_minutes)
        elif booking and not s.planned_end_at:
            s.planned_end_at = booking.end_at
        if booking:
            s.booking_id = booking.id
            if booking.status in (BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN):
                booking.status = BookingStatus.IN_PROGRESS
                booking.checked_in_at = booking.checked_in_at or now
        db.flush()
        _event(db, s, "started", frm, s.status, actor, method, {"confidence": confidence, **(source_detail or {})})
        audit(db, actor, "session.start" if method == DetectionMethod.MANUAL else "session.auto_start", "game_session", s.id,
              branch_id=s.branch_id, after={"table": table.table_number, "method": method, "confidence": confidence, "customer_id": s.customer_id})
        if not s.customer_id:
            raise_alert(db, s.branch_id, "SESSION_WITHOUT_CUSTOMER", f"Table {table.table_number} started without a customer",
                        severity=AlertSeverity.INFO, table_id=table.id, session_id=s.id, dedupe_key=f"nocust:{s.id}", events=events)
        table_service.set_status(db, table, TableStatus.GAME_STARTED, events)
        _publish(events, s, "started")
        from app.services import notification_service

        notification_service.enqueue_for_session(db, s, "session.started")
        if commit:
            db.commit()
    except IntegrityError as e:
        db.rollback()
        raise Conflict("Another session was started on this table at the same moment", code="SESSION_ALREADY_ACTIVE") from e
    except Exception:
        if commit:
            db.rollback()
        raise
    if commit and own:
        events.flush()
    return s, True


def _table_branch(db: Session, table_id: uuid.UUID):
    t = db.get(Table, table_id)
    if not t:
        raise NotFound("Table not found")
    return t.branch_id


def _current_booking(db: Session, table_id: uuid.UUID, now: datetime) -> Booking | None:
    return db.scalar(select(Booking).where(
        Booking.table_id == table_id, Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
        Booking.start_at <= now + timedelta(minutes=30), Booking.end_at > now,
    ).order_by(Booking.start_at))


# ------------------------------------------------------------------------------ pause/resume
def pause(db: Session, actor: Principal, session_id: uuid.UUID, reason: str | None = None) -> GameSession:
    events = PendingEvents()
    s = get_session(db, session_id, lock=True)
    actor.require("sessions.operate", s.branch_id)
    assert_transition(s.status, SessionStatus.PAUSED)
    now = utcnow()
    s.status, s.billing_status, s.paused_at = SessionStatus.PAUSED, BillingStatus.PAUSED, now
    db.add(SessionPause(session_id=s.id, paused_at=now, reason=reason, paused_by_id=actor.id))
    _event(db, s, "paused", SessionStatus.ACTIVE, s.status, actor, "MANUAL", {"reason": reason})
    audit(db, actor, "session.pause", "game_session", s.id, branch_id=s.branch_id, reason=reason)
    table_service.set_status(db, db.get(Table, s.table_id), TableStatus.PAUSED, events)
    _publish(events, s, "paused")
    db.commit()
    events.flush()
    return s


def resume(db: Session, actor: Principal, session_id: uuid.UUID) -> GameSession:
    events = PendingEvents()
    s = get_session(db, session_id, lock=True)
    actor.require("sessions.operate", s.branch_id)
    if s.status != SessionStatus.PAUSED:
        raise InvalidState("Session is not paused")
    _close_pause(db, s, utcnow())
    s.status, s.billing_status = SessionStatus.ACTIVE, BillingStatus.RUNNING
    _event(db, s, "resumed", SessionStatus.PAUSED, s.status, actor, "MANUAL")
    audit(db, actor, "session.resume", "game_session", s.id, branch_id=s.branch_id)
    table_service.set_status(db, db.get(Table, s.table_id), TableStatus.GAME_STARTED, events)
    _publish(events, s, "resumed")
    db.commit()
    events.flush()
    return s


def _close_pause(db: Session, s: GameSession, at: datetime) -> None:
    p = db.scalar(select(SessionPause).where(SessionPause.session_id == s.id, SessionPause.resumed_at.is_(None)))
    if p:
        p.resumed_at = at
        s.total_paused_seconds += int((at - p.paused_at).total_seconds())
    s.paused_at = None


# ------------------------------------------------------------------------------ extension
def extend(db: Session, actor: Principal, session_id: uuid.UUID, minutes: int) -> GameSession:
    """'+30 minutes': allowed only if no other booking starts in the extended window."""
    if minutes <= 0 or minutes > 240:
        raise ValidationFailed("Extension must be between 1 and 240 minutes")
    events = PendingEvents()
    s = get_session(db, session_id, lock=True)
    actor.require("sessions.operate", s.branch_id)
    if s.status not in (SessionStatus.ACTIVE, SessionStatus.PAUSED, SessionStatus.CREATED):
        raise InvalidState("Only open sessions can be extended")
    table = db.scalar(for_update(select(Table).where(Table.id == s.table_id), db))
    base = s.planned_end_at or utcnow()
    new_end = base + timedelta(minutes=minutes)
    pol = branch_settings(db.get(Branch, s.branch_id)).booking
    clash = db.scalar(select(Booking).where(
        Booking.table_id == table.id, Booking.status.in_([BookingStatus.HELD, BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
        Booking.id != (s.booking_id or uuid.uuid4()), Booking.start_at < new_end + timedelta(minutes=pol.buffer_minutes), Booking.end_at > base,
    ).order_by(Booking.start_at))
    if clash and not (clash.status == BookingStatus.HELD and clash.hold_expires_at and clash.hold_expires_at < utcnow()):
        raise Conflict(f"Extension unavailable: table is booked from {clash.start_at.isoformat()}", code="EXTENSION_UNAVAILABLE",
                       details={"next_booking_start": clash.start_at.isoformat()})
    before = s.planned_end_at
    s.planned_end_at = new_end
    if s.booking_id:
        b = db.get(Booking, s.booking_id)
        if b and b.end_at < new_end:
            b.end_at = new_end
            b.duration_minutes = int((b.end_at - b.start_at).total_seconds() // 60)
    _event(db, s, "extended", s.status, s.status, actor, "MANUAL", {"minutes": minutes})
    audit(db, actor, "session.extend", "game_session", s.id, branch_id=s.branch_id, before={"planned_end_at": before}, after={"planned_end_at": new_end})
    _publish(events, s, "extended")
    events.add(s.branch_id, "availability.changed", {"table_id": s.table_id}, public={"table_id": s.table_id})
    db.commit()
    events.flush()
    return s


# ------------------------------------------------------------------------------ stop
def stop(db: Session, actor: Principal | None, session_id: uuid.UUID, *, status: SessionStatus = SessionStatus.COMPLETED,
         ended_at: datetime | None = None, reason: str | None = None, events: PendingEvents | None = None, commit: bool = True) -> tuple[GameSession, Invoice]:
    """End the game, freeze the clock and generate the final invoice atomically."""
    own = events is None
    events = events or PendingEvents()
    s = get_session(db, session_id, lock=True)
    if actor is not None:
        actor.require("sessions.operate", s.branch_id)
    if s.status == SessionStatus.CREATED:
        raise InvalidState("Session never started; cancel it instead")
    assert_transition(s.status, status)
    end = ensure_utc(ended_at) if ended_at else utcnow()
    if s.status == SessionStatus.PAUSED:
        _close_pause(db, s, min(end, utcnow()))
    frm = s.status
    s.status = status
    s.ended_at = end
    s.ended_by_id = actor.id if actor else None
    s.active_table_key = None
    s.billing_status = BillingStatus.STOPPED
    s.duration_seconds = billable_seconds(s, end)
    _event(db, s, "stopped" if status == SessionStatus.COMPLETED else "auto_closed", frm, s.status, actor, "MANUAL" if actor else "SYSTEM", {"reason": reason})
    audit(db, actor, "session.stop" if actor else "session.auto_close", "game_session", s.id, branch_id=s.branch_id,
          after={"ended_at": end, "duration_seconds": s.duration_seconds}, reason=reason)
    if s.booking_id:
        b = db.get(Booking, s.booking_id)
        if b and b.status in (BookingStatus.IN_PROGRESS, BookingStatus.CHECKED_IN, BookingStatus.CONFIRMED):
            b.status = BookingStatus.COMPLETED
    from app.services import billing_service, detection_service

    invoice = billing_service.generate_for_session(db, actor, s, events)
    s.billing_status = BillingStatus.INVOICED
    detection_service.reset_state(db, s.table_id)
    table = db.get(Table, s.table_id)
    table_service.recompute_status(db, table, events)
    _publish(events, s, "stopped")
    events.add(s.branch_id, "availability.changed", {"table_id": s.table_id}, public={"table_id": s.table_id})
    if commit:
        db.commit()
        if own:
            events.flush()
    return s, invoice


def cancel(db: Session, actor: Principal, session_id: uuid.UUID, reason: str) -> GameSession:
    """Cancel without charge (wrong table started, customer left immediately).
    Cancelling a running session requires sessions.adjust and is alerted."""
    events = PendingEvents()
    s = get_session(db, session_id, lock=True)
    actor.require("sessions.operate", s.branch_id)
    if s.status in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
        actor.require("sessions.adjust", s.branch_id)
        raise_alert(db, s.branch_id, "SESSION_CANCELLED_WHILE_RUNNING", f"Running session on table cancelled by {actor.user.username}: {reason}",
                    table_id=s.table_id, session_id=s.id, events=events)
    assert_transition(s.status, SessionStatus.CANCELLED)
    frm = s.status
    s.status = SessionStatus.CANCELLED
    s.ended_at = utcnow()
    s.active_table_key = None
    s.billing_status = BillingStatus.STOPPED
    if s.booking_id:
        b = db.get(Booking, s.booking_id)
        if b and b.status == BookingStatus.IN_PROGRESS:
            b.status = BookingStatus.CHECKED_IN
    _event(db, s, "cancelled", frm, s.status, actor, "MANUAL", {"reason": reason})
    audit(db, actor, "session.cancel", "game_session", s.id, branch_id=s.branch_id, before={"status": frm}, after={"status": s.status}, reason=reason)
    from app.services import detection_service

    detection_service.reset_state(db, s.table_id)
    table_service.recompute_status(db, db.get(Table, s.table_id), events)
    _publish(events, s, "cancelled")
    db.commit()
    events.flush()
    return s


def adjust_times(db: Session, actor: Principal, session_id: uuid.UUID, *, started_at: datetime | None, reason: str) -> GameSession:
    """Correct the start time of an OPEN session (e.g. staff forgot to press start).
    Closed sessions are corrected through invoice adjustments instead."""
    s = get_session(db, session_id, lock=True)
    actor.require("sessions.adjust", s.branch_id)
    if s.status not in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
        raise InvalidState("Only running sessions can be time-adjusted; use an invoice adjustment for closed sessions")
    if not reason or len(reason) < 3:
        raise ValidationFailed("A reason is required")
    if started_at:
        started_at = ensure_utc(started_at)
        if started_at > utcnow():
            raise ValidationFailed("Start time cannot be in the future")
        before = s.started_at
        s.started_at = started_at
        _event(db, s, "adjusted", s.status, s.status, actor, "MANUAL", {"started_at_before": str(before), "started_at_after": str(started_at)})
        audit(db, actor, "session.adjust", "game_session", s.id, branch_id=s.branch_id, before={"started_at": before}, after={"started_at": started_at}, reason=reason)
    db.commit()
    return s


# ------------------------------------------------------------------------------ helpers
def active_intervals(s: GameSession, until: datetime | None = None) -> list[tuple[datetime, datetime]]:
    if not s.started_at:
        return []
    end = ensure_utc(until or s.ended_at or utcnow())
    cursor = s.started_at
    out: list[tuple[datetime, datetime]] = []
    for p in sorted(s.pauses, key=lambda x: x.paused_at):
        if p.paused_at >= end:
            break
        if p.paused_at > cursor:
            out.append((cursor, p.paused_at))
        cursor = max(cursor, p.resumed_at or end)
    if cursor < end:
        out.append((cursor, end))
    return out


def billable_seconds(s: GameSession, until: datetime | None = None) -> int:
    return int(sum((e - st).total_seconds() for st, e in active_intervals(s, until)))


def list_open_sessions(db: Session, branch_id: uuid.UUID) -> list[GameSession]:
    return list(db.scalars(select(GameSession).where(GameSession.branch_id == branch_id, GameSession.status.in_(OPEN_SESSION_STATUSES))
                           .order_by(GameSession.started_at)).unique().all())


def recover_on_startup(db: Session) -> int:
    """Server restart: sessions are persisted, so nothing is lost. We just make
    sure every table's status matches the open sessions again."""
    n = 0
    events = PendingEvents()
    for t in db.scalars(select(Table).where(Table.deleted_at.is_(None))).unique().all():
        before = t.status
        table_service.recompute_status(db, t, events)
        n += int(before != t.status)
    db.commit()
    return n
