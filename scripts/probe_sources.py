"""Live smoke test of every source client (nightly in CI, non-blocking).

    uv run python scripts/probe_sources.py [--query "customer churn"] [--opt-in www.linkedin.com,cdn.syndication.twimg.com]

Exit code 0 when every source is healthy or degraded-with-fallback; 1 when a
source returns nothing and has no fallback. Prints per-source counts, tiers,
latency and access-policy blocks (robots.txt without opt-in counts as "blocked
by policy", not as a failure).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta

from deno_sources import AccessDenied, SourceConfig, SourceName, SourceUnavailable, build_clients, build_fetcher


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="customer churn")
    parser.add_argument("--subreddits", default="SaaS,startups")
    parser.add_argument("--searxng", default="http://127.0.0.1:8890")
    parser.add_argument("--opt-in", default="", help="comma-separated hosts the operator opts in despite robots.txt")
    args = parser.parse_args()

    config = SourceConfig(
        searxng_url=args.searxng,
        robots_opt_in={h.strip() for h in args.opt_in.split(",") if h.strip()},
        subreddits=[s.strip() for s in args.subreddits.split(",") if s.strip()],
    )
    fetcher = build_fetcher(config)
    clients = build_clients(config, fetcher)
    since = datetime.now(UTC) - timedelta(days=365)
    report: dict[str, dict[str, object]] = {}
    failed = False
    for name, client in clients.items():
        started = time.monotonic()
        try:
            posts = await client.search(args.query, since=since, limit=5 if name == SourceName.LINKEDIN_POSTS else 10)
            status = "ok" if posts else ("empty" if name == SourceName.TRENDS else "no_results")
            report[name] = {
                "status": status,
                "count": len(posts),
                "tiers": sorted({p.tier for p in posts}),
                "sample": posts[0].canonical_url if posts else None,
            }
            failed |= status == "no_results"
        except AccessDenied as exc:
            report[name] = {"status": "blocked_by_policy", "reason": str(exc)[:120]}
        except SourceUnavailable as exc:
            report[name] = {"status": "unavailable", "reason": str(exc)[:120]}
            failed = True
        report[name]["seconds"] = round(time.monotonic() - started, 1)
    report["_health"] = {k: v.snapshot() for k, v in fetcher.health.items()}  # type: ignore[assignment]
    await fetcher.aclose()
    print(json.dumps(report, indent=2, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
