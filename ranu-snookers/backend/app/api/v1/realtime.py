"""WebSockets + payment webhooks (not rate limited like public endpoints).

WebSocket protocol
------------------
Connect:  wss://host/api/v1/ws/branches/{branch_id}?token=<access JWT>   (staff)
          wss://host/api/v1/ws/public/branches/{branch_id}              (booking page)
Server → client messages: {"type": "table.status" | "session.started" | ... , "data": {...}}
Client → server: "ping" → "pong" (keep-alive). Clients should refetch on reconnect.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.deps import build_principal
from app.core.realtime import hub
from app.core.security import decode_access_token
from app.models import User
from app.services import payment_service

router = APIRouter(tags=["realtime"])


@router.post("/payments/webhooks/{provider}")
async def webhook(provider: str, request: Request, db: Session = Depends(get_db)):
    """Provider → server. Signature-verified and idempotent; authoritative for booking confirmation."""
    body = await request.body()
    return payment_service.handle_webhook(db, provider, dict(request.headers), body)


async def _pump(channel: str, ws: WebSocket) -> None:
    await hub.connect(channel, ws)
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(channel, ws)


@router.websocket("/ws/branches/{branch_id}")
async def staff_ws(ws: WebSocket, branch_id: uuid.UUID, token: str | None = None):
    try:
        payload = decode_access_token(token or "")
        with SessionLocal() as db:
            user = db.get(User, uuid.UUID(payload["sub"]))
            if not user or not user.is_active or not build_principal(user).has("tables.view", branch_id):
                raise PermissionError
    except Exception:
        await ws.close(code=4401)
        return
    await _pump(f"staff:{branch_id}", ws)


@router.websocket("/ws/public/branches/{branch_id}")
async def public_ws(ws: WebSocket, branch_id: uuid.UUID):
    await _pump(f"public:{branch_id}", ws)
