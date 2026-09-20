"""Background job contract shared by the API (enqueues) and the worker (executes).

taskiq on Valkey Streams (ADR-004): acknowledged delivery. A job whose worker
dies is re-claimed by another worker after ``idle_timeout``, and graph runs
then resume from their LangGraph checkpoint (thread_id = run_id).
"""

from __future__ import annotations

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
    """Send a job by name (the API never imports worker code). Returns the job id."""
    kicker: AsyncKicker[Any, Any] = AsyncKicker(task_name, broker or get_broker(), {})
    task = await kicker.kiq(**kwargs)
    return str(task.task_id)
