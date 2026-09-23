"""Validation eval (docs/08 Phase 8): runs the real graph on labelled ideas and reports

- junk_insufficient: share of junk ideas that end INSUFFICIENT_EVIDENCE (target ≥ 0.9)
- fabricated_urls: citations whose URL isn't a stored document of that run (target 0; structural)
- citation_verified_rate: verified citations / all citations on kept claims (judge precision proxy)
- verdict_agreement: good → build|pivot, dead → kill|pivot|insufficient (tracked, not gated)
- p95_seconds

    TEST_DATABASE_URL=...deno_dev uv run python evals/validation/run_eval.py [--label junk] [--limit N]

Results append to results.jsonl (one line per idea) so long runs can be resumed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from deno_core.db import models as m
from deno_core.db.repositories import UserScope
from deno_core.db.session import build_engine
from deno_core.errors import InvalidInput, UpstreamUnavailable
from deno_core.events import RunEvents
from deno_core.runs import RunContext, execute_run
from deno_core.settings import get_settings
from deno_graphs.validation import nodes
from deno_graphs.validation.runner import run_validation_graph

HERE = Path(__file__).parent
AGREES = {
    "good": {"build", "pivot"},
    "dead": {"kill", "pivot", "insufficient_evidence"},
    "junk": {"insufficient_evidence"},
}


async def one(maker: async_sessionmaker, redis: Redis, settings: object, idea: str) -> dict[str, object]:  # type: ignore[type-arg]
    user = uuid.uuid4()
    try:
        async with maker() as s, s.begin():
            scope = UserScope(s, user)
            await scope.ensure_profile()
            project = await scope.create_project(idea)
            run, _ = await scope.create_run(project.id)
    except InvalidInput:  # refused before any run: the honest outcome for junk
        return {
            "status": "rejected_input",
            "verdict": "insufficient_evidence",
            "confidence": 0.0,
            "citations": 0,
            "verified_citations": 0,
            "fabricated_urls": 0,
            "had_evidence": False,
            "seconds": 0.0,
        }
    ctx = RunContext(run_id=run.id, user_id=user, events=RunEvents(redis), sessionmaker=maker)
    started = time.monotonic()

    async def runner(c: RunContext):  # type: ignore[no-untyped-def]
        return await run_validation_graph(c, settings=settings)  # type: ignore[arg-type]

    for attempt in range(3):  # transient NIM errors: resume from the checkpoint, like the job queue does
        try:
            await execute_run(ctx, runner)
            break
        except UpstreamUnavailable:
            if attempt == 2:
                raise
            await asyncio.sleep(30)
    seconds = time.monotonic() - started
    async with maker() as s:
        scope = UserScope(s, user)
        r = await scope.get_run(run.id)
        verdict = await scope.get_verdict(run.id)
        doc_urls = {d.canonical_url for d in await scope.list_documents(run.id)}
        claims = await scope.list_claims_with_evidence(run.id)
        cites = [(c, doc) for _, cs in claims for c, _chunk, doc in cs]
        fabricated = sum(1 for _, doc in cites if doc.canonical_url not in doc_urls)
        verified = sum(1 for c, _ in cites if c.verified)
        chunks_ok = (await s.execute(select(m.Chunk.id).where(m.Chunk.run_id == run.id).limit(1))).first() is not None
    return {
        "status": r.status.value,
        "verdict": verdict.verdict.value if verdict else None,
        "confidence": verdict.confidence if verdict else None,
        "citations": len(cites),
        "verified_citations": verified,
        "fabricated_urls": fabricated,
        "had_evidence": chunks_ok,
        "seconds": round(seconds, 1),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", choices=["good", "dead", "junk"])
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()
    db = os.environ["TEST_DATABASE_URL"]
    settings = get_settings().model_copy(update={"database_url": db})
    orig = nodes.GraphDeps.__init__

    def no_review(self: nodes.GraphDeps, *a: object, **kw: object) -> None:
        orig(self, *a, **kw)  # type: ignore[arg-type]
        self.review_step = False

    nodes.GraphDeps.__init__ = no_review  # type: ignore[method-assign]
    engine = build_engine(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(settings.valkey_url)
    results_path = HERE / "results.jsonl"
    done = (
        {json.loads(line)["idea"] for line in results_path.read_text().splitlines()} if results_path.exists() else set()
    )
    ideas = [json.loads(line) for line in (HERE / "ideas.jsonl").read_text().splitlines()]
    todo = [i for i in ideas if (not args.label or i["label"] == args.label) and i["idea"] not in done][: args.limit]
    for item in todo:
        res = await one(maker, redis, settings, item["idea"])
        row = {**item, **res, "agrees": res["verdict"] in AGREES[item["label"]]}
        with results_path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)
    await redis.aclose()
    await engine.dispose()
    summarize(results_path)


def summarize(path: Path) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    junk = [r for r in rows if r["label"] == "junk"]
    real = [r for r in rows if r["label"] != "junk"]
    cites = sum(r["citations"] for r in rows)
    secs = sorted(r["seconds"] for r in real) or [0]
    print(
        json.dumps(
            {
                "ideas": len(rows),
                "junk_insufficient": round(sum(r["verdict"] == "insufficient_evidence" for r in junk) / len(junk), 3)
                if junk
                else None,
                "fabricated_urls": sum(r["fabricated_urls"] for r in rows),
                "citation_verified_rate": round(sum(r["verified_citations"] for r in rows) / cites, 3)
                if cites
                else None,
                "verdict_agreement": round(sum(r["agrees"] for r in real) / len(real), 3) if real else None,
                "failed_runs": sum(r["status"] == "failed" for r in rows),
                "p95_seconds": secs[int(0.95 * (len(secs) - 1))],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
