"""Tiny async load test: N concurrent clients hammering read endpoints; prints status counts and latency.

uv run python scripts/load_test.py --base http://127.0.0.1:8001 --users 50 --requests 40
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from collections import Counter

import httpx


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--requests", type=int, default=40)
    args = ap.parse_args()
    async with httpx.AsyncClient(base_url=args.base, timeout=30) as c:
        projects = (await c.get("/api/v1/projects")).json()["items"]
        runs = (await c.get(f"/api/v1/projects/{projects[0]['id']}/runs")).json() if projects else []
    paths = ["/api/v1/projects", "/api/v1/billing", "/api/v1/me", "/healthz"]
    if runs:
        paths += [f"/api/v1/runs/{runs[0]['id']}/report", f"/api/v1/runs/{runs[0]['id']}/communities"]
    latencies: list[float] = []
    codes: Counter[int] = Counter()

    async def user(i: int) -> None:
        async with httpx.AsyncClient(base_url=args.base, timeout=30) as c:
            for j in range(args.requests):
                started = time.perf_counter()
                r = await c.get(paths[(i + j) % len(paths)])
                latencies.append((time.perf_counter() - started) * 1000)
                codes[r.status_code] += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(user(i) for i in range(args.users)))
    elapsed = time.perf_counter() - t0
    latencies.sort()
    print(
        f"{len(latencies)} requests in {elapsed:.1f}s ({len(latencies) / elapsed:.0f} rps) status={dict(codes)} "
        f"p50={statistics.median(latencies):.0f}ms p95={latencies[int(0.95 * (len(latencies) - 1))]:.0f}ms "
        f"max={latencies[-1]:.0f}ms"
    )


if __name__ == "__main__":
    asyncio.run(main())
