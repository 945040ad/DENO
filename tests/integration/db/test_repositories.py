"""Repository behaviour and tenant isolation against real Postgres + pgvector."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from deno_core.db import models as m
from deno_core.db.base import new_id
from deno_core.db.enums import Source, Stance, UsageKind, VerdictKind
from deno_core.db.repositories import UserScope, purge_by_takedown, purge_scraped_text
from deno_core.errors import Conflict, InvalidInput, NotFound

IDEA = "A tool that scores LinkedIn drafts for AI-sounding language before you post."


def users() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()


async def seed_run(scope: UserScope) -> tuple[m.Project, m.ValidationRun]:
    project = await scope.create_project(IDEA)
    run, _ = await scope.create_run(project.id)
    return project, run


async def seed_doc(
    scope: UserScope, run_id: uuid.UUID, url: str = "https://x.com/a/status/1", body: str = "I hate writing posts"
) -> uuid.UUID:
    doc_id, _ = await scope.add_document(
        run_id,
        source=Source.X,
        url=url,
        canonical_url=url,
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
        fetch_tier="syndication",
        raw_text=body,
        author_handle="a",
    )
    return doc_id


# ---- tenant isolation --------------------------------------------------------


async def test_foreign_ids_behave_like_missing_ones(session: AsyncSession) -> None:
    a_id, b_id = users()
    a, b = UserScope(session, a_id), UserScope(session, b_id)
    project, run = await seed_run(a)
    doc_id = await seed_doc(a, run.id)
    [chunk_id] = await a.add_chunks(doc_id, ["I hate writing posts"])

    with pytest.raises(NotFound):
        await b.get_project(project.id)
    with pytest.raises(NotFound):
        await b.get_run(run.id)
    with pytest.raises(NotFound):
        await b.create_run(project.id)
    with pytest.raises(NotFound):
        await b.add_document(
            run.id, source=Source.X, url="u", canonical_url="u", content_hash="h", fetch_tier="t", raw_text="x"
        )
    with pytest.raises(NotFound):
        await b.add_chunks(doc_id, ["injected"])
    with pytest.raises(NotFound):
        await b.update_project(project.id, title="pwned")
    with pytest.raises(NotFound):
        await b.delete_project(project.id)
    assert await b.get_chunks([chunk_id]) == []
    assert await b.list_documents(run.id) == []
    assert (await b.list_projects()).items == []
    assert (await a.get_project(project.id)).title.startswith("A tool")


async def test_scope_overrides_caller_supplied_owner(session: AsyncSession) -> None:
    a_id, b_id = users()
    scope = UserScope(session, a_id)
    project = await scope.create_project(IDEA)
    project.user_id = b_id  # a buggy caller trying to reassign ownership
    scope._add(project)
    await session.flush()
    assert (await session.get(m.Project, project.id)).user_id == a_id  # type: ignore[union-attr]


async def test_export_and_delete_only_touch_own_rows(session: AsyncSession) -> None:
    a_id, b_id = users()
    a, b = UserScope(session, a_id), UserScope(session, b_id)
    await a.ensure_profile("Ada")
    _, run_a = await seed_run(a)
    await seed_doc(a, run_a.id)
    _, run_b = await seed_run(b)
    await seed_doc(b, run_b.id)

    exported = await a.export()
    assert len(exported["projects"]) == 1
    assert all(row["user_id"] == str(a_id) for rows in exported.values() for row in rows)
    json.dumps(exported)  # serialisable as a download

    await a.delete_everything()
    await session.flush()
    assert (await a.list_projects()).items == []
    assert await session.get(m.Profile, a_id) is None
    assert len((await b.list_projects()).items) == 1
    assert len(await b.list_documents(run_b.id)) == 1


# ---- projects & runs ----------------------------------------------------------


async def test_idempotency_key_returns_same_run(session: AsyncSession) -> None:
    scope = UserScope(session, uuid.uuid4())
    p1 = await scope.create_project(IDEA)
    p2 = await scope.create_project(IDEA + " v2")
    run, created = await scope.create_run(p1.id, idempotency_key="k-1")
    again, created_again = await scope.create_run(p1.id, idempotency_key="k-1")
    assert created and not created_again and again.id == run.id
    assert run.thread_id == str(run.id)
    with pytest.raises(Conflict):
        await scope.create_run(p2.id, idempotency_key="k-1")
    assert await scope.count_active_runs() == 1


async def test_cursor_pagination_and_soft_delete(session: AsyncSession) -> None:
    scope = UserScope(session, uuid.uuid4())
    created = []
    for i in range(5):
        project = await scope.create_project(f"{IDEA} #{i}")
        # distinct timestamps so ordering is deterministic
        await session.execute(
            update(m.Project)
            .where(m.Project.id == project.id)
            .values(created_at=datetime.now(UTC) - timedelta(minutes=10 - i))
        )
        created.append(project.id)
    await session.flush()
    first = await scope.list_projects(limit=2)
    second = await scope.list_projects(limit=2, cursor=first.next_cursor)
    third = await scope.list_projects(limit=2, cursor=second.next_cursor)
    seen = [p.id for p in first.items + second.items + third.items]
    assert seen == list(reversed(created))
    assert third.next_cursor is None

    await scope.delete_project(created[0])
    assert created[0] not in [p.id for p in (await scope.list_projects(limit=10)).items]
    with pytest.raises(NotFound):
        await scope.get_project(created[0])
    with pytest.raises(InvalidInput):
        await scope.list_projects(cursor="garbage!!")


async def test_short_idea_rejected(session: AsyncSession) -> None:
    with pytest.raises(InvalidInput):
        await UserScope(session, uuid.uuid4()).create_project("  hi ")


# ---- evidence -------------------------------------------------------------------


async def test_documents_dedupe_per_run(session: AsyncSession) -> None:
    scope = UserScope(session, uuid.uuid4())
    _, run = await seed_run(scope)
    first = await seed_doc(scope, run.id)
    again, created = await scope.add_document(
        run.id,
        source=Source.X,
        url="https://x.com/a/status/1?s=20",
        canonical_url="https://x.com/a/status/1",
        content_hash="other",
        fetch_tier="oembed",
        raw_text="dup",
    )
    assert again == first and created is False
    assert len(await scope.list_documents(run.id)) == 1


async def test_vector_and_fulltext_search(session: AsyncSession) -> None:
    scope = UserScope(session, uuid.uuid4())
    _, run = await seed_run(scope)
    doc = await seed_doc(scope, run.id)

    def vec(hot: int) -> list[float]:
        v = [0.0] * m.EMBEDDING_DIM
        v[hot] = 1.0
        return v

    ids = await scope.add_chunks(doc, ["Writing LinkedIn posts takes me hours", "Pizza in Naples"], [vec(0), vec(1)])
    nearest = (
        await session.execute(
            select(m.Chunk.id)
            .where(m.Chunk.run_id == run.id)
            .order_by(m.Chunk.embedding.cosine_distance(vec(0)))
            .limit(1)
        )
    ).scalar_one()
    assert nearest == ids[0]
    fts = (
        (
            await session.execute(
                select(m.Chunk.id).where(m.Chunk.tsv.op("@@")(text("websearch_to_tsquery('english', 'writing posts')")))
            )
        )
        .scalars()
        .all()
    )
    assert fts == [ids[0]]


# ---- findings constraints -------------------------------------------------------


async def test_verdict_confidence_is_clamped_by_the_database(session: AsyncSession) -> None:
    scope = UserScope(session, uuid.uuid4())
    _, run = await seed_run(scope)
    scope._add(m.Verdict(id=new_id(), run_id=run.id, verdict=VerdictKind.BUILD, confidence=1.7))
    with pytest.raises(IntegrityError):
        await session.flush()


# ---- retention & takedown -------------------------------------------------------


async def test_purge_keeps_links_but_drops_text(session: AsyncSession) -> None:
    scope = UserScope(session, uuid.uuid4())
    _, run = await seed_run(scope)
    old = await seed_doc(scope, run.id, url="https://x.com/a/status/old", body="old pain quote")
    fresh = await seed_doc(scope, run.id, url="https://x.com/a/status/new", body="fresh pain quote")
    [old_chunk] = await scope.add_chunks(old, ["old pain quote"])
    claim = scope._add(
        m.Claim(id=new_id(), run_id=run.id, analyst="pain", text="People hate it", stance=Stance.SUPPORTS)
    )
    await session.flush()
    scope._add(m.Citation(id=new_id(), claim_id=claim.id, chunk_id=old_chunk, verified=True))
    await session.execute(
        update(m.SourceDocument)
        .where(m.SourceDocument.id == old)
        .values(fetched_at=datetime.now(UTC) - timedelta(days=91))
    )
    await session.flush()

    assert await purge_scraped_text(session, older_than_days=90) == 1
    old_doc = await session.get(m.SourceDocument, old, populate_existing=True)
    fresh_doc = await session.get(m.SourceDocument, fresh, populate_existing=True)
    assert old_doc is not None and old_doc.raw_text is None and old_doc.purged_at is not None
    assert old_doc.canonical_url.endswith("/old") and old_doc.content_hash
    assert fresh_doc is not None and fresh_doc.raw_text == "fresh pain quote"
    chunk = await session.get(m.Chunk, old_chunk, populate_existing=True)
    assert chunk is not None and chunk.text == ""
    assert len((await session.execute(select(m.Citation).where(m.Citation.claim_id == claim.id))).all()) == 1
    assert await purge_scraped_text(session, older_than_days=90) == 0  # idempotent


async def test_takedown_by_author_crosses_tenants(session: AsyncSession) -> None:
    a, b = UserScope(session, uuid.uuid4()), UserScope(session, uuid.uuid4())
    _, run_a = await seed_run(a)
    _, run_b = await seed_run(b)
    await seed_doc(a, run_a.id, url="https://x.com/Victim/status/1")
    await seed_doc(b, run_b.id, url="https://x.com/Victim/status/2")
    await session.execute(update(m.SourceDocument).values(author_handle="Victim"))
    assert await purge_by_takedown(session, author_handle="@victim") == 2
    with pytest.raises(InvalidInput):
        await purge_by_takedown(session)


# ---- usage ledger ----------------------------------------------------------------


async def test_usage_ledger_sums_per_user(session: AsyncSession) -> None:
    a, b = UserScope(session, uuid.uuid4()), UserScope(session, uuid.uuid4())
    since = datetime.now(UTC) - timedelta(days=1)
    await a.record_usage(UsageKind.VALIDATION_RUN)
    await a.record_usage(UsageKind.VALIDATION_RUN, units=2)
    await b.record_usage(UsageKind.VALIDATION_RUN)
    assert await a.usage_since(UsageKind.VALIDATION_RUN, since) == 3
    assert await b.usage_since(UsageKind.VALIDATION_RUN, since) == 1


# ---- row-level security (Supabase Data API path) ----------------------------------


async def test_rls_limits_authenticated_role_to_own_rows(session: AsyncSession) -> None:
    a_id, b_id = users()
    await UserScope(session, a_id).create_project(IDEA)
    await UserScope(session, b_id).create_project(IDEA)
    await session.flush()
    await session.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON public.projects TO authenticated"))

    await session.execute(text("SET LOCAL ROLE authenticated"))
    await session.execute(
        text("SELECT set_config('request.jwt.claims', :c, true)"), {"c": json.dumps({"sub": str(a_id)})}
    )
    owners = (await session.execute(text("SELECT user_id FROM public.projects"))).scalars().all()
    assert owners == [a_id]

    with pytest.raises(DBAPIError, match="row-level security"):
        async with session.begin_nested():
            await session.execute(
                text("INSERT INTO public.projects (id, user_id, title, idea) VALUES (:id, :uid, 't', 'idea text')"),
                {"id": new_id(), "uid": b_id},
            )
    await session.execute(text("RESET ROLE"))
