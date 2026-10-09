"""Consistent error model.

Every error leaving the API has the shape::

    {"error": {"code": "BOOKING_CONFLICT", "message": "...", "details": {...}, "request_id": "..."}}
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class InvalidState(AppError):
    status_code = 409
    code = "INVALID_STATE_TRANSITION"


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"


def _body(request: Request, code: str, message: str, details: Any = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_body(request, exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content=_body(request, "VALIDATION_ERROR", "Request validation failed", details))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(status_code=exc.status_code, content=_body(request, code, str(exc.detail)))

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError):
        log.warning("integrity_error", extra={"error": str(exc.orig)[:300]})
        return JSONResponse(
            status_code=409,
            content=_body(request, "CONFLICT", "The operation conflicts with existing data (duplicate or concurrent change)."),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled_error")
        return JSONResponse(status_code=500, content=_body(request, "INTERNAL_ERROR", "An unexpected error occurred."))
