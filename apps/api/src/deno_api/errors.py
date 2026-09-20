"""One error envelope for every failure: ``{"error": {"code", "message", "request_id"}}``.

Unhandled exceptions are logged with their stack trace and returned as a
generic 500 — internals, upstream bodies and tracebacks never reach clients.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from deno_core.errors import (
    Conflict,
    DenoError,
    InvalidInput,
    NotFound,
    PermissionDenied,
    QuotaExceeded,
    RateLimited,
    UpstreamUnavailable,
)
from deno_core.logging import get_logger

log = get_logger(__name__)

STATUS_BY_ERROR: dict[type[DenoError], int] = {
    NotFound: 404,
    PermissionDenied: 403,
    InvalidInput: 422,
    Conflict: 409,
    QuotaExceeded: 402,
    RateLimited: 429,
    UpstreamUnavailable: 503,
}

CODE_BY_STATUS = {
    400: "bad_request",
    401: "unauthenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "invalid_input",
    429: "rate_limited",
}


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def envelope(
    request: Request, status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "request_id": request_id_of(request)}}
    return JSONResponse(status_code=status, content=body, headers=headers)


async def _deno_error(request: Request, exc: Exception) -> JSONResponse:
    err = cast(DenoError, exc)
    status = next((s for cls, s in STATUS_BY_ERROR.items() if isinstance(err, cls)), 500)
    if status >= 500:
        log.error("domain_error", code=err.code, exc_info=err)
    return envelope(request, status, err.code, err.message)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    http = cast(StarletteHTTPException, exc)
    code = CODE_BY_STATUS.get(http.status_code, "error")
    message = http.detail if isinstance(http.detail, str) else "Request failed."
    headers = dict(getattr(http, "headers", None) or {})
    if http.status_code == 405:
        headers["Allow"] = _allowed_methods(request)
    return envelope(request, http.status_code, code, message, headers=headers or None)


def _allowed_methods(request: Request) -> str:
    """Every method any route serves at this path (Starlette only reports the first partial match)."""
    methods: set[str] = set()
    for route in request.app.router.routes:
        match, _ = route.matches({**request.scope, "method": "GET"})
        route_methods = getattr(route, "methods", None)
        if match != Match.NONE and route_methods:
            methods |= set(route_methods)
    return ", ".join(sorted(methods))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    invalid = cast(RequestValidationError, exc)
    # Field paths only; never echo the submitted values back.
    fields = [".".join(str(p) for p in e.get("loc", ())) for e in invalid.errors()]
    message = "Invalid request: " + ", ".join(fields) if fields else "Invalid request."
    return envelope(request, 422, "invalid_input", message)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", path=request.url.path, exc_info=exc)
    # Starlette runs this handler outside user middleware, so the request-id
    # middleware never sees this response; add the header here.
    request_id = request_id_of(request)
    headers = {"X-Request-ID": request_id} if request_id else None
    return envelope(request, 500, "internal_error", DenoError.message, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DenoError, _deno_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)
