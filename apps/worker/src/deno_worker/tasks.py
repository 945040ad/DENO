"""Worker entrypoint: ``taskiq worker deno_worker.tasks:broker`` (+ ``taskiq scheduler deno_worker.tasks:scheduler``)."""

from __future__ import annotations

from redis.asyncio import Redis
from taskiq import TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource

from deno_core import maintenance
from deno_core.db.session import get_sessionmaker
from deno_core.jobs import (
    TASK_CONTENT_PLAN,
    TASK_PURGE_SCRAPED_TEXT,
    TASK_REQUEUE_STALE_RUNS,
    TASK_VALIDATION_RUN,
    get_broker,
)
from deno_core.logging import configure_logging, get_logger
from deno_core.observability import init_sentry
from deno_core.settings import get_settings
from deno_worker import handlers

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
    handlers.register_runners()


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _shutdown(state: TaskiqState) -> None:
    if _redis is not None:
        await _redis.aclose()


@broker.task(task_name=TASK_VALIDATION_RUN)
async def run_validation(run_id: str, user_id: str) -> None:
    await handlers.validation_run(redis_client(), run_id, user_id)


@broker.task(task_name=TASK_CONTENT_PLAN)
async def run_content_plan(plan_id: str, user_id: str) -> None:
    await handlers.content_plan(redis_client(), plan_id, user_id)


@broker.task(task_name=TASK_PURGE_SCRAPED_TEXT, schedule=[{"cron": "17 3 * * *"}])
async def purge_old_scraped_text() -> int:
    return await maintenance.purge_old_scraped_text(get_sessionmaker())


@broker.task(task_name=TASK_REQUEUE_STALE_RUNS, schedule=[{"cron": "* * * * *"}])
async def requeue_stale_runs() -> int:
    return await maintenance.requeue_stale_runs(get_sessionmaker())
