"""Fixed-window rate limiter. Uses Redis when configured (shared across replicas),
otherwise an in-process dictionary (fine for single-node/dev)."""
from __future__ import annotations

import threading
import time

from fastapi import Request

from app.core.config import settings
from app.core.errors import RateLimited

_lock = threading.Lock()
_memory: dict[str, tuple[int, int]] = {}
_redis = None
if settings.REDIS_URL:
    try:  # pragma: no cover - depends on infra
        import redis

        _redis = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=0.3)
    except Exception:
        _redis = None


def _hit(key: str, window: int) -> int:
    bucket = int(time.time() // window)
    full = f"rl:{key}:{bucket}"
    if _redis is not None:  # pragma: no cover
        try:
            n = _redis.incr(full)
            if n == 1:
                _redis.expire(full, window + 1)
            return int(n)
        except Exception:
            pass
    with _lock:
        b, n = _memory.get(key, (bucket, 0))
        if b != bucket:
            b, n = bucket, 0
        n += 1
        _memory[key] = (b, n)
        return n


def rate_limit(name: str, per_minute: int | None = None):
    def _dep(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        limit = per_minute or settings.RATE_LIMIT_PUBLIC_PER_MINUTE
        ip = request.client.host if request.client else "unknown"
        if _hit(f"{name}:{ip}", 60) > limit:
            raise RateLimited("Too many requests, please slow down.")

    return _dep


def reset_memory() -> None:
    with _lock:
        _memory.clear()
