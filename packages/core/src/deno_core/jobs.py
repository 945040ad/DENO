"""Background job contract shared by the API (enqueues) and the worker (executes).

taskiq on Valkey Streams (ADR-004): acknowledged delivery. A job whose worker
dies is re-claimed by another worker after ``idle_timeout``, and graph runs
then resume from their LangGraph checkpoint (thread_id = run_id).
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from taskiq import AsyncBroker, InMemoryBroker
from taskiq.kicker import AsyncKicker
from taskiq.middlewares import SmartRetryMiddleware
from taskiq_redis import RedisStreamBroker

from deno_core.errors import RateLimited, UpstreamUnavailable
from deno_core.settings import get_settings

TASK_VALIDATION_RUN = "validation.run"
TASK_CONTENT_PLAN = "content.plan"
TASK_PURGE_SCRAPED_TEXT = "maintenance.purge_scraped_text"
TASK_REQUEUE_STALE_RUNS = "maintenance.requeue_stale_runs"
# The one-shot entrypoint a Cloud Run Job execution runs: `python -m deno_worker.run_once <task> <json kwargs>`.
RUN_ONCE_MODULE = "deno_worker.run_once"

# Longest a job may run before another worker re-claims it (validation p95 target is 4 min).
JOB_IDLE_TIMEOUT_MS = 15 * 60 * 1000

# Only transient failures are retried; everything else fails the run once.
RETRYABLE: tuple[type[BaseException], ...] = (UpstreamUnavailable, RateLimited, ConnectionError, TimeoutError)


def build_broker(url: str | None = None, *, in_memory: bool = False) -> AsyncBroker:
    broker: AsyncBroker
    if in_memory:
        broker = InMemoryBroker()
    else:
        broker = RedisStreamBroker(
            url=url or get_settings().valkey_url,
            queue_name="deno:jobs",
            consumer_group_name="deno-workers",
            idle_timeout=JOB_IDLE_TIMEOUT_MS,
            maxlen=10_000,
        )
    return broker.with_middlewares(
        SmartRetryMiddleware(
            default_retry_count=2,
            default_retry_label=True,
            use_jitter=True,
            use_delay_exponent=True,
            default_delay=5,
            max_delay_exponent=60,
            types_of_exceptions=RETRYABLE,
        )
    )


@lru_cache(maxsize=1)
def get_broker() -> AsyncBroker:
    return build_broker(in_memory=get_settings().environment == "test")


async def enqueue(task_name: str, broker: AsyncBroker | None = None, **kwargs: Any) -> str:
    """Send a job by name (the API never imports worker code). Returns the job id.

    With TASK_RUNNER=cloudrun_job the job becomes one Cloud Run Job execution instead
    of a queue message, so no worker has to stay running (docs/09 §4.1).
    """
    settings = get_settings()
    if broker is None and settings.task_runner == "cloudrun_job":
        from deno_core.gcp import run_cloud_run_job

        args = ["-m", RUN_ONCE_MODULE, task_name, json.dumps(kwargs, sort_keys=True)]
        return await run_cloud_run_job(settings.cloudrun_job, args)
    kicker: AsyncKicker[Any, Any] = AsyncKicker(task_name, broker or get_broker(), {})
    task = await kicker.kiq(**kwargs)
    return str(task.task_id)
