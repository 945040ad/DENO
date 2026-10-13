"""Embedding and rerank clients (ADR-007) behind small protocols so tests and evals can swap them."""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import math
import re
from collections.abc import Sequence
from typing import NoReturn, Protocol

from langchain_core.documents import Document
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings, NVIDIARerank

from deno_core.errors import RateLimited, UpstreamUnavailable
from deno_core.logging import get_logger
from deno_llm.limiter import Limiter, NullLimiter

log = get_logger(__name__)

_NIM_STATUS = re.compile(r"^\[(\d{3})\]")


def _raise_nim(exc: Exception) -> NoReturn:
    """NIM's LangChain client raises bare ``Exception("[502] Bad Gateway…")``. Re-raise 429/5xx as the errors
    the run executor retries (the graph resumes from its checkpoint); anything else unchanged."""
    m = _NIM_STATUS.match(str(exc))
    status = int(m.group(1)) if m else 0
    if status == 429:
        raise RateLimited(f"NIM {status}") from exc
    if status >= 500:
        raise UpstreamUnavailable(f"NIM {status}") from exc
    raise exc


EMBED_BATCH = 32
RERANK_BATCH = 64
RERANK_ATTEMPTS = 3


class Embedder(Protocol):
    dim: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, texts: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        """(index into ``texts``, score), best first."""
        ...


class NimEmbedder:
    def __init__(
        self, *, api_key: str, model: str, base_url: str, limiter: Limiter | None = None, dim: int = 2048
    ) -> None:
        self._client = NVIDIAEmbeddings(model=model, api_key=api_key, base_url=base_url, truncate="END")
        self._limiter = limiter or NullLimiter()
        self.dim = dim

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            await self._limiter.acquire()
            try:
                out.extend(await self._client.aembed_documents(list(texts[start : start + EMBED_BATCH])))
            except Exception as exc:
                _raise_nim(exc)
        return out

    async def embed_query(self, text: str) -> list[float]:
        await self._limiter.acquire()
        try:
            return await self._client.aembed_query(text)
        except Exception as exc:
            _raise_nim(exc)

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Several queries in one request (query-side embedding)."""
        out: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            await self._limiter.acquire()
            try:
                out.extend(await self._client._aembed(list(texts[start : start + EMBED_BATCH]), model_type="query"))
            except Exception as exc:
                _raise_nim(exc)
        return out


class NimReranker:
    def __init__(self, *, api_key: str, model: str, base_url: str, limiter: Limiter | None = None) -> None:
        self._client = NVIDIARerank(
            model=model, api_key=api_key, base_url=base_url, truncate="END", max_batch_size=RERANK_BATCH
        )
        self._limiter = limiter or NullLimiter()

    async def rerank(self, query: str, texts: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        if not texts:
            return []
        docs = [Document(page_content=t, metadata={"i": i}) for i, t in enumerate(texts)]
        client = self._client.model_copy(update={"top_n": min(top_n, len(texts))})
        for attempt in range(RERANK_ATTEMPTS):
            for _ in range(0, len(texts), RERANK_BATCH):
                await self._limiter.acquire()
            try:
                ranked = await client.acompress_documents(documents=docs, query=query)
            except Exception as exc:  # NIM raises bare Exception("[502] Bad Gateway…") for HTTP errors
                log.warning("rerank_failed", attempt=attempt + 1, error=str(exc)[:200])
                if attempt + 1 < RERANK_ATTEMPTS:
                    await asyncio.sleep(2**attempt)
                continue
            return [(int(d.metadata["i"]), float(d.metadata.get("relevance_score", 0.0))) for d in ranked]
        # Reranking only refines an order that hybrid retrieval already fused (RRF), so an upstream outage
        # degrades quality instead of failing the run: keep the fused order.
        log.warning("rerank_fallback_fused_order", candidates=len(texts))
        n = min(top_n, len(texts))
        return [(i, 1.0 - i / n) for i in range(n)]


# ---- offline stand-ins (unit tests, CI evals) ------------------------------------

_WORD = re.compile(r"[a-z0-9']+")


class HashingEmbedder:
    """Deterministic bag-of-words vectors (hashed unigrams + bigrams, L2-normalised). No network."""

    def __init__(self, dim: int = 2048) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        words = _WORD.findall(text.lower())
        v = [0.0] * self.dim
        for gram in [*words, *(f"{a} {b}" for a, b in itertools.pairwise(words))]:
            h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0 if (h >> 63) else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class PassthroughReranker:
    """Keeps the fused order."""

    async def rerank(self, query: str, texts: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        return [(i, 1.0 / (i + 1)) for i in range(min(top_n, len(texts)))]
