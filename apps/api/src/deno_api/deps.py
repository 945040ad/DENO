"""FastAPI dependencies: database session, tenant scope, Valkey, rate limiting."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deno_api.auth import DEV_USER, AuthUser, current_user
from deno_core.db.repositories import UserScope
from deno_core.errors import MfaRequired
from deno_core.events import RunEvents
from deno_core.logging import bind_context, get_logger
from deno_core.ratelimit import SlidingWindowLimiter
from deno_core.settings import get_settings

log = get_logger(__name__)


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    maker: async_sessionmaker[AsyncSession] | None = getattr(request.app.state, "sessionmaker", None)
    if maker is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not configured.")
    return maker


async def get_session(
    maker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
) -> AsyncIterator[AsyncSession]:
    """One transaction per request: committed if the handler returns, rolled back if it raises."""
    async with maker() as session, session.begin():
        yield session


def get_redis(request: Request) -> Redis:
    redis: Redis | None = getattr(request.app.state, "redis", None)
    if redis is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Queue is not configured.")
    return redis


def get_events(redis: Annotated[Redis, Depends(get_redis)]) -> RunEvents:
    return RunEvents(redis)


# user id -> (checked at, has a verified factor). Short-lived so enrolling or removing 2FA applies quickly.
MFA_CACHE_SECONDS = 60.0
_mfa_cache: dict[uuid.UUID, tuple[float, bool]] = {}


async def _has_verified_factor(maker: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> bool:
    now = time.monotonic()
    hit = _mfa_cache.get(user_id)
    if hit and now - hit[0] < MFA_CACHE_SECONDS:
        return hit[1]
    async with maker() as session:
        # auth.mfa_factors exists only on Supabase; plain Postgres (tests, CI) has no factors.
        if (await session.execute(text("SELECT to_regclass('auth.mfa_factors')"))).scalar() is None:
            enrolled = False
        else:
            enrolled = bool(
                (
                    await session.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM auth.mfa_factors"
                            " WHERE user_id = :uid AND status = 'verified')"
                        ),
                        {"uid": user_id},
                    )
                ).scalar()
            )
    if len(_mfa_cache) > 10_000:
        _mfa_cache.clear()
    _mfa_cache[user_id] = (now, enrolled)
    return enrolled


async def user_uuid(request: Request, user: Annotated[AuthUser, Depends(current_user)]) -> uuid.UUID:
    try:
        user_id = uuid.UUID(user.id)
    except ValueError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired session", {"WWW-Authenticate": "Bearer"}
        ) from None
    bind_context(user_id=str(user_id))
    # A password-only session (aal1) of a user who enrolled 2FA must not reach their data:
    # the web app's login screen can be skipped by calling the API with that token directly.
    maker: async_sessionmaker[AsyncSession] | None = getattr(request.app.state, "sessionmaker", None)
    password_only = user is not DEV_USER and user.aal != "aal2"
    if password_only and maker is not None and await _has_verified_factor(maker, user_id):
        raise MfaRequired()
    return user_id


async def rate_limit(request: Request, response: Response, user_id: Annotated[uuid.UUID, Depends(user_uuid)]) -> None:
    """60 requests/minute per user (sliding window). Fails open if Valkey is down: availability over strictness."""
    redis: Redis | None = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    settings = getattr(request.app.state, "settings", None) or get_settings()
    limit = settings.api_rate_limit_per_minute
    try:
        decision = await SlidingWindowLimiter(redis).hit(f"api:{user_id}", limit, 60)
    except RedisError:
        log.warning("rate_limiter_unavailable")
        return
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests. Slow down and try again shortly.",
            {"Retry-After": str(decision.retry_after_s)},
        )


async def get_scope(
    user_id: Annotated[uuid.UUID, Depends(user_uuid)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[None, Depends(rate_limit)],
) -> UserScope:
    return UserScope(session, user_id)


Scope = Annotated[UserScope, Depends(get_scope)]
UserId = Annotated[uuid.UUID, Depends(user_uuid)]
Events = Annotated[RunEvents, Depends(get_events)]
