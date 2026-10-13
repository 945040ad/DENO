"""Run one graph job, then exit: the Cloud Run Job entrypoint (docs/09 §4.1).

    python -m deno_worker.run_once validation.run '{"run_id": "...", "user_id": "..."}'

Exit code 0 when the run finished (including a run that ended as failed), 1 on a
transient error so Cloud Run retries the execution and the graph resumes from its
checkpoint, 2 on a bad invocation (no retry would help).
"""

from __future__ import annotations

import asyncio
import json
import sys

from redis.asyncio import Redis

from deno_core.db.session import get_engine
from deno_core.logging import configure_logging, get_logger
from deno_core.observability import init_sentry
from deno_core.settings import get_settings
from deno_worker.handlers import GRAPH_HANDLERS, register_runners

log = get_logger(__name__)


async def run(task: str, kwargs: dict[str, str]) -> None:
    register_runners()
    redis = Redis.from_url(get_settings().valkey_url)
    try:
        await GRAPH_HANDLERS[task](redis, **kwargs)
    finally:
        await redis.aclose()
        await get_engine().dispose()


def main(argv: list[str]) -> int:
    configure_logging()
    init_sentry(get_settings(), "worker")
    if len(argv) != 2 or argv[0] not in GRAPH_HANDLERS:
        log.error("run_once_bad_invocation", argv=argv, tasks=sorted(GRAPH_HANDLERS))
        return 2
    try:
        kwargs = json.loads(argv[1])
    except json.JSONDecodeError:
        log.error("run_once_bad_kwargs")
        return 2
    if not isinstance(kwargs, dict):
        log.error("run_once_bad_kwargs")
        return 2
    try:
        asyncio.run(run(argv[0], kwargs))
    except Exception:
        log.exception("run_once_transient_failure")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
