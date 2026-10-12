"""Table Activity Detection Service — the hybrid detection engine.

    device event ─► provider.interpret() ─► Signal ─► process_signal()
                                                        │
                    IDLE ─► ACTIVITY_DETECTED ─► CONFIRMING ─► GAME_STARTED ─► session_service.start()

Business rule (spec §52): a single movement NEVER starts billing. Activity is
confirmed only when ALL of these hold:
  * fused confidence  >= detection.confirmation_threshold
  * activity sustained >= detection.min_activity_seconds
  * at least detection.min_activity_events activity signals
  * (if detection.require_identification) a customer was identified recently
    (card tap / QR) or a booking is checked in at the table.

Fused confidence combines *different* signal sources, so one noisy motion
sensor firing 50 times cannot reach the threshold on its own:

    score = 1 − Π_source (1 − weight_source × best_confidence_source)

Explicit intent (QR confirm, card tap, start button) starts the session
immediately when enabled — that is a customer action, not an inference.
Staff START / STOP / ADJUST always remain available as manual fallback.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import for_update
from app.core.realtime import PendingEvents
from app.core.timeutil import ensure_utc, utcnow
from app.devices.providers.base import Signal, SignalKind
from app.models import Booking, Branch, Customer, Device, GameSession, Table, TableDetectionState
from app.models.enums import OPEN_SESSION_STATUSES, AlertSeverity, BookingStatus, DetectionMethod, DetectionState, SessionStatus
from app.schemas.settings import DetectionSettings
from app.services.audit import raise_alert
from app.services.common import branch_settings


# ============================================================================ pure fusion logic
@dataclass
class FusionResult:
    score: float
    sources: list[str]
    sustained_seconds: float
    activity_events: int
    identified: bool
    confirmed: bool
    reason: str


def fuse(signals: list[dict], cfg: DetectionSettings, now: datetime, *, identified: bool, booking_checked_in: bool,
         first_activity_at: datetime | None, activity_events: int) -> FusionResult:
    """Pure function (unit-tested): decide whether recent signals confirm a game."""
    window_start = now - timedelta(seconds=cfg.signal_window_seconds)
    best: dict[str, float] = {}
    for s in signals:
        at = ensure_utc(datetime.fromisoformat(s["at"]))
        if at < window_start:
            continue
        src = s["source"]
        c = float(s["confidence"])
        if src == "CAMERA" and c < cfg.camera_confidence_threshold:
            continue
        best[src] = max(best.get(src, 0.0), c)
    if identified:
        best["IDENTIFIED"] = max(best.get("IDENTIFIED", 0.0), 1.0)
    if booking_checked_in:
        best["BOOKING_CHECKIN"] = 1.0
    prod = 1.0
    for src, c in best.items():
        w = cfg.weights.get(src, cfg.weights.get("RFID", 0.7) if src == "IDENTIFIED" else 0.3)
        prod *= 1.0 - max(0.0, min(1.0, w * c))
    score = round(1.0 - prod, 4)
    activity_sources = [s for s in best if s not in ("IDENTIFIED", "BOOKING_CHECKIN")]
    sustained = (now - first_activity_at).total_seconds() if first_activity_at else 0.0
    reasons = []
    if not activity_sources:
        reasons.append("no activity signal")
    if score < cfg.confirmation_threshold:
        reasons.append(f"confidence {score:.2f} < {cfg.confirmation_threshold}")
    if sustained < cfg.min_activity_seconds:
        reasons.append(f"sustained {int(sustained)}s < {cfg.min_activity_seconds}s")
    if activity_events < cfg.min_activity_events:
        reasons.append(f"{activity_events} events < {cfg.min_activity_events}")
    if cfg.require_identification and not (identified or booking_checked_in):
        reasons.append("no customer identification")
    return FusionResult(score, sorted(best), sustained, activity_events, identified, not reasons, "; ".join(reasons) or "confirmed")


# ============================================================================ state persistence
def _state(db: Session, table_id: uuid.UUID) -> TableDetectionState:
    st = db.scalar(for_update(select(TableDetectionState).where(TableDetectionState.table_id == table_id), db))
    if st is None:
        st = TableDetectionState(table_id=table_id, state=DetectionState.IDLE, signals=[], updated_at=utcnow())
        db.add(st)
        db.flush()
    return st


def reset_state(db: Session, table_id: uuid.UUID) -> None:
    st = db.scalar(select(TableDetectionState).where(TableDetectionState.table_id == table_id))
    if st:
        st.state, st.score, st.first_activity_at, st.last_activity_at = DetectionState.IDLE, 0.0, None, None
        st.activity_events, st.signals = 0, []
        st.identified_customer_id = st.identified_membership_id = st.identified_at = None
        st.updated_at = utcnow()


def _method_for(sources: list[str]) -> DetectionMethod:
    physical = [s for s in sources if s in ("MOTION", "PRESSURE", "IR", "VIBRATION", "CONTROLLER")]
    has_cam = "CAMERA" in sources
    has_card = "IDENTIFIED" in sources
    kinds = int(bool(physical)) + int(has_cam) + int(has_card)
    if kinds > 1:
        return DetectionMethod.HYBRID
    if has_cam:
        return DetectionMethod.CAMERA
    return DetectionMethod.SENSOR


# ============================================================================ main entry
def process_signal(db: Session, table: Table, sig: Signal, *, device: Device | None, events: PendingEvents) -> dict:
    """Apply one normalised signal to a table. Must be called inside a transaction;
    the table's detection-state row is locked so concurrent events serialise."""
    branch = db.get(Branch, table.branch_id)
    cfg = branch_settings(branch).detection
    now = utcnow()
    occurred = ensure_utc(sig.occurred_at) if sig.occurred_at else now

    # ---- anti-fraud: stale / future-dated events ---------------------------------
    if occurred < now - timedelta(seconds=cfg.reject_events_older_than_seconds):
        raise_alert(db, branch.id, "STALE_DEVICE_EVENT", f"Ignored stale event from {device.device_id if device else 'device'} ({occurred.isoformat()})",
                    severity=AlertSeverity.INFO, table_id=table.id, device_pk=device.id if device else None,
                    dedupe_key=f"stale:{device.id if device else table.id}", events=events)
        return {"outcome": "IGNORED_STALE"}
    if occurred > now + timedelta(seconds=cfg.clock_skew_tolerance_seconds):
        raise_alert(db, branch.id, "DEVICE_CLOCK_SKEW", f"Device clock ahead by {int((occurred-now).total_seconds())}s — using server time",
                    table_id=table.id, device_pk=device.id if device else None, dedupe_key=f"skew:{device.id if device else table.id}", events=events)
        occurred = now

    st = _state(db, table.id)
    window_start = now - timedelta(seconds=cfg.signal_window_seconds)
    st.signals = [s for s in (st.signals or []) if ensure_utc(datetime.fromisoformat(s["at"])) >= window_start]
    session = db.scalar(select(GameSession).where(GameSession.table_id == table.id, GameSession.status.in_(OPEN_SESSION_STATUSES)))

    if sig.kind == SignalKind.IGNORE:
        return {"outcome": "IGNORED", "detail": sig.detail}

    # ---- identification (card / QR) ------------------------------------------
    customer_id = None
    membership_id = None
    if sig.card_uid:
        from app.services import membership_service

        m = membership_service.find_by_card(db, sig.card_uid)
        if m and m.status == "ACTIVE":
            customer_id, membership_id = m.customer_id, m.id
        else:
            raise_alert(db, branch.id, "UNKNOWN_CARD", f"Unknown or inactive card {sig.card_uid} tapped at table {table.table_number}",
                        severity=AlertSeverity.INFO, table_id=table.id, dedupe_key=f"card:{sig.card_uid}:{table.id}", events=events)
    elif sig.customer_phone:
        from app.services.customer_service import normalize_phone

        c = db.scalar(select(Customer).where(Customer.organization_id == branch.organization_id, Customer.phone == normalize_phone(sig.customer_phone)))
        customer_id = c.id if c else None
    if customer_id:
        st.identified_customer_id, st.identified_membership_id, st.identified_at = customer_id, membership_id, now

    # ---- a session is already running: keep it alive / attach customer -------
    if session and session.status in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
        if sig.kind in (SignalKind.ACTIVITY, SignalKind.INTENT):
            session.last_activity_at = occurred
        if customer_id and not session.customer_id:
            session.customer_id = customer_id
            session.membership_id = membership_id
        if sig.kind == SignalKind.STOP_REQUEST:
            raise_alert(db, branch.id, "STOP_REQUESTED", f"Table {table.table_number}: customer pressed STOP — please close the bill",
                        severity=AlertSeverity.INFO, table_id=table.id, session_id=session.id, dedupe_key=f"stopreq:{session.id}", events=events)
            return {"outcome": "STOP_REQUEST_FORWARDED", "session_id": str(session.id)}
        st.state = DetectionState.GAME_STARTED
        st.updated_at = now
        return {"outcome": "SESSION_ALREADY_ACTIVE", "session_id": str(session.id)}

    if sig.kind == SignalKind.IDLE:
        if st.state in (DetectionState.ACTIVITY_DETECTED, DetectionState.CONFIRMING) and not st.signals:
            reset_state(db, table.id)
        return {"outcome": "IDLE_NOTED"}

    identified_recent = bool(st.identified_at and ensure_utc(st.identified_at) >= now - timedelta(seconds=cfg.identification_valid_seconds))
    booking = db.scalar(select(Booking).where(Booking.table_id == table.id, Booking.status == BookingStatus.CHECKED_IN, Booking.end_at > now))
    ready_session = session if session and session.status == SessionStatus.CREATED else None
    booking_checked_in = bool(booking or ready_session)

    # ---- explicit intent (card tap / QR confirm / start button) ---------------
    if sig.kind == SignalKind.INTENT:
        allowed = cfg.auto_start_enabled and (
            (sig.source in ("RFID", "NFC") and cfg.rfid_starts_session and customer_id)
            or (sig.source == "QR" and cfg.qr_starts_session)
            or (sig.source == "CONTROLLER")
        )
        if allowed:
            return _start(db, table, st, events, method=_intent_method(sig.source), confidence=1.0, customer_id=customer_id or st.identified_customer_id,
                          detail={"source": sig.source, "card_uid": sig.card_uid})
        raise_alert(db, branch.id, "START_REQUESTED", f"Table {table.table_number}: start requested via {sig.source} — confirm at the counter",
                    severity=AlertSeverity.INFO, table_id=table.id, dedupe_key=f"startreq:{table.id}", events=events)
        return {"outcome": "AWAITING_STAFF_CONFIRMATION"}

    # ---- activity: accumulate & fuse -----------------------------------------
    st.signals = (st.signals or []) + [{"source": sig.source, "confidence": round(float(sig.confidence), 3), "at": occurred.isoformat()}]
    st.signals = st.signals[-50:]
    if st.state == DetectionState.IDLE or st.first_activity_at is None:
        st.state = DetectionState.ACTIVITY_DETECTED
        st.first_activity_at = occurred
        st.activity_events = 0
    st.activity_events += 1
    st.last_activity_at = occurred
    res = fuse(st.signals, cfg, now, identified=identified_recent, booking_checked_in=booking_checked_in,
               first_activity_at=ensure_utc(st.first_activity_at), activity_events=st.activity_events)
    st.score = res.score
    st.updated_at = now
    events.add(branch.id, "detection.updated", {"table_id": table.id, "state": st.state, "score": res.score, "sources": res.sources, "reason": res.reason})
    if not res.confirmed:
        if st.state == DetectionState.ACTIVITY_DETECTED and res.score >= cfg.confirmation_threshold * 0.5:
            st.state = DetectionState.CONFIRMING
        return {"outcome": "ACTIVITY_RECORDED", "state": st.state, "score": res.score, "reason": res.reason}
    if not cfg.auto_start_enabled:
        st.state = DetectionState.CONFIRMING
        raise_alert(db, branch.id, "GAME_ACTIVITY_CONFIRMED", f"Table {table.table_number}: game activity detected (confidence {res.score:.0%}). Start the session?",
                    severity=AlertSeverity.INFO, table_id=table.id, dedupe_key=f"gac:{table.id}", data={"score": res.score, "sources": res.sources}, events=events)
        return {"outcome": "GAME_ACTIVITY_CONFIRMED_AWAITING_STAFF", "score": res.score}
    cust = st.identified_customer_id if identified_recent else (booking.customer_id if booking else (ready_session.customer_id if ready_session else None))
    return _start(db, table, st, events, method=_method_for(res.sources), confidence=res.score, customer_id=cust,
                  detail={"sources": res.sources, "sustained_seconds": int(res.sustained_seconds), "events": res.activity_events})


def _intent_method(source: str) -> DetectionMethod:
    return {"RFID": DetectionMethod.RFID, "NFC": DetectionMethod.NFC, "QR": DetectionMethod.QR}.get(source, DetectionMethod.SENSOR)


def _start(db: Session, table: Table, st: TableDetectionState, events: PendingEvents, *, method: DetectionMethod, confidence: float,
           customer_id, detail: dict) -> dict:
    from app.services import session_service

    booking = db.scalar(select(Booking).where(Booking.table_id == table.id, Booking.status == BookingStatus.CHECKED_IN, Booking.end_at > utcnow()))
    try:
        s, created = session_service.start(db, None, table.id, method=method, customer_id=customer_id, booking_id=booking.id if booking else None,
                                           confidence=confidence, override_reservation=False, source_detail=detail, events=events, commit=False)
    except Exception as e:  # e.g. table reserved for someone else -> alert staff instead of billing wrongly
        raise_alert(db, table.branch_id, "AUTO_START_BLOCKED", f"Table {table.table_number}: automatic start blocked — {getattr(e, 'message', str(e))}",
                    table_id=table.id, dedupe_key=f"autoblock:{table.id}", events=events)
        return {"outcome": "AUTO_START_BLOCKED", "reason": getattr(e, "message", str(e))}
    st.state = DetectionState.GAME_STARTED
    return {"outcome": "SESSION_STARTED" if created else "SESSION_ALREADY_ACTIVE", "session_id": str(s.id), "method": method, "confidence": confidence}


# ============================================================================ monitoring (worker)
def monitor_sessions(db: Session) -> int:
    """Inactivity + excessive-duration alerts; optional auto-close."""
    from app.services import session_service

    now = utcnow()
    n = 0
    sensor_tables = set(db.scalars(select(Device.table_id).where(Device.table_id.is_not(None), Device.device_type.in_(
        ["MOTION_SENSOR", "PRESSURE_SENSOR", "IR_SENSOR", "VIBRATION_SENSOR", "CAMERA"]), Device.status == "ONLINE")).all())
    for s in db.scalars(select(GameSession).where(GameSession.status == SessionStatus.ACTIVE)).unique().all():
        cfg = branch_settings(db.get(Branch, s.branch_id)).detection
        if s.started_at and now - s.started_at > timedelta(hours=cfg.max_session_hours_alert):
            if raise_alert(db, s.branch_id, "EXCESSIVE_SESSION", f"Table {s.table.table_number} has been running for over {cfg.max_session_hours_alert}h",
                           table_id=s.table_id, session_id=s.id, dedupe_key=f"long:{s.id}"):
                n += 1
        if s.table_id in sensor_tables and s.last_activity_at and now - s.last_activity_at > timedelta(minutes=cfg.inactivity_alert_minutes):
            if cfg.auto_close_on_inactivity:
                session_service.stop(db, None, s.id, status=SessionStatus.AUTO_CLOSED, ended_at=s.last_activity_at,
                                     reason=f"No activity for {cfg.inactivity_alert_minutes} min", commit=True)
                n += 1
            elif raise_alert(db, s.branch_id, "TABLE_INACTIVE", f"Table {s.table.table_number}: no activity for {cfg.inactivity_alert_minutes} min but billing is running",
                             table_id=s.table_id, session_id=s.id, dedupe_key=f"idle:{s.id}:{s.last_activity_at.isoformat()}"):
                n += 1
    # decay unconfirmed detection states
    for st in db.scalars(select(TableDetectionState).where(TableDetectionState.state.in_([DetectionState.ACTIVITY_DETECTED, DetectionState.CONFIRMING]))).all():
        table = db.get(Table, st.table_id)
        cfg = branch_settings(db.get(Branch, table.branch_id)).detection
        if st.last_activity_at and now - ensure_utc(st.last_activity_at) > timedelta(seconds=cfg.signal_window_seconds):
            reset_state(db, st.table_id)
    db.commit()
    return n


def state_snapshot(db: Session, branch_id: uuid.UUID) -> list[dict]:
    rows = db.execute(select(TableDetectionState, Table).join(Table, Table.id == TableDetectionState.table_id).where(Table.branch_id == branch_id)).all()
    return [{"table_id": t.id, "table_number": t.table_number, "state": st.state, "score": st.score, "activity_events": st.activity_events,
             "first_activity_at": st.first_activity_at, "last_activity_at": st.last_activity_at, "identified_customer_id": st.identified_customer_id,
             "signals": st.signals} for st, t in rows]

