"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.api.v1 import admin, auth, commerce, devices, operations, public, realtime, tables
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.errors import install_error_handlers
from app.core.logging import RequestContextMiddleware, configure_logging, metrics_text
from app.core.realtime import hub

log = logging.getLogger("app")

TAGS = [
    {"name": "auth", "description": "JWT access tokens (15 min) + rotating refresh tokens (httpOnly cookie or body)."},
    {"name": "public", "description": "Customer website: branches, availability, timeline, checkout hold, QR start. Rate limited."},
    {"name": "operations", "description": "Bookings, sessions (state machine), invoices, split payments, approvals."},
    {"name": "tables", "description": "Tables, game types, pricing rules, live board and receptionist dashboard."},
    {"name": "commerce", "description": "Customers/CRM & dues, POS, inventory ledger, memberships, loyalty, coupons."},
    {"name": "devices", "description": "Device registry & health, detection state, simulator."},
    {"name": "device-api", "description": "Hardware endpoints. Auth with X-Device-Id / X-Device-Key headers. Idempotent on event_id."},
    {"name": "admin", "description": "Branches/settings, users & roles, alerts, audit, shifts, expenses, tournaments, reports."},
    {"name": "realtime", "description": "Payment webhooks and WebSockets (/ws/branches/{id}?token=..., /ws/public/branches/{id})."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await hub.start()
    try:
        from app.services import session_service

        with SessionLocal() as db:
            n = session_service.recover_on_startup(db)
            log.info("startup_recovered", extra={"tables_resynced": n})
    except Exception:
        log.exception("startup_recovery_failed")
    task = None
    if settings.RUN_EMBEDDED_WORKER:
        from app.workers.scheduler import Scheduler

        sched = Scheduler()

        async def loop():
            while True:
                await asyncio.to_thread(sched.tick)
                await asyncio.sleep(settings.WORKER_TICK_SECONDS)

        task = asyncio.create_task(loop())
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description=(
            "RANU Club Management Platform API. Errors always use "
            "`{\"error\": {\"code\", \"message\", \"details\", \"request_id\"}}`. Lists use `?page=&size=` and return "
            "`{items,total,page,size}`. All timestamps are UTC ISO-8601."
        ),
        openapi_tags=TAGS,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Request-ID"])
    install_error_handlers(app)
    for r in (auth.router, public.router, tables.router, operations.router, commerce.router, devices.router, admin.router, realtime.router):
        app.include_router(r, prefix=settings.API_PREFIX)

    @app.get("/health", tags=["ops"])
    def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    def ready():
        checks = {}
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:  # pragma: no cover
            checks["database"] = f"error: {type(e).__name__}"
        if settings.REDIS_URL:
            try:
                import redis

                redis.Redis.from_url(settings.REDIS_URL, socket_timeout=1).ping()
                checks["redis"] = "ok"
            except Exception as e:  # pragma: no cover
                checks["redis"] = f"error: {type(e).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "degraded", "checks": checks})

    @app.get("/metrics", tags=["ops"], response_class=PlainTextResponse)
    def metrics():
        return metrics_text()

    return app


app = create_app()
