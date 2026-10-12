"""Device management (staff, JWT) and device ingestion (hardware, device key).

Hardware authenticates with headers:
    X-Device-Id:  TABLE4_SENSOR
    X-Device-Key: rdk_...   (issued once at registration)
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require
from app.core.errors import ValidationFailed
from app.core.realtime import PendingEvents
from app.core.timeutil import utcnow
from app.devices.providers.base import Signal, SignalKind
from app.schemas.domain import (
    DeviceEventBatchIn,
    DeviceEventIn,
    DeviceEventOut,
    DeviceIn,
    DeviceOut,
    DeviceUpdateIn,
    DeviceWithKeyOut,
    HeartbeatIn,
    SimulateIn,
)
from app.services import detection_service, device_service, table_service

router = APIRouter(tags=["devices"])


# ------------------------------------------------------------------------------ management
@router.get("/branches/{branch_id}/devices", response_model=list[DeviceOut])
def list_devices(branch_id: uuid.UUID, p: Principal = Depends(require("devices.view")), db: Session = Depends(get_db)):
    p.require("devices.view", branch_id)
    return device_service.list_devices(db, branch_id)


@router.post("/branches/{branch_id}/devices", response_model=DeviceWithKeyOut, status_code=201)
def register_device(branch_id: uuid.UUID, body: DeviceIn, p: Principal = Depends(require("devices.manage")), db: Session = Depends(get_db)):
    d, key = device_service.register(db, p, branch_id, body.model_dump())
    return DeviceWithKeyOut(device=DeviceOut.model_validate(d), api_key=key)


@router.patch("/devices/{device_pk}", response_model=DeviceOut)
def update_device(device_pk: uuid.UUID, body: DeviceUpdateIn, p: Principal = Depends(require("devices.manage")), db: Session = Depends(get_db)):
    return device_service.update(db, p, device_pk, body.model_dump(exclude_unset=True))


@router.post("/devices/{device_pk}/rotate-key", response_model=DeviceWithKeyOut)
def rotate_key(device_pk: uuid.UUID, p: Principal = Depends(require("devices.manage")), db: Session = Depends(get_db)):
    d, key = device_service.rotate_key(db, p, device_pk)
    return DeviceWithKeyOut(device=DeviceOut.model_validate(d), api_key=key)


@router.get("/branches/{branch_id}/device-events", response_model=list[DeviceEventOut])
def device_events(branch_id: uuid.UUID, device_pk: uuid.UUID | None = None, limit: int = 100, p: Principal = Depends(require("devices.view")), db: Session = Depends(get_db)):
    p.require("devices.view", branch_id)
    return device_service.recent_events(db, branch_id, device_pk, min(limit, 500))


@router.get("/branches/{branch_id}/detection-state")
def detection_state(branch_id: uuid.UUID, p: Principal = Depends(require("devices.view")), db: Session = Depends(get_db)):
    p.require("devices.view", branch_id)
    return {"health": device_service.health_summary(db, branch_id), "tables": detection_service.state_snapshot(db, branch_id)}


@router.post("/devices/simulate")
def simulate(body: SimulateIn, p: Principal = Depends(require("devices.manage")), db: Session = Depends(get_db)):
    """Commissioning / training tool: inject a synthetic signal for a table and see
    how the detection engine reacts (identical code path to real hardware)."""
    t = table_service.get_table(db, body.table_id)
    p.require("devices.manage", t.branch_id)
    kind = SignalKind.INTENT if body.source in ("RFID", "CONTROLLER") else SignalKind.ACTIVITY
    if body.source == "RFID" and not body.card_uid:
        raise ValidationFailed("card_uid is required for RFID simulation")
    events = PendingEvents()
    res = detection_service.process_signal(db, t, Signal(kind, body.source, body.confidence, utcnow() - timedelta(seconds=body.seconds_ago), card_uid=body.card_uid),
                                           device=None, events=events)
    db.commit()
    events.flush()
    return res


# ------------------------------------------------------------------------------ ingestion (hardware)
def _device(request: Request, db: Session, device_id: str | None, device_key: str | None):
    return device_service.authenticate(db, device_id, device_key, request.client.host if request.client else None)


@router.post("/devices/ingest/events", tags=["device-api"])
def ingest(request: Request, body: DeviceEventBatchIn | DeviceEventIn, x_device_id: str | None = Header(None), x_device_key: str | None = Header(None),
           db: Session = Depends(get_db)):
    """Send one event or a batch `{"events": [...]}`. Each `event_id` is processed at most once."""
    d = _device(request, db, x_device_id, x_device_key)
    items = [e.model_dump(mode="json") for e in body.events] if isinstance(body, DeviceEventBatchIn) else [body.model_dump(mode="json")]
    return {"results": device_service.ingest_events(db, d, items, request.client.host if request.client else None)}


@router.post("/devices/ingest/heartbeat", tags=["device-api"])
def heartbeat(request: Request, body: HeartbeatIn, x_device_id: str | None = Header(None), x_device_key: str | None = Header(None), db: Session = Depends(get_db)):
    d = _device(request, db, x_device_id, x_device_key)
    return device_service.heartbeat(db, d, body.model_dump(), request.client.host if request.client else None)

