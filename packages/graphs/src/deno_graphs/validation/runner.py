"""Runs the validation graph for one run (the worker registers this as the run executor).

- Checkpoints to Postgres (``AsyncPostgresSaver``), thread id = ``validation_runs.thread_id``:
  a crashed/re-delivered run continues from its last completed node.
- A run paused at the review interrupt is resumed with the founder's flags.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator
from typing import Any

import openai
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import select

from deno_core.db import models as m
from deno_core.errors import UpstreamUnavailable
from deno_core.gcp import searxng_auth_headers
from deno_core.logging import get_logger
from deno_core.observability import RUN_SECONDS, RUNS
from deno_core.runs import RunContext, RunOutcome, register_runner
from deno_core.settings import Settings, get_settings
from deno_graphs.validation.graph import build_graph
from deno_graphs.validation.nodes import GraphDeps
from deno_llm import BudgetExceeded, build_stack
from deno_sources import ValkeyCache, build_fetcher
from deno_sources.registry import SourceConfig

log = get_logger(__name__)
_setup_done = False


def _psycopg_url(url: str) -> str:
    """SQLAlchemy URL -> libpq key=value conninfo.

    Parsed with SQLAlchemy (as the API does) rather than handed to libpq as a URI: libpq rejects
    passwords with unescaped ``?``, ``&`` or ``/``, which SQLAlchemy accepts.
    """
    from psycopg.conninfo import make_conninfo
    from sqlalchemy.engine import make_url

    u = make_url(url)
    params: dict[str, Any] = {
        "host": u.host,
        "port": u.port,
        "dbname": u.database,
        "user": u.username,
        "password": u.password,
    }
    params.update({k: v if isinstance(v, str) else v[-1] for k, v in u.query.items()})
    return make_conninfo("", **{k: v for k, v in params.items() if v is not None})


@contextlib.asynccontextmanager
async def checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver[Any]]:
    global _setup_done
    if not settings.database_url.startswith("postgresql"):
        yield InMemorySaver()
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row

    # prepare_threshold=None: works through Supabase's transaction pooler (PgBouncer).
    async with await AsyncConnection.connect(
        _psycopg_url(settings.database_url), autocommit=True, prepare_threshold=None, row_factory=dict_row
    ) as conn:
        saver = AsyncPostgresSaver(conn)
        if not _setup_done:
            await saver.setup()
            _setup_done = True
        yield saver


async def run_validation_graph(ctx: RunContext, *, settings: Settings | None = None) -> RunOutcome:
    started = time.monotonic()
    outcome = await _run(ctx, settings or get_settings())
    RUNS.labels(outcome.status).inc()
    if outcome.status != "failed":
        RUN_SECONDS.observe(time.monotonic() - started)
    return outcome


async def _run(ctx: RunContext, settings: Settings) -> RunOutcome:
    async with ctx.sessionmaker() as session:
        row = (
            await session.execute(
                select(m.ValidationRun, m.Project)
                .join(m.Project, m.Project.id == m.ValidationRun.project_id)
                .where(m.ValidationRun.id == ctx.run_id, m.ValidationRun.user_id == ctx.user_id)
            )
        ).one()
        run, project = row.tuple()
        thread_id, idea = run.thread_id, project.idea
        flagged = [
            str(cid)
            for cid in (
                await session.execute(
                    select(m.Claim.id).where(m.Claim.run_id == ctx.run_id, m.Claim.flagged_wrong.is_(True))
                )
            ).scalars()
        ]

    redis = ctx.events.redis
    fetcher = build_fetcher(
        SourceConfig(
            searxng_url=settings.searxng_url,
            robots_opt_in=settings.sources_robots_opt_in,
            user_agent=settings.sources_user_agent or None,
            searxng_headers=searxng_auth_headers(settings),
        ),
        cache=ValkeyCache(redis),
    )
    stack = build_stack(settings, redis)
    deps = GraphDeps(ctx=ctx, settings=settings, stack=stack, fetcher=fetcher)
    # max_concurrency bounds parallel source/analyst branches (DB connections, NIM rate limit).
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "deps": deps},
        "recursion_limit": 60,
        "max_concurrency": 8,
    }
    try:
        async with checkpointer(settings) as saver:
            graph = build_graph(saver)
            snapshot = await graph.aget_state(config)
            if snapshot.interrupts:
                await ctx.emit("log", message="Resuming after review.")
                payload: Any = Command(resume={"flagged_claim_ids": flagged})
            elif snapshot.next:
                await ctx.emit("log", message="Resuming from the last completed step.")
                payload = None
            else:
                payload = {"idea": idea}
            await graph.ainvoke(payload, config)
            final = await graph.aget_state(config)
    except BudgetExceeded:
        log.warning("run_budget_exceeded")
        return RunOutcome("failed", "llm_budget_exceeded")
    except (
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.RateLimitError,
        openai.InternalServerError,
    ) as exc:
        # Transient provider trouble: the job is retried and the graph resumes from its last checkpoint.
        raise UpstreamUnavailable(f"LLM provider unavailable: {type(exc).__name__}") from exc
    finally:
        await fetcher.aclose()
    if final.interrupts:
        await ctx.emit("interrupt", kind="review")
        return RunOutcome("awaiting_review")
    return RunOutcome("succeeded")


def register() -> None:
    register_runner(run_validation_graph)
