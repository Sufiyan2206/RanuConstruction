"""Device registry, authentication, heartbeats and event ingestion (HTTP gateway).

Event path:  device/gateway ─HTTP─► ingest_events() ─► provider ─► detection_service
MQTT can be added later by a bridge that calls ingest_events() with the same payload.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import Principal
from app.core.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from app.core.realtime import PendingEvents
from app.core.security import constant_time_eq, sha256_hex
from app.core.timeutil import ensure_utc, utcnow
from app.devices.providers.base import RawEvent, Signal, SignalKind
from app.devices.providers.builtin import provider_for
from app.models import Device, DeviceEvent, DeviceHeartbeat, Table
from app.models.enums import AlertSeverity, DeviceStatus
from app.services import detection_service
from app.services.audit import audit, raise_alert, snapshot
from app.services.common import ensure_branch_access, get_branch

DEVICE_FIELDS = ["name", "table_id", "device_type", "status", "firmware_version", "configuration", "is_enabled"]


# ------------------------------------------------------------------------------ registry
def register(db: Session, actor: Principal, branch_id: uuid.UUID, data: dict) -> tuple[Device, str]:
    """Returns (device, api_key). The API key is shown ONCE; only its hash is stored."""
    branch = get_branch(db, branch_id)
    ensure_branch_access(actor, branch, "devices.manage")
    if db.scalar(select(Device.id).where(Device.device_id == data["device_id"])):
        raise Conflict("device_id already registered")
    if data.get("table_id"):
        t = db.get(Table, data["table_id"])
        if not t or t.branch_id != branch_id:
            raise ValidationFailed("Table does not belong to this branch")
    key = f"rdk_{secrets.token_urlsafe(32)}"
    d = Device(branch_id=branch_id, device_id=data["device_id"], table_id=data.get("table_id"), name=data["name"], device_type=data["device_type"],
               configuration=data.get("configuration") or {}, firmware_version=data.get("firmware_version"), status=DeviceStatus.OFFLINE,
               api_key_hash=sha256_hex(key), api_key_prefix=key[:8])
    db.add(d)
    db.flush()
    audit(db, actor, "device.register", "device", d.id, branch_id=branch_id, after=snapshot(d, DEVICE_FIELDS))
    db.commit()
    return d, key


def update(db: Session, actor: Principal, device_pk: uuid.UUID, data: dict) -> Device:
    d = _get(db, device_pk)
    ensure_branch_access(actor, get_branch(db, d.branch_id), "devices.manage")
    before = snapshot(d, DEVICE_FIELDS)
    for k, v in data.items():
        if k in DEVICE_FIELDS:
            setattr(d, k, v)
    audit(db, actor, "device.update", "device", d.id, branch_id=d.branch_id, before=before, after=snapshot(d, DEVICE_FIELDS))
    db.commit()
    return d


def rotate_key(db: Session, actor: Principal, device_pk: uuid.UUID) -> tuple[Device, str]:
    d = _get(db, device_pk)
    ensure_branch_access(actor, get_branch(db, d.branch_id), "devices.manage")
    key = f"rdk_{secrets.token_urlsafe(32)}"
    d.api_key_hash, d.api_key_prefix = sha256_hex(key), key[:8]
    audit(db, actor, "device.rotate_key", "device", d.id, branch_id=d.branch_id)
    db.commit()
    return d, key


def _get(db: Session, device_pk: uuid.UUID) -> Device:
    d = db.get(Device, device_pk)
    if not d:
        raise NotFound("Device not found")
    return d


def list_devices(db: Session, branch_id: uuid.UUID) -> list[Device]:
    return list(db.scalars(select(Device).where(Device.branch_id == branch_id).order_by(Device.device_id)).unique().all())


def recent_events(db: Session, branch_id: uuid.UUID, device_pk: uuid.UUID | None, limit: int = 100) -> list[DeviceEvent]:
    stmt = select(DeviceEvent).where(DeviceEvent.branch_id == branch_id)
    if device_pk:
        stmt = stmt.where(DeviceEvent.device_pk == device_pk)
    return list(db.scalars(stmt.order_by(DeviceEvent.received_at.desc()).limit(limit)).all())


# ------------------------------------------------------------------------------ device auth
def authenticate(db: Session, device_id: str | None, api_key: str | None, ip: str | None) -> Device:
    if not device_id or not api_key:
        raise Unauthorized("Device credentials required", code="DEVICE_AUTH")
    d = db.scalar(select(Device).where(Device.device_id == device_id))
    if not d or not constant_time_eq(d.api_key_hash, sha256_hex(api_key)):
        if d:  # someone knows the device id but not the key => spoofing attempt
            raise_alert(db, d.branch_id, "DEVICE_SPOOFING", f"Rejected event with invalid key for device {device_id} from {ip}",
                        severity=AlertSeverity.CRITICAL, device_pk=d.id, dedupe_key=f"spoof:{d.id}:{ip}")
            db.commit()
        raise Unauthorized("Invalid device credentials", code="DEVICE_AUTH")
    if not d.is_enabled:
        raise Unauthorized("Device disabled", code="DEVICE_DISABLED")
    return d


def _mark_seen(db: Session, d: Device, ip: str | None, events: PendingEvents, firmware: str | None = None) -> None:
    was = d.status
    d.last_seen_at = utcnow()
    d.ip_address = ip
    if firmware:
        d.firmware_version = firmware
    if d.status in (DeviceStatus.OFFLINE, DeviceStatus.ERROR):
        d.status = DeviceStatus.ONLINE
    if was != d.status:
        events.add(d.branch_id, "device.status", {"device_id": d.device_id, "status": d.status, "table_id": d.table_id})


def heartbeat(db: Session, d: Device, data: dict, ip: str | None) -> dict:
    events = PendingEvents()
    _mark_seen(db, d, ip, events, data.get("firmware_version"))
    if data.get("status") == "ERROR":
        d.status = DeviceStatus.ERROR
        raise_alert(db, d.branch_id, "DEVICE_ERROR", f"{d.name} reported an error: {data.get('error', '')[:120]}", device_pk=d.id, table_id=d.table_id,
                    dedupe_key=f"deverr:{d.id}", events=events)
    db.add(DeviceHeartbeat(device_pk=d.id, received_at=utcnow(), firmware_version=data.get("firmware_version"), uptime_seconds=data.get("uptime_seconds"),
                           queue_depth=data.get("queue_depth"), meta=data.get("meta") or {}))
    db.commit()
    events.flush()
    return {"status": d.status, "server_time": utcnow().isoformat(), "configuration": d.configuration}


def ingest_events(db: Session, d: Device, items: list[dict], ip: str | None) -> list[dict]:
    """Process a batch (gateways flush their offline queue in batches).
    Each event is idempotent on (device, event_id) — resends are acknowledged, never re-applied."""
    results = []
    for item in items:
        events = PendingEvents()
        try:
            results.append(_ingest_one(db, d, item, ip, events))
            db.commit()
            events.flush()
        except IntegrityError:
            db.rollback()
            results.append({"event_id": item.get("event_id"), "outcome": "DUPLICATE"})
        except Exception as e:
            db.rollback()
            results.append({"event_id": item.get("event_id"), "outcome": "ERROR", "detail": getattr(e, "message", str(e))[:200]})
    return results


def _ingest_one(db: Session, d: Device, item: dict, ip: str | None, events: PendingEvents) -> dict:
    event_id = str(item.get("event_id") or "")[:64]
    if not event_id:
        raise ValidationFailed("event_id is required for idempotency")
    if db.scalar(select(DeviceEvent.id).where(DeviceEvent.device_pk == d.id, DeviceEvent.event_id == event_id)):
        return {"event_id": event_id, "outcome": "DUPLICATE"}
    _mark_seen(db, d, ip, events)
    ts = item.get("timestamp")
    occurred = ensure_utc(datetime.fromisoformat(ts.replace("Z", "+00:00"))) if ts else utcnow()
    raw = RawEvent(event=str(item.get("event", "")).upper(), occurred_at=occurred, confidence=item.get("confidence"),
                   card_uid=item.get("card_uid"), payload=item.get("payload") or {})
    row = DeviceEvent(device_pk=d.id, event_id=event_id, branch_id=d.branch_id, table_id=d.table_id, event_type=raw.event, confidence=raw.confidence,
                      payload={k: v for k, v in item.items() if k not in ("event_id",)}, occurred_at=occurred, received_at=utcnow())
    db.add(row)
    db.flush()  # UNIQUE(device, event_id) enforced here for concurrent duplicates
    claimed_table = item.get("table_id")
    if claimed_table is not None and d.table is not None and str(claimed_table) not in (str(d.table.id), str(d.table.table_number)):
        raise_alert(db, d.branch_id, "DEVICE_TABLE_MISMATCH", f"{d.device_id} claims table {claimed_table} but is assigned to table {d.table.table_number}",
                    severity=AlertSeverity.WARNING, device_pk=d.id, dedupe_key=f"mismatch:{d.id}", events=events)
    if d.table_id is None:
        row.outcome = "NO_TABLE_ASSIGNED"
        return {"event_id": event_id, "outcome": row.outcome}
    if d.status == DeviceStatus.MAINTENANCE:
        row.outcome = "DEVICE_IN_MAINTENANCE"
        return {"event_id": event_id, "outcome": row.outcome}
    sig = provider_for(d.device_type).interpret(raw, d.configuration or {})
    table = db.get(Table, d.table_id)
    result = detection_service.process_signal(db, table, sig, device=d, events=events)
    row.outcome = result.get("outcome")
    row.detail = str({k: v for k, v in result.items() if k != "outcome"})[:500]
    return {"event_id": event_id, **result}


# ------------------------------------------------------------------------------ QR (Option B)
def qr_lookup(db: Session, token: str) -> Table:
    t = db.scalar(select(Table).where(Table.qr_token == token, Table.deleted_at.is_(None)))
    if not t:
        raise NotFound("Unknown table code")
    return t


def qr_start(db: Session, token: str, *, phone: str | None, name: str | None, customer_id: uuid.UUID | None) -> dict:
    """Customer scanned the QR at the table and confirmed 'Start Game'."""
    t = qr_lookup(db, token)
    events = PendingEvents()
    if phone and not customer_id:
        from app.models import Branch
        from app.services import customer_service

        branch = db.get(Branch, t.branch_id)
        c = customer_service.find_or_create(db, branch.organization_id, name=name or "Guest", phone=phone, branch_id=branch.id)
        customer_id = c.id
    sig = Signal(SignalKind.INTENT, "QR", 1.0, utcnow())
    st = detection_service._state(db, t.id)
    if customer_id:
        st.identified_customer_id, st.identified_at = customer_id, utcnow()
    result = detection_service.process_signal(db, t, sig, device=None, events=events)
    db.commit()
    events.flush()
    return result


# ------------------------------------------------------------------------------ health monitor
def mark_offline_devices(db: Session) -> int:
    cutoff = utcnow() - timedelta(seconds=settings.DEVICE_OFFLINE_AFTER_SECONDS)
    events = PendingEvents()
    n = 0
    for d in db.scalars(select(Device).where(Device.status == DeviceStatus.ONLINE, Device.last_seen_at < cutoff)).unique().all():
        d.status = DeviceStatus.OFFLINE
        n += 1
        raise_alert(db, d.branch_id, "DEVICE_OFFLINE", f"{d.name} ({d.device_id}) is OFFLINE — use manual start/stop for this table",
                    device_pk=d.id, table_id=d.table_id, dedupe_key=f"offline:{d.id}", events=events)
        events.add(d.branch_id, "device.status", {"device_id": d.device_id, "status": d.status, "table_id": d.table_id})
    db.commit()
    events.flush()
    return n


def health_summary(db: Session, branch_id: uuid.UUID) -> dict:
    rows = db.execute(select(Device.status, func.count()).where(Device.branch_id == branch_id).group_by(Device.status)).all()
    return {status: count for status, count in rows}


def prune_heartbeats(db: Session, days: int = 7) -> int:
    from sqlalchemy import delete

    res = db.execute(delete(DeviceHeartbeat).where(DeviceHeartbeat.received_at < utcnow() - timedelta(days=days)))
    db.commit()
    return res.rowcount or 0
