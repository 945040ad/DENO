"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from deno_api.errors import install_error_handlers
from deno_api.health import register_readiness_check
from deno_api.health import router as health_router
from deno_api.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from deno_api.v1 import billing, content, me, projects, runs, takedowns
from deno_api.v1.schemas import ERROR_RESPONSES
from deno_core.db.session import build_engine
from deno_core.logging import configure_logging, get_logger
from deno_core.observability import init_sentry
from deno_core.settings import Settings, get_settings

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = None
    if settings.database_url and getattr(app.state, "sessionmaker", None) is None:
        engine = build_engine(settings.database_url)
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

        async def db_ready() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        register_readiness_check("database", db_ready)
    if getattr(app.state, "redis", None) is None:
        # socket_timeout must exceed the SSE XREAD block (15 s) or idle streams die mid-run.
        app.state.redis = Redis.from_url(settings.valkey_url, socket_timeout=30, socket_connect_timeout=2)
        redis = app.state.redis

        async def valkey_ready() -> None:
            await redis.ping()

        register_readiness_check("valkey", valkey_ready)
    try:
        yield
    finally:
        if engine is not None:
            await engine.dispose()
        await app.state.redis.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    init_sentry(settings, "api")
    app = FastAPI(
        title="Deno API",
        version="1.0.0",
        description="Evidence-grounded idea validation and human-voice distribution.",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)
    v1.include_router(projects.router)
    v1.include_router(runs.router)
    v1.include_router(me.router)
    v1.include_router(takedowns.router)
    v1.include_router(content.router)
    v1.include_router(billing.router)
    app.include_router(v1)
    app.include_router(health_router)

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.request_max_bytes)
    # Browsers normally reach the API through the Next.js /api rewrite (same
    # origin). Direct cross-origin calls are limited to the web app's origins and
    # authenticate with a bearer token, so no credentials mode is needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key", "Last-Event-ID"],
        expose_headers=["X-Request-ID", "Retry-After", "X-RateLimit-Remaining"],
    )
    # Outermost, so the request id covers CORS rejections and error responses too.
    app.add_middleware(RequestContextMiddleware)
    return app
