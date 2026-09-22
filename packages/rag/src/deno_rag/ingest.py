"""Posts → deduped source documents → chunks with embeddings."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from deno_core.db.enums import Source
from deno_core.db.repositories import UserScope
from deno_core.logging import get_logger
from deno_llm.retrieval_models import Embedder
from deno_rag.text import chunk, is_english, normalise
from deno_sources.models import Post
from deno_sources.normalize import content_hash

log = get_logger(__name__)
MIN_CHARS = 20


@dataclass
class IngestReport:
    received: int = 0
    stored: int = 0
    chunks: int = 0
    duplicates: int = 0
    skipped_language: int = 0
    skipped_empty: int = 0
    document_ids: list[uuid.UUID] = field(default_factory=list)


async def ingest_posts(scope: UserScope, run_id: uuid.UUID, posts: Sequence[Post], embedder: Embedder) -> IngestReport:
    """Normalise, drop non-English/empty, dedupe (content hash + canonical URL), chunk, embed, store.

    Embeddings are computed in batches after dedupe, so duplicates never cost a NIM request.
    """
    report = IngestReport(received=len(posts))
    seen_hashes = await scope.existing_hashes(run_id)
    seen_urls: set[str] = set()
    pending: list[tuple[Post, str, str]] = []
    for post in posts:
        body = normalise(post.text)
        if len(body) < MIN_CHARS:
            report.skipped_empty += 1
            continue
        if not is_english(body):
            report.skipped_language += 1
            continue
        digest = content_hash(body)
        if digest in seen_hashes or post.canonical_url in seen_urls:
            report.duplicates += 1
            continue
        seen_hashes.add(digest)
        seen_urls.add(post.canonical_url)
        pending.append((post, body, digest))

    stored: list[tuple[uuid.UUID, list[str]]] = []
    for post, body, digest in pending:
        doc_id, created = await scope.add_document(
            run_id,
            source=Source(post.source.value),
            url=post.url,
            canonical_url=post.canonical_url,
            content_hash=digest,
            fetch_tier=post.tier,
            raw_text=body,
            author_handle=post.author_handle,
            community=post.community,
            published_at=post.published_at,
            engagement=post.engagement.model_dump(exclude_none=True),
        )
        if not created:  # same canonical URL stored by an earlier batch of this run
            report.duplicates += 1
            continue
        pieces = chunk(f"{post.title}\n\n{body}" if post.title and post.title not in body else body)
        stored.append((doc_id, pieces))
        report.document_ids.append(doc_id)

    flat = [p for _, pieces in stored for p in pieces]
    vectors = await embedder.embed_documents(flat) if flat else []
    cursor = 0
    for doc_id, pieces in stored:
        await scope.add_chunks(doc_id, pieces, vectors[cursor : cursor + len(pieces)])
        cursor += len(pieces)
    report.stored, report.chunks = len(stored), len(flat)
    log.info(
        "rag_ingested",
        run_id=str(run_id),
        received=report.received,
        stored=report.stored,
        chunks=report.chunks,
        duplicates=report.duplicates,
    )
    return report
