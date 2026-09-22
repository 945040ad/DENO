import math
from typing import Any

import pytest

from deno_llm.limiter import LocalLimiter
from deno_llm.retrieval_models import HashingEmbedder, NimEmbedder, NimReranker


async def test_local_limiter_spaces_requests() -> None:
    now = [0.0]
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    limiter = LocalLimiter(3, 60, clock=lambda: now[0], sleep=sleep)
    for _ in range(4):
        await limiter.acquire()
    assert len(slept) == 1 and slept[0] == pytest.approx(60.01)


async def test_hashing_embedder_is_deterministic_and_topical() -> None:
    e = HashingEmbedder(dim=512)
    q = await e.embed_query("customer churn is painful")
    near, far = await e.embed_documents(["our customer churn doubled", "pizza in naples"])

    def cos(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cos(q, near) > cos(q, far)
    assert math.isclose(sum(x * x for x in q), 1.0)
    assert q == await e.embed_query("customer churn is painful")


class CountingLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self) -> None:
        self.calls += 1


async def test_nim_embedder_batches_and_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = CountingLimiter()
    embedder = NimEmbedder(api_key="k", model="m", base_url="http://nim.invalid/v1", limiter=limiter)

    class Fake:
        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[float(len(t))] for t in texts]

        async def aembed_query(self, text: str) -> list[float]:
            return [0.0]

    embedder._client = Fake()  # type: ignore[assignment]
    out = await embedder.embed_documents([str(i) for i in range(70)])
    assert len(out) == 70 and limiter.calls == 3  # batches of 32
    await embedder.embed_query("q")
    assert limiter.calls == 4


async def test_nim_reranker_maps_indices(monkeypatch: pytest.MonkeyPatch) -> None:
    reranker = NimReranker(api_key="k", model="m", base_url="http://nim.invalid/v1", limiter=CountingLimiter())

    async def fake(self: Any, documents: list[Any], query: str) -> list[Any]:
        ranked = sorted(documents, key=lambda d: -len(d.page_content))[: self.top_n]
        for d in ranked:
            d.metadata["relevance_score"] = float(len(d.page_content))
        return ranked

    monkeypatch.setattr(type(reranker._client), "acompress_documents", fake)
    assert await reranker.rerank("q", ["a", "ccc", "bb"], top_n=2) == [(1, 3.0), (2, 2.0)]
    assert await reranker.rerank("q", [], top_n=2) == []
