"""Real-time fan-out for WebSocket clients.

Services call ``publish(branch_id, event_type, data)`` *after* commit. The hub
delivers to local sockets and, when REDIS_URL is configured, also publishes to
Redis so every API replica forwards the event to its own sockets.

Channels:
  * ``staff:<branch_id>``  – full payloads for authenticated staff dashboards
  * ``public:<branch_id>`` – availability-only payloads for the booking page
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.core.config import settings

log = logging.getLogger("app.realtime")

PUBLIC_EVENT_TYPES = {"table.status", "availability.changed"}


class RealtimeHub:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._redis = None
        self._instance = uuid.uuid4().hex

    # ---- lifecycle -------------------------------------------------------------
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if settings.REDIS_URL:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(settings.REDIS_URL)
                asyncio.create_task(self._redis_listener())
            except Exception:  # pragma: no cover - redis optional
                log.exception("realtime_redis_unavailable")
                self._redis = None

    async def _redis_listener(self) -> None:  # pragma: no cover - needs redis
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("ranu:realtime")
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                envelope = json.loads(msg["data"])
                if envelope.get("origin") == self._instance:
                    continue
                await self._deliver(envelope["branch_id"], envelope["message"])
            except Exception:
                log.exception("realtime_redis_message_error")

    # ---- sockets ---------------------------------------------------------------
    async def connect(self, channel: str, ws: WebSocket) -> None:
        await ws.accept()
        self._sockets[channel].add(ws)

    def disconnect(self, channel: str, ws: WebSocket) -> None:
        self._sockets[channel].discard(ws)

    async def _send(self, channel: str, message: dict) -> None:
        dead = []
        for ws in list(self._sockets.get(channel, ())):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._sockets[channel].discard(ws)

    async def _deliver(self, branch_id: str, message: dict) -> None:
        await self._send(f"staff:{branch_id}", message)
        if message["type"] in PUBLIC_EVENT_TYPES:
            public = {"type": message["type"], "data": message.get("public") or {}}
            await self._send(f"public:{branch_id}", public)

    # ---- publishing (thread-safe, callable from sync service code) -------------
    def publish(self, branch_id: uuid.UUID | str, event_type: str, data: dict[str, Any], public: dict | None = None) -> None:
        message = {"type": event_type, "data": _jsonable(data)}
        if public is not None:
            message["public"] = _jsonable(public)
        bid = str(branch_id)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        coro = self._publish_async(bid, message)
        if running is loop:
            loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)

    async def _publish_async(self, branch_id: str, message: dict) -> None:
        await self._deliver(branch_id, message)
        if self._redis is not None:  # pragma: no cover
            try:
                await self._redis.publish(
                    "ranu:realtime", json.dumps({"origin": self._instance, "branch_id": branch_id, "message": message})
                )
            except Exception:
                log.warning("realtime_redis_publish_failed")


def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


hub = RealtimeHub()


class PendingEvents:
    """Collects events inside a unit of work; flushed only after a successful commit
    so clients never see state that was rolled back."""

    def __init__(self) -> None:
        self.items: list[tuple] = []

    def add(self, branch_id, event_type: str, data: dict, public: dict | None = None) -> None:
        self.items.append((branch_id, event_type, data, public))

    def flush(self) -> None:
        for branch_id, event_type, data, public in self.items:
            hub.publish(branch_id, event_type, data, public)
        self.items.clear()
