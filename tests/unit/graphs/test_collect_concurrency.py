"""Collection fans its searches out concurrently and degrades instead of failing closed.

Reddit issues queries x subreddits x 2 endpoint calls against Arctic Shift, which regularly takes
~9 s and answers 422 about half the time (measured 2026-10-22). Serially that cannot fit in the
180 s budget, which is why real ideas were ending as `insufficient_evidence`.
"""

import asyncio
import time

from deno_graphs.validation.nodes import run_searches
from deno_sources import AccessDenied, SourceUnavailable
from deno_sources.models import Post, SourceName


def post(url: str) -> Post:
    return Post(source=SourceName.REDDIT, url=url, canonical_url=url, text="body", tier="arctic_shift")


class FakeClient:
    """Records when each search started so overlap can be asserted."""

    def __init__(self, delay: float = 0.05, fail: Exception | None = None) -> None:
        self.delay, self.fail, self.started = delay, fail, []

    async def search(self, query: str, *, since: object, limit: int) -> list[Post]:
        self.started.append(time.monotonic())
        await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return [post(f"https://example.com/{query}")]


def jobs(client: object, queries: list[str], sub: str = "SaaS") -> list[tuple[str, object, str]]:
    return [(q, client, sub) for q in queries]


async def run(js: list[tuple[str, object, str]], *, budget: float = 30.0, concurrency: int = 5):  # type: ignore[no-untyped-def]
    return await run_searches(
        js, since=None, limit=10, deadline=time.monotonic() + budget, source_label="reddit", concurrency=concurrency
    )


async def test_searches_overlap_instead_of_queueing() -> None:
    client = FakeClient(delay=0.2)
    elapsed = time.monotonic()
    outcomes, errors = await run(jobs(client, ["a", "b", "c", "d", "e"]))
    elapsed = time.monotonic() - elapsed

    assert errors == []
    assert len(outcomes) == 5
    # Serially this would take 5 x 0.2 s; concurrently it is one delay plus scheduling overhead.
    assert elapsed < 0.5, f"searches did not overlap, took {elapsed:.2f}s"


async def test_results_keep_job_order() -> None:
    """MAX_POSTS_PER_SOURCE truncates the merged list, so ordering must not depend on who finishes first."""
    slow, fast = FakeClient(delay=0.2), FakeClient(delay=0.01)
    outcomes, _ = await run([("slow", slow, ""), ("fast", fast, "")])
    assert [q for q, _, _ in outcomes] == ["slow", "fast"]


async def test_concurrency_is_bounded() -> None:
    client = FakeClient(delay=0.1)
    await run(jobs(client, [str(i) for i in range(6)]), concurrency=2)
    # With 6 jobs at concurrency 2, the last start must come well after the first.
    assert client.started[-1] - client.started[0] >= 0.1


async def test_one_failing_search_does_not_sink_the_others() -> None:
    ok, broken = FakeClient(), FakeClient(fail=SourceUnavailable("upstream 503"))
    outcomes, errors = await run([("good", ok, ""), ("bad", broken, "")])
    assert outcomes[0][2] is not None and outcomes[1][2] is None
    assert errors == ["unavailable: upstream 503"]


async def test_failed_job_is_distinguishable_from_an_empty_one() -> None:
    """`None` means the search never produced an answer; `[]` means it ran and found nothing."""

    class Empty(FakeClient):
        async def search(self, query: str, *, since: object, limit: int) -> list[Post]:
            return []

    outcomes, errors = await run([("empty", Empty(), ""), ("bad", FakeClient(fail=RuntimeError()), "")])
    assert outcomes[0][2] == []
    assert outcomes[1][2] is None
    assert errors == ["error: RuntimeError"]


async def test_policy_block_stops_the_remaining_searches() -> None:
    """robots.txt applies to the whole host, so there is nothing to gain from the other queries."""
    blocked = FakeClient(delay=0.01, fail=AccessDenied("robots.txt disallows"))
    later = FakeClient(delay=0.01)
    outcomes, errors = await run([("first", blocked, ""), ("second", later, "")], concurrency=1)
    assert "blocked_by_policy" in errors
    assert outcomes[1][2] is None
    assert later.started == [], "a blocked host must not be queried again"


async def test_exhausted_budget_reports_timeout_without_searching() -> None:
    client = FakeClient()
    outcomes, errors = await run(jobs(client, ["a", "b"]), budget=1.0)  # under the 5 s floor
    assert errors == ["timeout", "timeout"]
    assert all(found is None for _, _, found in outcomes)
    assert client.started == []
