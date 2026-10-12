"""Audit logging and alerting. Written in the SAME transaction as the change it
describes, so an audited change and its audit row commit or roll back together."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.core.logging import request_id_ctx
from app.core.realtime import PendingEvents
from app.core.timeutil import utcnow
from app.models import Alert, AuditLog
from app.models.enums import AlertSeverity


def _clean(v: Any) -> Any:
    if isinstance(v, (uuid.UUID, Decimal)):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def snapshot(obj: Any, fields: list[str]) -> dict:
    return {f: _clean(getattr(obj, f, None)) for f in fields}


def audit(
    db: Session,
    actor: Principal | None,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    *,
    branch_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> AuditLog:
    row = AuditLog(
        organization_id=actor.organization_id if actor else None,
        branch_id=branch_id,
        user_id=actor.id if actor else None,
        username=actor.user.username if actor else "system",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_clean(before) if before else None,
        after=_clean(after) if after else None,
        reason=reason,
        ip=actor.ip if actor else None,
        user_agent=actor.user_agent if actor else None,
        request_id=(actor.request_id if actor else None) or request_id_ctx.get(),
        created_at=utcnow(),
    )
    db.add(row)
    return row


def raise_alert(
    db: Session,
    branch_id: uuid.UUID,
    alert_type: str,
    message: str,
    *,
    severity: AlertSeverity = AlertSeverity.WARNING,
    table_id: uuid.UUID | None = None,
    device_pk: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    data: dict | None = None,
    events: PendingEvents | None = None,
) -> Alert | None:
    """Create an alert unless an unacknowledged alert with the same dedupe_key exists."""
    if dedupe_key:
        existing = db.scalar(select(Alert).where(Alert.dedupe_key == dedupe_key, Alert.acknowledged_at.is_(None)))
        if existing:
            return None
    alert = Alert(
        branch_id=branch_id, alert_type=alert_type, severity=severity, message=message, table_id=table_id,
        device_pk=device_pk, session_id=session_id, dedupe_key=dedupe_key, data=_clean(data or {}), created_at=utcnow(),
    )
    db.add(alert)
    db.flush()
    if events is not None:
        events.add(branch_id, "alert.created", {"id": alert.id, "type": alert_type, "severity": severity, "message": message})
    return alert
