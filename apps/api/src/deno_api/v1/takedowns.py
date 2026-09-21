"""Takedowns: anyone can ask for content to be removed; an operator reviews and purges.

Intake is public (the person asking is usually not a Deno user) and rate-limited per IP.
Nothing is purged on intake, otherwise anyone could erase evidence from other users' reports;
an admin (``profiles.role = 'admin'``, set in SQL) approves or rejects each request.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from deno_api.deps import Scope, get_session
from deno_api.v1.schemas import TakedownCreate, TakedownOut, TakedownReceipt, TakedownResolved
from deno_core.db import repositories as repo
from deno_core.db.enums import TakedownStatus
from deno_core.db.repositories import UserScope
from deno_core.logging import get_logger
from deno_core.ratelimit import SlidingWindowLimiter
from deno_core.settings import get_settings

router = APIRouter(tags=["takedowns"])
log = get_logger(__name__)
Session = Annotated[AsyncSession, Depends(get_session)]


async def _ip_rate_limit(request: Request) -> None:
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    settings = getattr(request.app.state, "settings", None) or get_settings()
    ip = request.client.host if request.client else "unknown"
    try:
        decision = await SlidingWindowLimiter(redis).hit(f"takedown:{ip}", settings.takedown_rate_limit_per_hour, 3600)
    except RedisError:
        log.warning("rate_limiter_unavailable")
        return
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many takedown requests from this address. Try again later.",
            {"Retry-After": str(decision.retry_after_s)},
        )


async def require_admin(scope: Scope) -> UserScope:
    profile = await scope.ensure_profile()
    if profile.role != "admin":
        # 404, not 403: the admin surface doesn't advertise itself.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return scope


Admin = Annotated[UserScope, Depends(require_admin)]


@router.post("/takedowns", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(_ip_rate_limit)])
async def request_takedown(body: TakedownCreate, session: Session) -> TakedownReceipt:
    """Ask for a post (by URL) or everything by an author (by handle) to be removed from Deno."""
    created = await repo.create_takedown(
        session, url=body.url, author_handle=body.author_handle, reason=body.reason, contact=body.contact
    )
    log.info("takedown_received", takedown_id=str(created.id))
    return TakedownReceipt(id=created.id, status=created.status)


@router.get("/admin/takedowns")
async def list_takedowns(
    scope: Admin, status_filter: Annotated[TakedownStatus | None, Query(alias="status")] = None
) -> list[TakedownOut]:
    return [TakedownOut.model_validate(t) for t in await repo.list_takedowns(scope.session, status_filter)]


@router.post("/admin/takedowns/{takedown_id}/approve")
async def approve_takedown(takedown_id: uuid.UUID, scope: Admin) -> TakedownResolved:
    request, purged = await repo.resolve_takedown(scope.session, takedown_id, approve=True)
    log.info("takedown_processed", takedown_id=str(takedown_id), purged=purged)
    return TakedownResolved(id=request.id, status=request.status, purged_documents=purged)


@router.post("/admin/takedowns/{takedown_id}/reject")
async def reject_takedown(takedown_id: uuid.UUID, scope: Admin) -> TakedownResolved:
    request, _ = await repo.resolve_takedown(scope.session, takedown_id, approve=False)
    log.info("takedown_rejected", takedown_id=str(takedown_id))
    return TakedownResolved(id=request.id, status=request.status, purged_documents=0)
