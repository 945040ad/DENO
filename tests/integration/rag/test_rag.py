"""Ingest + hybrid retrieval against Postgres + pgvector, with offline embedder/reranker."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from deno_core.db.enums import Source
from deno_core.db.repositories import UserScope
from deno_llm.retrieval_models import HashingEmbedder, PassthroughReranker
from deno_rag import Retriever, ingest_posts
from deno_sources.models import Engagement, Post, SourceName

IDEA = "A tool that predicts SaaS customer churn from support tickets."


def post(n: int, text: str, *, source: SourceName = SourceName.REDDIT, likes: int = 0, year: int = 2026) -> Post:
    url = f"https://www.reddit.com/r/SaaS/comments/{n}"
    return Post(
        source=source,
        url=url,
        canonical_url=url,
        text=text,
        tier="arctic_shift",
        published_at=datetime(year, 3, 1, tzinfo=UTC),
        engagement=Engagement(score=likes),
    )


CORPUS = [
    post(
        1,
        "Customer churn is killing our SaaS, we lose 8% of accounts every month and support tickets pile up",
        likes=40,
    ),
    post(2, "Our churn problem: customers leave silently after a few angry support tickets", likes=5),
    post(3, "Best pizza place in Naples? I am visiting for a week with my family", likes=90),
    post(4, "We hired a new designer and the onboarding flow looks great now", likes=3),
    post(
        5,
        "Is there a tool that predicts churn before the customer cancels their subscription?",
        source=SourceName.HN,
        likes=12,
        year=2024,
    ),
]


async def seeded(session: AsyncSession) -> tuple[UserScope, uuid.UUID]:
    scope = UserScope(session, uuid.uuid4())
    project = await scope.create_project(IDEA)
    run, _ = await scope.create_run(project.id)
    return scope, run.id


async def test_ingest_dedupes_and_skips_noise(session: AsyncSession) -> None:
    scope, run_id = await seeded(session)
    dupe_text = post(6, CORPUS[0].text.upper() + "  ")
    german = post(7, "Wir verlieren jeden Monat Kunden und niemand weiß warum das passiert ist")
    report = await ingest_posts(scope, run_id, [*CORPUS, dupe_text, german, post(8, "[deleted]")], HashingEmbedder())
    assert (report.stored, report.duplicates, report.skipped_language, report.skipped_empty) == (5, 1, 1, 1)
    again = await ingest_posts(scope, run_id, CORPUS, HashingEmbedder())
    assert again.stored == 0 and again.duplicates == 5


async def test_hybrid_retrieval_ranks_relevant_first_and_filters(session: AsyncSession) -> None:
    scope, run_id = await seeded(session)
    await ingest_posts(scope, run_id, CORPUS, HashingEmbedder())
    retriever = Retriever(scope, HashingEmbedder(), PassthroughReranker())

    hits = await retriever.retrieve("customer churn support tickets", run_id, top_n=3)
    assert {h.url.rsplit("/", 1)[-1] for h in hits[:2]} == {"1", "2"}
    assert hits[0].source == Source.REDDIT and hits[0].text

    only_hn = await retriever.retrieve("churn", run_id, sources=[Source.HN])
    assert [h.url.rsplit("/", 1)[-1] for h in only_hn] == ["5"]
    recent = await retriever.retrieve("churn", run_id, since=datetime(2025, 1, 1, tzinfo=UTC))
    assert "5" not in {h.url.rsplit("/", 1)[-1] for h in recent}
    popular = await retriever.retrieve("churn", run_id, min_engagement=10)
    assert {h.url.rsplit("/", 1)[-1] for h in popular} <= {"1", "3", "5"}


async def test_retrieval_never_crosses_tenants(session: AsyncSession) -> None:
    alice, alice_run = await seeded(session)
    bob, _ = await seeded(session)
    await ingest_posts(alice, alice_run, CORPUS, HashingEmbedder())
    # Bob asks about Alice's run id directly: nothing comes back.
    hits = await Retriever(bob, HashingEmbedder(), PassthroughReranker()).retrieve("churn", alice_run)
    assert hits == []
