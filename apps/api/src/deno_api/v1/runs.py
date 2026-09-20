"""Validation runs: status, live events (SSE), cancellation, report, evidence, review."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deno_api.deps import Events, Scope, UserId, get_sessionmaker, rate_limit
from deno_api.v1.schemas import (
    ClaimOut,
    EvidenceOut,
    EvidencePage,
    ReportOut,
    ResumeRequest,
    RunOut,
    SignalOut,
    VerdictOut,
)
from deno_core.db.enums import RunStatus, Source
from deno_core.db.repositories import UserScope
from deno_core.errors import Conflict
from deno_core.events import RunEvent
from deno_core.jobs import TASK_VALIDATION_RUN, enqueue

router = APIRouter(prefix="/runs", tags=["runs"])

HEARTBEAT_MS = 15_000


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, scope: Scope) -> RunOut:
    return RunOut.model_validate(await scope.get_run(run_id))


async def owned_run_status(
    run_id: uuid.UUID,
    user_id: UserId,
    maker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
) -> RunStatus:
    """Ownership check before the stream starts (a 404 can't be sent once streaming began).

    Uses its own short session so the long-lived stream holds no DB connection.
    """
    async with maker() as session:
        return (await UserScope(session, user_id).get_run(run_id)).status


@router.get(
    "/{run_id}/events",
    response_class=EventSourceResponse,
    dependencies=[Depends(rate_limit)],
    responses={200: {"description": "text/event-stream of run events; closes after a terminal status"}},
)
async def run_events(
    run_id: uuid.UUID,
    run_status: Annotated[RunStatus, Depends(owned_run_status)],
    events: Events,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=64)] = None,
) -> AsyncIterable[ServerSentEvent]:
    """Live node/source/status events. Resumes after `Last-Event-ID`; heartbeat comment every 15 s."""
    stream = events.follow(str(run_id), after=last_event_id or "0-0", block_ms=HEARTBEAT_MS)
    saw_any = False
    async for event in stream:
        if event is None:
            if not saw_any and run_status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
                # Stream already expired (runs older than a day): report the final state and stop.
                yield _sse(RunEvent(type="status", data={"status": run_status.value}, id="0-1"))
                return
            yield ServerSentEvent(comment="heartbeat")
            continue
        saw_any = True
        yield _sse(event)


def _sse(event: RunEvent) -> ServerSentEvent:
    return ServerSentEvent(data={"type": event.type, "ts": event.ts, **event.data}, event=event.type, id=event.id)


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: uuid.UUID, scope: Scope, events: Events) -> RunOut:
    run = await scope.get_run(run_id)
    if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
        raise Conflict("That run has already finished.")
    await events.request_cancel(str(run_id))
    if run.status == RunStatus.QUEUED:
        run.status = RunStatus.CANCELLED  # never started; the worker will skip it
    return RunOut.model_validate(run)


@router.post("/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_run(run_id: uuid.UUID, body: ResumeRequest, scope: Scope, background: BackgroundTasks) -> RunOut:
    """Answer the review step: flag wrong claims (kept for evals) and let the run finish."""
    run = await scope.get_run(run_id)
    if run.status != RunStatus.AWAITING_REVIEW:
        raise Conflict("That run isn't waiting for review.")
    await scope.flag_claims(run_id, body.wrong_claim_ids)
    run.status = RunStatus.QUEUED
    background.add_task(enqueue, TASK_VALIDATION_RUN, run_id=str(run_id), user_id=str(scope.user_id))
    return RunOut.model_validate(run)


@router.get("/{run_id}/report")
async def get_report(run_id: uuid.UUID, scope: Scope) -> ReportOut:
    run = await scope.get_run(run_id)
    verdict = await scope.get_verdict(run_id)
    return ReportOut(
        run=RunOut.model_validate(run),
        verdict=VerdictOut.model_validate(verdict) if verdict else None,
        signals=[SignalOut.model_validate(s) for s in await scope.list_signals(run_id)],
        claims=[ClaimOut.of(c, cites) for c, cites in await scope.list_claims_with_evidence(run_id)],
    )


@router.get("/{run_id}/evidence")
async def list_evidence(
    run_id: uuid.UUID,
    scope: Scope,
    source: Source | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> EvidencePage:
    page = await scope.list_evidence(run_id, source=source, limit=limit, cursor=cursor)
    return EvidencePage(items=[EvidenceOut.of(d) for d in page.items], next_cursor=page.next_cursor)


@router.get("/{run_id}/claims/{claim_id}")
async def get_claim(run_id: uuid.UUID, claim_id: uuid.UUID, scope: Scope) -> ClaimOut:
    claim, cites = await scope.get_claim(run_id, claim_id)
    return ClaimOut.of(claim, cites)
