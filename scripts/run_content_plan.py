"""Generate a content plan from a finished validation run (real NIM, Postgres + Valkey).

    uv run python scripts/run_content_plan.py RUN_ID [--days 7] [--seed-demo]

--seed-demo adds a sample Story Bank entry and voice samples for that run's user (dev only).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from deno_core.db import models as m
from deno_core.db.enums import StoryCategory
from deno_core.db.repositories import UserScope
from deno_core.db.session import build_engine
from deno_core.events import RunEvents
from deno_core.runs import RunContext
from deno_core.settings import get_settings
from deno_graphs.content.graph import run_content_plan

DEMO_SAMPLES = [
    "We almost lost our biggest account last spring and nobody saw it coming. Their usage looked fine. What "
    "we missed was that their champion had left two months earlier and the new person never logged in. I now "
    "check who is actually using the product every Monday, not just how much.",
    "I spent three weekends building a churn dashboard nobody opened. The CS team kept their own spreadsheet "
    "because it had the notes from calls in it. Lesson learned: put the signal where people already work, "
    "don't make them visit a new tab.",
    "Hot take from someone who runs CS at a small startup: most health scores are vibes with extra steps. "
    "Ours had nine inputs and still flagged happy customers as at risk. We cut it to three and started "
    "trusting it again.",
    "Our support queue tells you more about churn than NPS ever did. When the same account opens four tickets "
    "about the same bug in a month, they're shopping for alternatives. We learned that the hard way twice.",
    "Small thing that worked for us: after every renewal call I write one line about what almost made them "
    "leave. After a year that doc was the best product roadmap input we had.",
]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--seed-demo", action="store_true")
    ap.add_argument(
        "--db",
        default=os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:54329/deno_test"),
    )
    args = ap.parse_args()
    settings = get_settings().model_copy(update={"database_url": args.db})
    engine = build_engine(args.db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s, s.begin():
        run = await s.get(m.ValidationRun, uuid.UUID(args.run_id))
        assert run is not None
        scope = UserScope(s, run.user_id)
        if args.seed_demo:
            for text in DEMO_SAMPLES:
                await scope.add_voice_sample(text)
            await scope.add_story(
                category=StoryCategory.SCAR,
                headline="Lost our biggest account after their champion left",
                details="Usage looked fine, but the champion had left two months earlier and the new admin never "
                "logged in. We found out at renewal. Since then I check active users per account every Monday.",
                numbers=["two months"],
                tags=["churn"],
            )
        plan = await scope.create_content_plan(run.project_id, run.id, args.days)
        user_id = run.user_id
    redis = Redis.from_url(settings.valkey_url)
    ctx = RunContext(run_id=plan.id, user_id=user_id, events=RunEvents(redis), sessionmaker=maker)
    summary = await run_content_plan(ctx, settings=settings)
    print("SUMMARY", summary)
    async with maker() as s:
        scope = UserScope(s, user_id)
        drafts = {d.brief_id: d for d in await scope.latest_drafts(plan.id)}
        gates = await scope.gate_results([d.id for d in drafts.values()])
        for b in await scope.list_briefs(plan.id):
            d = drafts.get(b.id)
            print(
                f"\n=== day {b.day} {b.platform.value} promo={b.is_promotional} hook={b.hook_formula}\nANGLE: {b.angle}"
            )
            if d:
                failing = [
                    (g.layer, [f.get("rule_id") for f in g.findings][:4]) for g in gates.get(d.id, []) if not g.passed
                ]
                print(f"STATUS: {d.status.value} v{d.version} failing={failing}\n{d.text}")
    await redis.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
