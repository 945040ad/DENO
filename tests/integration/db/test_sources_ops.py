"""Source health persistence and the takedown lifecycle against Postgres."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deno_core.db import models as m
from deno_core.db import repositories as repo
from deno_core.db.enums import Source, TakedownStatus
from deno_core.errors import Conflict, NotFound


async def test_source_health_accumulates_per_hour(session: AsyncSession) -> None:
    at = datetime(2026, 9, 24, 10, 17, tzinfo=UTC)
    snap = {"requests": 4, "successes": 3, "blocked": 0, "success_rate": 0.75, "p95_ms": 120}
    assert await repo.record_source_health(session, {"reddit": snap, "searxng": snap}, at=at) == 1
    await repo.record_source_health(session, {"reddit": {**snap, "p95_ms": 900}, "hn": {"requests": 0}}, at=at)
    await repo.record_source_health(session, {"reddit": snap}, at=at.replace(hour=11))
    rows = (
        (
            await session.execute(
                select(m.SourceHealth).where(m.SourceHealth.source == Source.REDDIT).order_by("window_start")
            )
        )
        .scalars()
        .all()
    )
    assert [(r.window_start.hour, r.requests, r.successes, r.p95_ms) for r in rows] == [
        (10, 8, 6, 900),
        (11, 4, 3, 120),
    ]


async def test_source_health_summary(session: AsyncSession) -> None:
    await repo.record_source_health(session, {"hn": {"requests": 10, "successes": 9, "p95_ms": 300}})
    summary = await repo.source_health_summary(session)
    assert summary["hn"]["success_rate"] == 0.9


async def test_takedown_lifecycle(session: AsyncSession) -> None:
    scope = repo.UserScope(session, uuid.uuid4())
    project = await scope.create_project("A tool that scores LinkedIn drafts for AI-sounding language.")
    run, _ = await scope.create_run(project.id)
    doc, _ = await scope.add_document(
        run.id,
        source=Source.X,
        url="https://x.com/victim/status/1",
        canonical_url="https://x.com/victim/status/1",
        raw_text="quote",
        content_hash="h1",
        fetch_tier="oembed",
    )
    request = await repo.create_takedown(
        session, url="https://x.com/victim/status/1", author_handle=None, reason="mine", contact=None
    )
    assert request.status == TakedownStatus.RECEIVED
    assert [t.id for t in await repo.list_takedowns(session, TakedownStatus.RECEIVED)] == [request.id]

    resolved, purged = await repo.resolve_takedown(session, request.id, approve=True)
    assert (resolved.status, purged) == (TakedownStatus.PROCESSED, 1)
    stored = await session.get(m.SourceDocument, doc, populate_existing=True)
    assert stored is not None and stored.raw_text is None
    with pytest.raises(Conflict):
        await repo.resolve_takedown(session, request.id, approve=False)
    with pytest.raises(NotFound):
        await repo.resolve_takedown(session, uuid.uuid4(), approve=True)
