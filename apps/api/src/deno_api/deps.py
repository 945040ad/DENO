"""FastAPI dependencies: database session, tenant scope, Valkey, rate limiting."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deno_api.auth import AuthUser, current_user
from deno_core.db.repositories import UserScope
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


def user_uuid(user: Annotated[AuthUser, Depends(current_user)]) -> uuid.UUID:
    try:
        user_id = uuid.UUID(user.id)
    except ValueError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired session", {"WWW-Authenticate": "Bearer"}
        ) from None
    bind_context(user_id=str(user_id))
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
