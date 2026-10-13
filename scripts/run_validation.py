"""Run one validation end to end from the command line (real sources, real NIM, Postgres + Valkey).

    uv run python scripts/run_validation.py "A tool that ..." [--db postgresql+asyncpg://...] [--no-review]

Prints live node/source events, then the report (verdict, signals, verified claims with URLs).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from deno_core.db.repositories import UserScope
from deno_core.db.session import build_engine
from deno_core.events import RunEvents
from deno_core.runs import RunContext, execute_run
from deno_core.settings import get_settings
from deno_graphs.validation import nodes
from deno_graphs.validation.runner import run_validation_graph


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("idea", nargs="?", default="")
    ap.add_argument("--resume", help="run id to resume from its checkpoint (resets a failed run to running)")
    ap.add_argument("--db", default=get_settings().database_url, help="defaults to DATABASE_URL (Supabase)")
    ap.add_argument("--no-review", action="store_true")
    args = ap.parse_args()

    settings = get_settings().model_copy(update={"database_url": args.db})
    engine = build_engine(args.db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    if args.resume:
        from sqlalchemy import update

        from deno_core.db import models as m
        from deno_core.db.enums import RunStatus

        async with maker() as s, s.begin():
            run = await s.get(m.ValidationRun, uuid.UUID(args.resume))
            assert run is not None
            user = run.user_id
            await s.execute(
                update(m.ValidationRun).where(m.ValidationRun.id == run.id).values(status=RunStatus.RUNNING)
            )
    else:
        user = uuid.uuid4()
        async with maker() as s, s.begin():
            scope = UserScope(s, user)
            await scope.ensure_profile()
            project = await scope.create_project(args.idea)
            run, _ = await scope.create_run(project.id)
    redis = Redis.from_url(settings.valkey_url)
    events = RunEvents(redis)
    ctx = RunContext(run_id=run.id, user_id=user, events=events, sessionmaker=maker)

    if args.no_review:
        orig = nodes.GraphDeps.__init__

        def no_review(self: nodes.GraphDeps, *a: object, **kw: object) -> None:
            orig(self, *a, **kw)  # type: ignore[arg-type]
            self.review_step = False

        nodes.GraphDeps.__init__ = no_review  # type: ignore[method-assign]

    follow_redis = Redis.from_url(settings.valkey_url)

    async def follow() -> None:
        async for ev in RunEvents(follow_redis).follow(str(run.id), after="0-0", block_ms=2000):
            if ev is None:
                continue
            print(f"  [{ev.type}] {json.dumps(ev.data, default=str)[:160]}", flush=True)
            if ev.is_terminal:
                return

    started = time.monotonic()
    follower = asyncio.create_task(follow())

    async def runner(c: RunContext):  # type: ignore[no-untyped-def]
        return await run_validation_graph(c, settings=settings)

    await execute_run(ctx, runner)
    await asyncio.sleep(1)
    follower.cancel()
    await follow_redis.aclose()
    print(f"\n=== finished in {time.monotonic() - started:.0f}s ===")
    async with maker() as s:
        scope = UserScope(s, user)
        r = await scope.get_run(run.id)
        print("status:", r.status, r.error_code)
        v = await scope.get_verdict(run.id)
        if v:
            print("VERDICT:", v.verdict, "confidence", v.confidence)
            print("reasons:", v.reasons)
            print("rationale:", v.rationale)
        for sig in await scope.list_signals(run.id):
            print(f"  signal {sig.name} = {sig.value}  ({sig.method})")
        for claim, cites in await scope.list_claims_with_evidence(run.id):
            print(f"- [{claim.analyst}/{claim.stance}] {claim.text}")
            for cit, _chunk, doc in cites:
                print(f"     {'✓' if cit.verified else '✗'} {cit.entailment_score} {doc.canonical_url}")
    await redis.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
