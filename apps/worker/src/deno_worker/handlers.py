"""Graph-run job bodies, shared by the taskiq worker (tasks.py) and the one-shot
Cloud Run Job entrypoint (run_once.py)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from deno_core.db.session import get_sessionmaker
from deno_core.events import RunEvents
from deno_core.jobs import TASK_CONTENT_PLAN, TASK_VALIDATION_RUN
from deno_core.logging import get_logger
from deno_core.runs import RunContext, execute_run

log = get_logger(__name__)


def register_runners() -> None:
    # The validation graph registers itself as the runner when its package is installed (Phase 8).
    try:
        from deno_graphs.validation.runner import register as register_graph
    except ImportError:
        log.warning("validation_graph_not_installed")
    else:
        register_graph()


def _context(run_id: str, user_id: str, redis: Redis) -> RunContext:
    return RunContext(
        run_id=uuid.UUID(run_id),
        user_id=uuid.UUID(user_id),
        events=RunEvents(redis),
        sessionmaker=get_sessionmaker(),
    )


async def validation_run(redis: Redis, run_id: str, user_id: str) -> None:
    await execute_run(_context(run_id, user_id, redis))


async def content_plan(redis: Redis, plan_id: str, user_id: str) -> None:
    from deno_graphs.content.graph import run_content_plan

    await run_content_plan(_context(plan_id, user_id, redis))


GRAPH_HANDLERS: dict[str, Callable[..., Awaitable[None]]] = {
    TASK_VALIDATION_RUN: validation_run,
    TASK_CONTENT_PLAN: content_plan,
}
