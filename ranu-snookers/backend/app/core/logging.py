"""Structured JSON logging + request-ID middleware."""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

_STD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD and not k.startswith("_"):
                data[k] = v
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.LOG_LEVEL)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = rid
        logging.getLogger("app.access").info(
            "request",
            extra={"method": request.method, "path": request.url.path, "status": response.status_code, "ms": elapsed, "rid": rid},
        )
        _metrics.observe(request.url.path, response.status_code, elapsed)
        return response


class _Metrics:
    """Tiny in-process metrics exposed at /metrics (Prometheus text format)."""

    def __init__(self) -> None:
        self.requests = 0
        self.errors = 0
        self.total_ms = 0.0

    def observe(self, path: str, status: int, ms: float) -> None:
        self.requests += 1
        self.total_ms += ms
        if status >= 500:
            self.errors += 1

    def render(self) -> str:
        avg = self.total_ms / self.requests if self.requests else 0
        return (
            f"ranu_http_requests_total {self.requests}\n"
            f"ranu_http_errors_total {self.errors}\n"
            f"ranu_http_request_avg_ms {avg:.2f}\n"
        )


_metrics = _Metrics()


def metrics_text() -> str:
    return _metrics.render()
