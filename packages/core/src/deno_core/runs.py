"""Validation-run lifecycle, independent of what actually runs (the LangGraph graph, Phase 8).

``execute_run`` owns status transitions, events and failure handling; a
*runner* does the work. Re-delivery of the same job is safe: a run already in
a terminal state is skipped, and a running one resumes (the graph checkpointer
continues from its last completed node).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deno_core.db.enums import RunStatus
from deno_core.db.repositories import UserScope
from deno_core.events import RunEvent, RunEvents
from deno_core.jobs import RETRYABLE
from deno_core.logging import bind_context, get_logger

log = get_logger(__name__)

TERMINAL = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
LEASE_SECONDS = 60
LEASE_REFRESH_SECONDS = 20


class RunCancelled(Exception):
    """Raised by a runner when it notices the cancel flag between nodes."""


@dataclass(frozen=True)
class RunOutcome:
    status: Literal["succeeded", "awaiting_review", "failed"]
    error_code: str | None = None


@dataclass
class RunContext:
    run_id: uuid.UUID
    user_id: uuid.UUID
    events: RunEvents
    sessionmaker: async_sessionmaker[AsyncSession]

    async def emit(self, type_: Any, **data: Any) -> None:
        await self.events.publish(str(self.run_id), RunEvent(type=type_, data=data))

    async def check_cancelled(self) -> None:
        if await self.events.is_cancelled(str(self.run_id)):
            raise RunCancelled()

    def scope(self, session: AsyncSession) -> UserScope:
        return UserScope(session, self.user_id)


class Runner(Protocol):
    async def __call__(self, ctx: RunContext) -> RunOutcome: ...


async def _not_deployed(ctx: RunContext) -> RunOutcome:  # replaced by the graph runner at worker start
    await ctx.emit("log", message="No validation graph is registered in this worker.")
    return RunOutcome("failed", "runner_not_configured")


_runner: Runner = _not_deployed


def register_runner(runner: Runner) -> None:
    global _runner
    _runner = runner


def current_runner() -> Runner:
    return _runner


async def _set_status(
    ctx: RunContext, status: RunStatus, *, error_code: str | None = None, started: bool = False
) -> None:
    async with ctx.sessionmaker() as session, session.begin():
        run = await ctx.scope(session).get_run(ctx.run_id)
        run.status = status
        if started and run.started_at is None:
            run.started_at = datetime.now(UTC)
        if status in TERMINAL or status == RunStatus.AWAITING_REVIEW:
            run.finished_at = datetime.now(UTC)
        run.error_code = error_code
    await ctx.emit("status", status=status.value, **({"error_code": error_code} if error_code else {}))


def lease_key(run_id: str) -> str:
    return f"run:{run_id}:lease"


@contextlib.asynccontextmanager
async def run_lease(ctx: RunContext) -> AsyncIterator[bool]:
    """Exclusive, self-renewing lease so a duplicate delivery never executes a run twice.

    If the worker dies, the lease expires within LEASE_SECONDS and a re-delivered
    job can take over (resuming from the graph checkpoint).
    """
    redis = ctx.events.redis
    key, token = lease_key(str(ctx.run_id)), uuid.uuid4().hex
    if not await redis.set(key, token, nx=True, ex=LEASE_SECONDS):
        yield False
        return

    async def renew() -> None:
        while True:
            await asyncio.sleep(LEASE_REFRESH_SECONDS)
            await redis.set(key, token, xx=True, ex=LEASE_SECONDS)

    renewer = asyncio.create_task(renew())
    try:
        yield True
    finally:
        renewer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewer
        current = await redis.get(key)
        if current in (token, token.encode()):
            await redis.delete(key)


async def execute_run(
    ctx: RunContext, runner: Runner | Callable[[RunContext], Awaitable[RunOutcome]] | None = None
) -> None:
    bind_context(run_id=str(ctx.run_id), user_id=str(ctx.user_id))
    async with run_lease(ctx) as acquired:
        if not acquired:
            log.info("run_already_being_executed")
            return
        await _execute(ctx, runner or current_runner())


async def _execute(ctx: RunContext, runner: Runner | Callable[[RunContext], Awaitable[RunOutcome]]) -> None:
    async with ctx.sessionmaker() as session:
        run = await ctx.scope(session).get_run(ctx.run_id)
        if run.status in TERMINAL:
            log.info("run_already_finished", status=run.status.value)
            return
    if await ctx.events.is_cancelled(str(ctx.run_id)):
        await _set_status(ctx, RunStatus.CANCELLED)
        return

    await _set_status(ctx, RunStatus.RUNNING, started=True)
    try:
        outcome = await runner(ctx)
    except RunCancelled:
        log.info("run_cancelled")
        await _set_status(ctx, RunStatus.CANCELLED)
        return
    except RETRYABLE:
        # Leave it RUNNING; the job middleware retries and the graph resumes from its checkpoint.
        log.warning("run_transient_failure", exc_info=True)
        raise
    except Exception:
        log.exception("run_failed")
        await _set_status(ctx, RunStatus.FAILED, error_code="internal_error")
        return
    await _set_status(ctx, RunStatus(outcome.status), error_code=outcome.error_code)
