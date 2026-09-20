"""Worker entrypoint: ``taskiq worker deno_worker.tasks:broker`` (+ ``taskiq scheduler deno_worker.tasks:scheduler``)."""

from __future__ import annotations

import uuid

from redis.asyncio import Redis
from taskiq import TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource

from deno_core.db.repositories import purge_scraped_text, stale_queued_runs
from deno_core.db.session import get_sessionmaker, session_scope
from deno_core.events import RunEvents
from deno_core.jobs import TASK_CONTENT_PLAN, TASK_PURGE_SCRAPED_TEXT, TASK_VALIDATION_RUN, get_broker
from deno_core.logging import configure_logging, get_logger
from deno_core.observability import init_sentry
from deno_core.runs import RunContext, execute_run
from deno_core.settings import get_settings

configure_logging()
log = get_logger(__name__)
init_sentry(get_settings(), "worker")

broker = get_broker()
if get_settings().environment != "test":
    from taskiq.middlewares.prometheus_middleware import PrometheusMiddleware

    broker.add_middlewares(PrometheusMiddleware(server_port=get_settings().worker_metrics_port))
scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])


_redis: Redis | None = None


def redis_client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().valkey_url)
    return _redis


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _startup(state: TaskiqState) -> None:
    redis_client()
    # The validation graph registers itself as the runner when its package is installed (Phase 8).
    try:
        from deno_graphs.validation.runner import register as register_graph
    except ImportError:
        log.warning("validation_graph_not_installed")
    else:
        register_graph()


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _shutdown(state: TaskiqState) -> None:
    if _redis is not None:
        await _redis.aclose()


@broker.task(task_name=TASK_VALIDATION_RUN)
async def run_validation(run_id: str, user_id: str) -> None:
    ctx = RunContext(
        run_id=uuid.UUID(run_id),
        user_id=uuid.UUID(user_id),
        events=RunEvents(redis_client()),
        sessionmaker=get_sessionmaker(),
    )
    await execute_run(ctx)


@broker.task(task_name=TASK_CONTENT_PLAN)
async def run_content_plan(plan_id: str, user_id: str) -> None:
    from deno_graphs.content.graph import run_content_plan as run_plan

    ctx = RunContext(
        run_id=uuid.UUID(plan_id),
        user_id=uuid.UUID(user_id),
        events=RunEvents(redis_client()),
        sessionmaker=get_sessionmaker(),
    )
    await run_plan(ctx)


@broker.task(task_name=TASK_PURGE_SCRAPED_TEXT, schedule=[{"cron": "17 3 * * *"}])
async def purge_old_scraped_text() -> int:
    async with session_scope() as session:
        purged = await purge_scraped_text(session, get_settings().scraped_text_retention_days)
    log.info("purged_scraped_text", documents=purged)
    return purged


@broker.task(task_name="maintenance.requeue_stale_runs", schedule=[{"cron": "* * * * *"}])
async def requeue_stale_runs() -> int:
    """Outbox repair: re-send runs whose enqueue was lost (API committed, broker call failed)."""
    async with session_scope() as session:
        stale = await stale_queued_runs(session)
    for run_id, user_id in stale:
        await run_validation.kiq(run_id=str(run_id), user_id=str(user_id))
    if stale:
        log.warning("requeued_stale_runs", count=len(stale))
    return len(stale)
