"""Hybrid retrieval: pgvector top-k + Postgres FTS top-k → reciprocal-rank fusion → rerank."""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from deno_core.db.enums import Source
from deno_core.db.repositories import ChunkFilter, UserScope
from deno_core.logging import get_logger
from deno_llm.retrieval_models import Embedder, Reranker

log = get_logger(__name__)
RRF_K = 60


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    url: str
    source: Source
    text: str
    score: float
    author_handle: str | None
    community: str | None
    published_at: datetime | None
    engagement: dict[str, int]


def rrf(*rankings: Sequence[uuid.UUID], k: int = RRF_K) -> list[uuid.UUID]:
    """Reciprocal-rank fusion; ties keep first-seen order."""
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda i: -scores[i])


class Retriever:
    def __init__(self, scope: UserScope, embedder: Embedder, reranker: Reranker) -> None:
        self.scope, self.embedder, self.reranker = scope, embedder, reranker

    async def retrieve(self, query: str, run_id: uuid.UUID, **kw: Any) -> list[RetrievedChunk]:
        return await self.retrieve_many([query], run_id, **kw)

    async def retrieve_many(
        self,
        queries: Sequence[str],
        run_id: uuid.UUID,
        *,
        sources: Sequence[Source] | None = None,
        since: datetime | None = None,
        min_engagement: int | None = None,
        k: int = 50,
        rerank_pool: int = 40,
        top_n: int = 20,
    ) -> list[RetrievedChunk]:
        """All queries in one embed request; every dense and sparse ranking fused by RRF; one rerank call
        against the queries joined (the reranker sees the whole information need)."""
        started = time.perf_counter()
        flt = ChunkFilter(sources=sources, since=since, min_engagement=min_engagement)
        vectors = (
            await self.embedder.embed_queries(list(queries))
            if len(queries) > 1
            else [await self.embedder.embed_query(queries[0])]
        )
        rankings: list[list[uuid.UUID]] = []
        for query, vector in zip(queries, vectors, strict=True):
            rankings.append(await self.scope.vector_candidates(run_id, vector, k=k, flt=flt))
            rankings.append(await self.scope.fts_candidates(run_id, query, k=k, flt=flt))
        dense = [c for r in rankings[::2] for c in r]
        sparse = [c for r in rankings[1::2] for c in r]
        fused = rrf(*rankings)[:rerank_pool]
        rows = await self.scope.chunks_with_documents(fused)
        pool = [cid for cid in fused if cid in rows]
        ranked = await self.reranker.rerank(" ; ".join(queries), [rows[c][0].text for c in pool], top_n)
        out = []
        for index, score in ranked:
            chunk, doc = rows[pool[index]]
            out.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=doc.id,
                    url=doc.canonical_url,
                    source=doc.source,
                    text=chunk.text,
                    score=score,
                    author_handle=doc.author_handle,
                    community=doc.community,
                    published_at=doc.published_at,
                    engagement={k: int(v) for k, v in (doc.engagement or {}).items() if isinstance(v, int)},
                )
            )
        log.info(
            "rag_retrieved",
            run_id=str(run_id),
            dense=len(dense),
            sparse=len(sparse),
            returned=len(out),
            ms=round((time.perf_counter() - started) * 1000),
        )
        return out
