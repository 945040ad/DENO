"""Retrieval eval: recall@10, MRR, nDCG@10 over the labelled set, against Postgres.

    uv run python evals/retrieval/run_eval.py            # offline: hashing embedder, no rerank (CI)
    uv run python evals/retrieval/run_eval.py --live     # NIM embeddings + rerank
    ... --update-baseline                                # write the result as the new baseline

Fails (exit 1) if any metric regresses by more than 5% against baseline.<mode>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from deno_core.db.repositories import UserScope
from deno_core.db.session import build_engine
from deno_core.settings import get_settings
from deno_llm import build_stack
from deno_llm.retrieval_models import HashingEmbedder, PassthroughReranker
from deno_rag import Retriever, ingest_posts
from deno_sources.models import Post, SourceName

HERE = Path(__file__).parent
DB = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:54329/deno_test")


def metrics(ranked: list[str], relevant: set[str], k: int = 10) -> dict[str, float]:
    top = ranked[:k]
    recall = len(set(top) & relevant) / len(relevant)
    mrr = next((1 / (i + 1) for i, d in enumerate(ranked) if d in relevant), 0.0)
    dcg = sum(1 / math.log2(i + 2) for i, d in enumerate(top) if d in relevant)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return {"recall@10": recall, "mrr": mrr, "ndcg@10": dcg / idcg}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()
    corpus = [json.loads(line) for line in (HERE / "corpus.jsonl").read_text().splitlines()]
    queries = [json.loads(line) for line in (HERE / "queries.jsonl").read_text().splitlines()]
    if args.live:
        stack = build_stack(get_settings())
        embedder, reranker = stack.embedder, stack.reranker
    else:
        embedder, reranker = HashingEmbedder(), PassthroughReranker()

    engine = build_engine(DB, pool_size=2, max_overflow=0)
    totals: dict[str, float] = {}
    latencies: list[float] = []
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        scope = UserScope(session, uuid.uuid4())
        project = await scope.create_project("Retrieval eval corpus")
        run, _ = await scope.create_run(project.id)
        posts = [
            Post(
                source=SourceName.REDDIT,
                url=f"https://eval.local/{c['id']}",
                canonical_url=f"https://eval.local/{c['id']}",
                text=c["text"],
                tier="eval",
            )
            for c in corpus
        ]
        await ingest_posts(scope, run.id, posts, embedder)
        retriever = Retriever(scope, embedder, reranker)
        for q in queries:
            started = time.perf_counter()
            hits = await retriever.retrieve(q["query"], run.id, top_n=10)
            latencies.append((time.perf_counter() - started) * 1000)
            for name, value in metrics([h.url.rsplit("/", 1)[-1] for h in hits], set(q["relevant"])).items():
                totals[name] = totals.get(name, 0.0) + value
        await trans.rollback()
    await engine.dispose()

    result = {k: round(v / len(queries), 4) for k, v in totals.items()}
    latencies.sort()
    result["p95_ms"] = round(latencies[int(0.95 * (len(latencies) - 1))])
    mode = "live" if args.live else "offline"
    print(json.dumps({"mode": mode, **result}, indent=2))
    baseline_path = HERE / f"baseline.{mode}.json"
    if args.update_baseline or not baseline_path.exists():
        baseline_path.write_text(json.dumps(result, indent=2) + "\n")
        return 0
    baseline = json.loads(baseline_path.read_text())
    regressed = [k for k in ("recall@10", "mrr", "ndcg@10") if result[k] < baseline[k] * 0.95]
    if regressed:
        print(f"REGRESSION vs baseline: {regressed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
