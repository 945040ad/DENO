"""Liveness and readiness probes.

`/healthz` answers as long as the process serves requests. `/readyz` checks
each dependency the API needs to do useful work; checks are registered by the
modules that own the dependency (database, Valkey, SearXNG) as they land.
"""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from deno_core.settings import get_settings

router = APIRouter(tags=["ops"])

ReadinessCheck = Callable[[], Awaitable[None]]
_checks: dict[str, ReadinessCheck] = {}


def register_readiness_check(name: str, check: ReadinessCheck) -> None:
    _checks[name] = check


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    async def run(check: ReadinessCheck) -> str:
        try:
            await asyncio.wait_for(check(), timeout=3)
        except Exception:
            return "fail"
        return "ok"

    names = list(_checks)
    results = dict(zip(names, await asyncio.gather(*(run(_checks[n]) for n in names)), strict=True))
    ready = all(v == "ok" for v in results.values())
    return JSONResponse(
        status_code=200 if ready else 503, content={"status": "ok" if ready else "degraded", "checks": results}
    )


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Prometheus scrape endpoint: bearer METRICS_TOKEN, or loopback only when no token is set."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    token = settings.metrics_token.get_secret_value()
    auth = request.headers.get("authorization", "")
    client = request.client.host if request.client else ""
    allowed = hmac.compare_digest(auth, f"Bearer {token}") if token else client in {"127.0.0.1", "::1"}
    if not allowed:
        return Response(status_code=404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
