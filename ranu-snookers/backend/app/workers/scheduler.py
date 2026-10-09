"""Background worker (run as its own process: `python -m app.workers.scheduler`).

Jobs are idempotent and safe to run on several replicas: each tick takes a
short Redis lock per job when REDIS_URL is set (otherwise single worker assumed).
"""
from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging

log = logging.getLogger("app.worker")


def _jobs() -> list[tuple[str, int, Callable]]:
    from app.services import booking_service, detection_service, device_service, membership_service, notification_service

    return [
        ("expire_holds", 15, lambda db: (booking_service.expire_stale_holds(db), db.commit())[0]),
        ("reserved_status", 60, booking_service.refresh_reserved_statuses),
        ("no_shows", 60, booking_service.process_no_shows),
        ("device_offline", 30, device_service.mark_offline_devices),
        ("session_monitor", 60, detection_service.monitor_sessions),
        ("reminders", 60, notification_service.schedule_reminders),
        ("notifications", 15, notification_service.dispatch_pending),
        ("membership_expiry", 3600, membership_service.expire_due),
        ("prune_heartbeats", 86400, device_service.prune_heartbeats),
    ]


class Scheduler:
    def __init__(self) -> None:
        self.last_run: dict[str, float] = {}
        self.running = True
        self._redis = None
        if settings.REDIS_URL:
            try:
                import redis

                self._redis = redis.Redis.from_url(settings.REDIS_URL)
            except Exception:  # pragma: no cover
                self._redis = None

    def _lock(self, name: str, ttl: int) -> bool:
        if self._redis is None:
            return True
        try:  # pragma: no cover - requires redis
            return bool(self._redis.set(f"ranu:job:{name}", "1", nx=True, ex=max(5, ttl - 1)))
        except Exception:
            return True

    def tick(self) -> dict[str, object]:
        results: dict[str, object] = {}
        now = time.time()
        for name, every, fn in _jobs():
            if now - self.last_run.get(name, 0) < every or not self._lock(name, every):
                continue
            self.last_run[name] = now
            db = SessionLocal()
            try:
                results[name] = fn(db)
            except Exception:
                db.rollback()
                log.exception("job_failed", extra={"job": name})
            finally:
                db.close()
        return results

    def run_forever(self) -> None:
        log.info("worker_started")
        while self.running:
            self.tick()
            time.sleep(settings.WORKER_TICK_SECONDS)


def main() -> None:  # pragma: no cover
    configure_logging()
    s = Scheduler()
    signal.signal(signal.SIGTERM, lambda *_: setattr(s, "running", False))
    signal.signal(signal.SIGINT, lambda *_: setattr(s, "running", False))
    s.run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
