"""Repositories. Tenant data is only reachable through a ``UserScope``.

Every read and write on a tenant table is filtered by the scope's
``user_id`` *here*, so API routes and graph nodes never build their own
queries against tenant tables. A foreign id behaves exactly like a missing
one (``NotFound``), which is what the API turns into a 404.
"""

from __future__ import annotations

import base64
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import ColumnElement, Select, delete, func, literal, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from deno_core.db import models as m
from deno_core.db.base import Base, new_id
from deno_core.db.enums import (
    DraftStatus,
    Platform,
    ProjectStatus,
    RunStatus,
    Source,
    Stance,
    StoryCategory,
    TakedownStatus,
    UsageKind,
    VerdictKind,
)
from deno_core.errors import Conflict, InvalidInput, NotFound

T = TypeVar("T", bound=Base)

ACTIVE_RUN_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.AWAITING_REVIEW)


_FTS_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ChunkFilter:
    sources: Sequence[Source] | None = None
    since: datetime | None = None
    min_engagement: int | None = None


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None


def _encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{row_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(created), uuid.UUID(row_id)
    except ValueError as exc:
        raise InvalidInput("Invalid cursor.") from exc


class UserScope:
    """All tenant access for one user, inside one session/transaction."""

    def __init__(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id

    # ---- generic helpers -------------------------------------------------

    def _owned(self, model: type[T]) -> Select[tuple[T]]:
        return select(model).where(model.user_id == self.user_id)  # type: ignore[attr-defined]

    async def _get(self, model: type[T], row_id: uuid.UUID) -> T:
        row = (await self.session.execute(self._owned(model).where(model.id == row_id))).scalar_one_or_none()  # type: ignore[attr-defined]
        if row is None:
            raise NotFound()
        return row

    def _add(self, obj: T) -> T:
        obj.user_id = self.user_id  # type: ignore[attr-defined]  # never trust a caller-provided owner
        self.session.add(obj)
        return obj

    # ---- profile -----------------------------------------------------------

    async def ensure_profile(self, display_name: str | None = None) -> m.Profile:
        await self.session.execute(
            insert(m.Profile).values(id=self.user_id, display_name=display_name).on_conflict_do_nothing()
        )
        profile = await self.session.get(m.Profile, self.user_id)
        if profile is None:  # pragma: no cover — the upsert above guarantees the row
            raise NotFound()
        return profile

    # ---- projects ----------------------------------------------------------

    async def create_project(self, idea: str, author_handle: str | None = None) -> m.Project:
        idea = idea.strip()
        if sum(not c.isspace() for c in idea) < 5:
            raise InvalidInput("Describe the idea in a sentence or more.")
        title = idea.splitlines()[0][:120]
        project = self._add(m.Project(id=new_id(), title=title, idea=idea, author_handle=author_handle))
        await self.session.flush()
        return project

    async def get_project(self, project_id: uuid.UUID) -> m.Project:
        project = await self._get(m.Project, project_id)
        if project.deleted_at is not None:
            raise NotFound()
        return project

    async def list_projects(self, limit: int = 20, cursor: str | None = None) -> Page[m.Project]:
        limit = max(1, min(limit, 100))
        stmt = self._owned(m.Project).where(m.Project.deleted_at.is_(None))
        if cursor:
            created, row_id = _decode_cursor(cursor)
            stmt = stmt.where(tuple_(m.Project.created_at, m.Project.id) < tuple_(literal(created), literal(row_id)))
        stmt = stmt.order_by(m.Project.created_at.desc(), m.Project.id.desc()).limit(limit + 1)
        rows = list((await self.session.execute(stmt)).scalars())
        more = len(rows) > limit
        items = rows[:limit]
        return Page(items, _encode_cursor(items[-1].created_at, items[-1].id) if more else None)

    async def update_project(
        self, project_id: uuid.UUID, *, title: str | None = None, status: ProjectStatus | None = None
    ) -> m.Project:
        project = await self.get_project(project_id)
        if title is not None:
            project.title = title.strip()[:200] or project.title
        if status is not None:
            project.status = status
        await self.session.flush()
        return project

    async def delete_project(self, project_id: uuid.UUID) -> None:
        project = await self.get_project(project_id)
        project.deleted_at = datetime.now(UTC)
        await self.session.flush()

    # ---- runs ---------------------------------------------------------------

    async def create_run(
        self, project_id: uuid.UUID, idempotency_key: str | None = None
    ) -> tuple[m.ValidationRun, bool]:
        """Returns (run, created). The same idempotency key returns the existing run."""
        await self.get_project(project_id)
        if idempotency_key:
            existing = await self.find_run_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.project_id != project_id:
                    raise Conflict("That idempotency key was used for another project.")
                return existing, False
        run_id = new_id()
        run = self._add(
            m.ValidationRun(id=run_id, project_id=project_id, thread_id=str(run_id), idempotency_key=idempotency_key)
        )
        await self.session.flush()
        return run, True

    async def find_run_by_idempotency_key(self, key: str) -> m.ValidationRun | None:
        stmt = self._owned(m.ValidationRun).where(m.ValidationRun.idempotency_key == key)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_run(self, run_id: uuid.UUID) -> m.ValidationRun:
        return await self._get(m.ValidationRun, run_id)

    async def list_runs(self, project_id: uuid.UUID) -> list[m.ValidationRun]:
        await self.get_project(project_id)
        stmt = (
            self._owned(m.ValidationRun)
            .where(m.ValidationRun.project_id == project_id)
            .order_by(m.ValidationRun.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def count_active_runs(self) -> int:
        stmt = (
            select(func.count())
            .select_from(m.ValidationRun)
            .where(m.ValidationRun.user_id == self.user_id, m.ValidationRun.status.in_(ACTIVE_RUN_STATUSES))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # ---- evidence -----------------------------------------------------------

    async def add_document(
        self,
        run_id: uuid.UUID,
        *,
        source: Source,
        url: str,
        canonical_url: str,
        content_hash: str,
        fetch_tier: str,
        raw_text: str | None,
        author_handle: str | None = None,
        community: str | None = None,
        published_at: datetime | None = None,
        engagement: dict[str, Any] | None = None,
    ) -> tuple[uuid.UUID, bool]:
        """Insert a document once per (run, canonical_url). Returns (id, created)."""
        await self.get_run(run_id)
        doc_id = new_id()
        stmt = (
            insert(m.SourceDocument)
            .values(
                id=doc_id,
                user_id=self.user_id,
                run_id=run_id,
                source=source,
                url=url,
                canonical_url=canonical_url,
                content_hash=content_hash,
                fetch_tier=fetch_tier,
                raw_text=raw_text,
                author_handle=author_handle,
                community=community,
                published_at=published_at,
                engagement=engagement or {},
            )
            .on_conflict_do_nothing(constraint="uq_source_documents_run_url")
            .returning(m.SourceDocument.id)
        )
        inserted = (await self.session.execute(stmt)).scalar_one_or_none()
        if inserted is not None:
            return inserted, True
        existing = (
            await self.session.execute(
                select(m.SourceDocument.id).where(
                    m.SourceDocument.user_id == self.user_id,
                    m.SourceDocument.run_id == run_id,
                    m.SourceDocument.canonical_url == canonical_url,
                )
            )
        ).scalar_one()
        return existing, False

    async def add_chunks(
        self, document_id: uuid.UUID, texts: Sequence[str], embeddings: Sequence[Sequence[float] | None] | None = None
    ) -> list[uuid.UUID]:
        doc = await self._get(m.SourceDocument, document_id)
        ids: list[uuid.UUID] = []
        for ordinal, chunk_text in enumerate(texts):
            vector = embeddings[ordinal] if embeddings else None
            chunk = self._add(
                m.Chunk(
                    id=new_id(),
                    document_id=doc.id,
                    run_id=doc.run_id,
                    ordinal=ordinal,
                    text=chunk_text,
                    embedding=list(vector) if vector is not None else None,
                )
            )
            ids.append(chunk.id)
        await self.session.flush()
        return ids

    async def list_documents(self, run_id: uuid.UUID, source: Source | None = None) -> list[m.SourceDocument]:
        stmt = self._owned(m.SourceDocument).where(m.SourceDocument.run_id == run_id)
        if source is not None:
            stmt = stmt.where(m.SourceDocument.source == source)
        return list((await self.session.execute(stmt.order_by(m.SourceDocument.fetched_at))).scalars())

    async def get_chunks(self, chunk_ids: Sequence[uuid.UUID]) -> list[m.Chunk]:
        if not chunk_ids:
            return []
        stmt = self._owned(m.Chunk).where(m.Chunk.id.in_(list(chunk_ids)))
        return list((await self.session.execute(stmt)).scalars())

    async def existing_hashes(self, run_id: uuid.UUID) -> set[str]:
        stmt = select(m.SourceDocument.content_hash).where(
            m.SourceDocument.user_id == self.user_id, m.SourceDocument.run_id == run_id
        )
        return set((await self.session.execute(stmt)).scalars())

    def _chunk_query(self, run_id: uuid.UUID, flt: ChunkFilter | None) -> Select[tuple[uuid.UUID]]:
        stmt = (
            select(m.Chunk.id)
            .join(m.SourceDocument, m.SourceDocument.id == m.Chunk.document_id)
            .where(m.Chunk.user_id == self.user_id, m.Chunk.run_id == run_id, m.Chunk.text != "")
        )
        if flt is None:
            return stmt
        if flt.sources:
            stmt = stmt.where(m.SourceDocument.source.in_(list(flt.sources)))
        if flt.since is not None:
            stmt = stmt.where(m.SourceDocument.published_at >= flt.since)
        if flt.min_engagement:
            eng = m.SourceDocument.engagement
            score = func.coalesce(eng["score"].as_integer(), eng["likes"].as_integer(), eng["comments"].as_integer(), 0)
            stmt = stmt.where(score >= flt.min_engagement)
        return stmt

    async def vector_candidates(
        self, run_id: uuid.UUID, embedding: Sequence[float], *, k: int = 50, flt: ChunkFilter | None = None
    ) -> list[uuid.UUID]:
        """Nearest chunks by cosine distance (HNSW, iterative scan so filters don't starve results)."""
        await self.session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        stmt = (
            self._chunk_query(run_id, flt)
            .where(m.Chunk.embedding.is_not(None))
            .order_by(m.Chunk.embedding.cosine_distance(list(embedding)))
            .limit(k)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def fts_candidates(
        self, run_id: uuid.UUID, query: str, *, k: int = 50, flt: ChunkFilter | None = None
    ) -> list[uuid.UUID]:
        """Full-text matches ranked by ts_rank_cd. OR semantics: any query word can match."""
        words = [w for w in _FTS_WORD.findall(query.lower()) if len(w) > 2][:32]
        if not words:
            return []
        tsq = func.to_tsquery("english", " | ".join(words))
        stmt = (
            self._chunk_query(run_id, flt)
            .where(m.Chunk.tsv.op("@@")(tsq))
            .order_by(func.ts_rank_cd(m.Chunk.tsv, tsq, 32).desc(), m.Chunk.id)
            .limit(k)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def chunks_with_documents(
        self, chunk_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[m.Chunk, m.SourceDocument]]:
        if not chunk_ids:
            return {}
        stmt = (
            select(m.Chunk, m.SourceDocument)
            .join(m.SourceDocument, m.SourceDocument.id == m.Chunk.document_id)
            .where(m.Chunk.user_id == self.user_id, m.Chunk.id.in_(list(chunk_ids)))
        )
        return {c.id: (c, d) for c, d in (await self.session.execute(stmt)).tuples()}

    async def list_evidence(
        self, run_id: uuid.UUID, *, source: Source | None = None, limit: int = 50, cursor: str | None = None
    ) -> Page[m.SourceDocument]:
        await self.get_run(run_id)
        limit = max(1, min(limit, 100))
        stmt = self._owned(m.SourceDocument).where(m.SourceDocument.run_id == run_id)
        if source is not None:
            stmt = stmt.where(m.SourceDocument.source == source)
        if cursor:
            fetched, row_id = _decode_cursor(cursor)
            stmt = stmt.where(
                tuple_(m.SourceDocument.fetched_at, m.SourceDocument.id) > tuple_(literal(fetched), literal(row_id))
            )
        stmt = stmt.order_by(m.SourceDocument.fetched_at, m.SourceDocument.id).limit(limit + 1)
        rows = list((await self.session.execute(stmt)).scalars())
        items = rows[:limit]
        more = len(rows) > limit
        return Page(items, _encode_cursor(items[-1].fetched_at, items[-1].id) if more else None)

    # ---- findings ---------------------------------------------------------------

    async def get_verdict(self, run_id: uuid.UUID) -> m.Verdict | None:
        await self.get_run(run_id)
        stmt = self._owned(m.Verdict).where(m.Verdict.run_id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_signals(self, run_id: uuid.UUID) -> list[m.Signal]:
        stmt = self._owned(m.Signal).where(m.Signal.run_id == run_id).order_by(m.Signal.name)
        return list((await self.session.execute(stmt)).scalars())

    async def list_claims_with_evidence(
        self, run_id: uuid.UUID, *, include_dropped: bool = False
    ) -> list[tuple[m.Claim, list[tuple[m.Citation, m.Chunk, m.SourceDocument]]]]:
        """Claims with their citations resolved to chunk + source document (one query each)."""
        await self.get_run(run_id)
        claim_stmt = self._owned(m.Claim).where(m.Claim.run_id == run_id)
        if not include_dropped:
            claim_stmt = claim_stmt.where(m.Claim.dropped.is_(False))
        claims = list((await self.session.execute(claim_stmt.order_by(m.Claim.analyst, m.Claim.created_at))).scalars())
        if not claims:
            return []
        cite_stmt = (
            select(m.Citation, m.Chunk, m.SourceDocument)
            .join(m.Chunk, m.Chunk.id == m.Citation.chunk_id)
            .join(m.SourceDocument, m.SourceDocument.id == m.Chunk.document_id)
            .where(m.Citation.user_id == self.user_id, m.Citation.claim_id.in_([c.id for c in claims]))
        )
        by_claim: dict[uuid.UUID, list[tuple[m.Citation, m.Chunk, m.SourceDocument]]] = {c.id: [] for c in claims}
        for citation, chunk, document in (await self.session.execute(cite_stmt)).tuples():
            by_claim[citation.claim_id].append((citation, chunk, document))
        return [(c, by_claim[c.id]) for c in claims]

    async def get_claim(
        self, run_id: uuid.UUID, claim_id: uuid.UUID
    ) -> tuple[m.Claim, list[tuple[m.Citation, m.Chunk, m.SourceDocument]]]:
        for claim, cites in await self.list_claims_with_evidence(run_id, include_dropped=True):
            if claim.id == claim_id:
                return claim, cites
        raise NotFound()

    async def flag_claims(self, run_id: uuid.UUID, claim_ids: Sequence[uuid.UUID]) -> int:
        """Founder feedback: mark claims as wrong (feeds the eval set)."""
        await self.get_run(run_id)
        if not claim_ids:
            return 0
        result = await self.session.execute(
            update(m.Claim)
            .where(m.Claim.user_id == self.user_id, m.Claim.run_id == run_id, m.Claim.id.in_(list(claim_ids)))
            .values(flagged_wrong=True)
            .returning(m.Claim.id)
        )
        return len(result.all())

    # ---- graph persistence (validation graph writes; the report is rebuilt from here) -------

    async def add_queries(self, run_id: uuid.UUID, rows: Sequence[tuple[Source, str, int]]) -> None:
        await self.get_run(run_id)
        for source, query, hits in rows:
            self._add(m.Query(id=new_id(), run_id=run_id, source=source, query=query[:2000], hits=hits))
        await self.session.flush()

    async def delete_claims(self, run_id: uuid.UUID, analyst: str) -> None:
        """Re-running an analyst node (crash resume) replaces its claims instead of duplicating them."""
        ids = select(m.Claim.id).where(
            m.Claim.user_id == self.user_id, m.Claim.run_id == run_id, m.Claim.analyst == analyst
        )
        await self.session.execute(delete(m.Citation).where(m.Citation.claim_id.in_(ids)))
        await self.session.execute(
            delete(m.Claim).where(m.Claim.user_id == self.user_id, m.Claim.run_id == run_id, m.Claim.analyst == analyst)
        )

    async def add_claim(
        self,
        run_id: uuid.UUID,
        *,
        analyst: str,
        text: str,
        stance: Stance,
        chunk_ids: Sequence[uuid.UUID],
        dropped: bool = False,
    ) -> m.Claim:
        owned = {c.id for c in await self.get_chunks(chunk_ids)}
        claim = self._add(
            m.Claim(id=new_id(), run_id=run_id, analyst=analyst, text=text, stance=stance, dropped=dropped)
        )
        await self.session.flush()
        for chunk_id in dict.fromkeys(chunk_ids):
            if chunk_id in owned:
                self._add(m.Citation(id=new_id(), claim_id=claim.id, chunk_id=chunk_id))
        await self.session.flush()
        return claim

    async def list_claims(self, run_id: uuid.UUID, *, include_dropped: bool = False) -> list[m.Claim]:
        stmt = self._owned(m.Claim).where(m.Claim.run_id == run_id)
        if not include_dropped:
            stmt = stmt.where(m.Claim.dropped.is_(False))
        return list((await self.session.execute(stmt.order_by(m.Claim.created_at))).scalars())

    async def list_citations(self, claim_ids: Sequence[uuid.UUID]) -> list[m.Citation]:
        if not claim_ids:
            return []
        stmt = self._owned(m.Citation).where(m.Citation.claim_id.in_(list(claim_ids)))
        return list((await self.session.execute(stmt)).scalars())

    async def replace_signals(self, run_id: uuid.UUID, rows: Sequence[tuple[str, float, str, dict[str, Any]]]) -> None:
        await self.get_run(run_id)
        await self.session.execute(delete(m.Signal).where(m.Signal.user_id == self.user_id, m.Signal.run_id == run_id))
        for name, value, method, inputs in rows:
            self._add(
                m.Signal(id=new_id(), run_id=run_id, name=name, value=value, method=method, inputs=_jsonable(inputs))
            )
        await self.session.flush()

    async def upsert_verdict(
        self,
        run_id: uuid.UUID,
        *,
        verdict: VerdictKind,
        confidence: float,
        coverage: dict[str, Any],
        reasons: list[Any],
        rationale: str | None,
    ) -> None:
        await self.get_run(run_id)
        values = {
            "verdict": verdict,
            "confidence": max(0.0, min(1.0, confidence)),
            "coverage": _jsonable(coverage),
            "reasons": _jsonable(reasons),
            "rationale": rationale,
        }
        stmt = insert(m.Verdict).values(id=new_id(), user_id=self.user_id, run_id=run_id, **values)
        await self.session.execute(stmt.on_conflict_do_update(index_elements=["run_id"], set_=values))

    async def set_run_communities(self, run_id: uuid.UUID, rows: Sequence[tuple[uuid.UUID, float, int]]) -> None:
        await self.get_run(run_id)
        await self.session.execute(
            delete(m.RunCommunity).where(m.RunCommunity.user_id == self.user_id, m.RunCommunity.run_id == run_id)
        )
        for community_id, relevance, count in rows:
            self._add(
                m.RunCommunity(
                    user_id=self.user_id,
                    run_id=run_id,
                    community_id=community_id,
                    relevance=relevance,
                    evidence_count=count,
                )
            )
        await self.session.flush()

    # ---- voice & story bank --------------------------------------------------------

    async def add_voice_sample(self, text: str, source_url: str | None = None) -> m.VoiceSample:
        sample = self._add(m.VoiceSample(id=new_id(), text=text, source_url=source_url))
        await self.session.flush()
        return sample

    async def list_voice_samples(self) -> list[m.VoiceSample]:
        stmt = self._owned(m.VoiceSample).where(m.VoiceSample.deleted_at.is_(None)).order_by(m.VoiceSample.created_at)
        return list((await self.session.execute(stmt)).scalars())

    async def delete_voice_sample(self, sample_id: uuid.UUID) -> None:
        sample = await self._get(m.VoiceSample, sample_id)
        sample.deleted_at = datetime.now(UTC)

    async def save_voice_profile(
        self, features: dict[str, Any], delta_baseline: dict[str, Any], few_shot_ids: list[str]
    ) -> m.VoiceProfile:
        current = await self.latest_voice_profile()
        profile = self._add(
            m.VoiceProfile(
                id=new_id(),
                version=(current.version + 1) if current else 1,
                features=_jsonable(features),
                delta_baseline=_jsonable(delta_baseline),
                few_shot_sample_ids=few_shot_ids,
            )
        )
        await self.session.flush()
        return profile

    async def latest_voice_profile(self) -> m.VoiceProfile | None:
        stmt = self._owned(m.VoiceProfile).order_by(m.VoiceProfile.version.desc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_story(
        self, *, category: StoryCategory, headline: str, details: str, numbers: list[str], tags: list[str]
    ) -> m.StoryBankEntry:
        entry = self._add(
            m.StoryBankEntry(
                id=new_id(), category=category, headline=headline, details=details, numbers=numbers, tags=tags
            )
        )
        await self.session.flush()
        return entry

    async def list_stories(self) -> list[m.StoryBankEntry]:
        stmt = (
            self._owned(m.StoryBankEntry)
            .where(m.StoryBankEntry.deleted_at.is_(None))
            .order_by(m.StoryBankEntry.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_story(self, story_id: uuid.UUID) -> m.StoryBankEntry:
        entry = await self._get(m.StoryBankEntry, story_id)
        if entry.deleted_at is not None:
            raise NotFound()
        return entry

    async def delete_story(self, story_id: uuid.UUID) -> None:
        (await self.get_story(story_id)).deleted_at = datetime.now(UTC)

    # ---- content plans -----------------------------------------------------------

    async def create_content_plan(self, project_id: uuid.UUID, run_id: uuid.UUID | None, days: int) -> m.ContentPlan:
        await self.get_project(project_id)
        if run_id is not None:
            await self.get_run(run_id)
        plan = self._add(
            m.ContentPlan(id=new_id(), project_id=project_id, run_id=run_id, days=days, thread_id=f"plan-{new_id()}")
        )
        await self.session.flush()
        return plan

    async def get_content_plan(self, plan_id: uuid.UUID) -> m.ContentPlan:
        return await self._get(m.ContentPlan, plan_id)

    async def list_content_plans(self, project_id: uuid.UUID) -> list[m.ContentPlan]:
        await self.get_project(project_id)
        stmt = self._owned(m.ContentPlan).where(m.ContentPlan.project_id == project_id)
        return list((await self.session.execute(stmt.order_by(m.ContentPlan.created_at.desc()))).scalars())

    async def replace_briefs(self, plan_id: uuid.UUID, briefs: Sequence[dict[str, Any]]) -> list[m.ContentBrief]:
        await self.get_content_plan(plan_id)
        existing = select(m.ContentBrief.id).where(
            m.ContentBrief.user_id == self.user_id, m.ContentBrief.plan_id == plan_id
        )
        drafts = select(m.ContentDraft.id).where(m.ContentDraft.brief_id.in_(existing))
        await self.session.execute(delete(m.GateResult).where(m.GateResult.draft_id.in_(drafts)))
        await self.session.execute(delete(m.ContentDraft).where(m.ContentDraft.brief_id.in_(existing)))
        await self.session.execute(delete(m.ContentBrief).where(m.ContentBrief.id.in_(existing)))
        rows = [self._add(m.ContentBrief(id=new_id(), plan_id=plan_id, **b)) for b in briefs]
        await self.session.flush()
        return rows

    async def list_briefs(self, plan_id: uuid.UUID) -> list[m.ContentBrief]:
        stmt = self._owned(m.ContentBrief).where(m.ContentBrief.plan_id == plan_id).order_by(m.ContentBrief.day)
        return list((await self.session.execute(stmt)).scalars())

    async def get_brief(self, brief_id: uuid.UUID) -> m.ContentBrief:
        return await self._get(m.ContentBrief, brief_id)

    async def add_draft(
        self,
        brief: m.ContentBrief,
        *,
        text: str,
        first_comment: str | None,
        status: DraftStatus,
        edited_by_user: bool = False,
        gate_layers: Sequence[dict[str, Any]] = (),
    ) -> m.ContentDraft:
        latest = await self.session.scalar(
            select(func.max(m.ContentDraft.version)).where(
                m.ContentDraft.user_id == self.user_id, m.ContentDraft.brief_id == brief.id
            )
        )
        draft = self._add(
            m.ContentDraft(
                id=new_id(),
                brief_id=brief.id,
                plan_id=brief.plan_id,
                version=(latest or 0) + 1,
                text=text,
                first_comment=first_comment,
                status=status,
                edited_by_user=edited_by_user,
            )
        )
        await self.session.flush()
        for layer in gate_layers:
            self._add(
                m.GateResult(
                    id=new_id(),
                    draft_id=draft.id,
                    layer=str(layer["layer"])[:32],
                    passed=bool(layer["passed"]),
                    score=layer.get("score"),
                    findings=_jsonable(layer.get("findings", [])),
                )
            )
        await self.session.flush()
        return draft

    async def get_draft(self, draft_id: uuid.UUID) -> m.ContentDraft:
        draft = await self._get(m.ContentDraft, draft_id)
        if draft.deleted_at is not None:
            raise NotFound()
        return draft

    async def latest_drafts(self, plan_id: uuid.UUID) -> list[m.ContentDraft]:
        """Newest version per brief."""
        latest = (
            select(m.ContentDraft.brief_id, func.max(m.ContentDraft.version).label("v"))
            .where(m.ContentDraft.user_id == self.user_id, m.ContentDraft.plan_id == plan_id)
            .group_by(m.ContentDraft.brief_id)
            .subquery()
        )
        stmt = (
            select(m.ContentDraft)
            .join(latest, (m.ContentDraft.brief_id == latest.c.brief_id) & (m.ContentDraft.version == latest.c.v))
            .where(m.ContentDraft.user_id == self.user_id)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def gate_results(self, draft_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[m.GateResult]]:
        if not draft_ids:
            return {}
        stmt = self._owned(m.GateResult).where(m.GateResult.draft_id.in_(list(draft_ids)))
        out: dict[uuid.UUID, list[m.GateResult]] = {}
        for row in (await self.session.execute(stmt)).scalars():
            out.setdefault(row.draft_id, []).append(row)
        return out

    async def list_run_communities(self, run_id: uuid.UUID) -> list[tuple[m.RunCommunity, m.Community]]:
        await self.get_run(run_id)
        stmt = (
            select(m.RunCommunity, m.Community)
            .join(m.Community, m.Community.id == m.RunCommunity.community_id)
            .where(m.RunCommunity.user_id == self.user_id, m.RunCommunity.run_id == run_id)
            .order_by(m.RunCommunity.evidence_count.desc())
        )
        return list((await self.session.execute(stmt)).tuples())

    async def latest_run_for_project(self, project_id: uuid.UUID) -> m.ValidationRun | None:
        stmt = (
            self._owned(m.ValidationRun)
            .where(m.ValidationRun.project_id == project_id)
            .order_by(m.ValidationRun.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ---- usage ----------------------------------------------------------------

    async def record_usage(
        self, kind: UsageKind, units: int = 1, cost_usd: float = 0.0, run_id: uuid.UUID | None = None, **meta: Any
    ) -> None:
        self._add(m.UsageEvent(id=new_id(), kind=kind, units=units, cost_usd=cost_usd, run_id=run_id, meta=meta))
        await self.session.flush()

    async def usage_since(self, kind: UsageKind, since: datetime) -> int:
        stmt = select(func.coalesce(func.sum(m.UsageEvent.units), 0)).where(
            m.UsageEvent.user_id == self.user_id, m.UsageEvent.kind == kind, m.UsageEvent.created_at >= since
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # ---- account lifecycle -----------------------------------------------------

    async def export(self) -> dict[str, list[dict[str, Any]]]:
        """Everything the user owns, as plain dicts (GDPR data export)."""
        out: dict[str, list[dict[str, Any]]] = {}
        for table in Base.metadata.sorted_tables:
            if table.name not in m.TENANT_TABLES:
                continue
            rows = (await self.session.execute(select(table).where(table.c.user_id == self.user_id))).mappings()
            out[table.name] = [
                {k: _jsonable(v) for k, v in row.items() if k not in ("embedding", "tsv")} for row in rows
            ]
        return out

    async def delete_everything(self) -> None:
        """Hard-delete all of the user's rows, children first."""
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in m.TENANT_TABLES:
                await self.session.execute(delete(table).where(table.c.user_id == self.user_id))
        await self.session.execute(delete(m.Profile).where(m.Profile.id == self.user_id))


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "is_finite"):  # Decimal
        return float(value)
    return value


# ---- maintenance (not user-scoped; worker cron only) ------------------------


async def stale_queued_runs(session: AsyncSession, older_than_seconds: int = 120) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(run_id, user_id) of runs still queued after `older_than_seconds` — their enqueue was lost."""
    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    stmt = select(m.ValidationRun.id, m.ValidationRun.user_id).where(
        m.ValidationRun.status == RunStatus.QUEUED, m.ValidationRun.created_at < cutoff
    )
    return [(row.id, row.user_id) for row in (await session.execute(stmt)).all()]


async def purge_scraped_text(session: AsyncSession, older_than_days: int = 90) -> int:
    """Drop scraped text past retention; URL, hash and claim/citation links stay."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    purged_ids = list(
        (
            await session.execute(
                update(m.SourceDocument)
                .where(m.SourceDocument.fetched_at < cutoff, m.SourceDocument.purged_at.is_(None))
                .values(raw_text=None, purged_at=func.now())
                .returning(m.SourceDocument.id)
            )
        ).scalars()
    )
    if purged_ids:
        await session.execute(
            update(m.Chunk).where(m.Chunk.document_id.in_(purged_ids)).values(text="", embedding=None)
        )
    return len(purged_ids)


async def purge_by_takedown(session: AsyncSession, *, url: str | None = None, author_handle: str | None = None) -> int:
    """Remove matching scraped content across all users (takedown process)."""
    if not url and not author_handle:
        raise InvalidInput("A takedown needs a URL or an author handle.")
    conditions: list[ColumnElement[bool]] = []
    if url:
        conditions.append((m.SourceDocument.canonical_url == url) | (m.SourceDocument.url == url))
    if author_handle:
        conditions.append(func.lower(m.SourceDocument.author_handle) == author_handle.lower().lstrip("@"))
    ids = list(
        (
            await session.execute(
                update(m.SourceDocument)
                .where(*conditions)
                .values(raw_text=None, author_handle=None, purged_at=func.now())
                .returning(m.SourceDocument.id)
            )
        ).scalars()
    )
    if ids:
        await session.execute(update(m.Chunk).where(m.Chunk.document_id.in_(ids)).values(text="", embedding=None))
    return len(ids)


# ---- takedowns (global, operator-only processing) ------------------------------------


async def create_takedown(
    session: AsyncSession, *, url: str | None, author_handle: str | None, reason: str, contact: str | None
) -> m.TakedownRequest:
    if not url and not author_handle:
        raise InvalidInput("A takedown needs a URL or an author handle.")
    request = m.TakedownRequest(
        id=new_id(),
        url=url,
        author_handle=author_handle.lstrip("@") if author_handle else None,
        reason=reason,
        contact=contact,
    )
    session.add(request)
    await session.flush()
    return request


async def list_takedowns(session: AsyncSession, status: TakedownStatus | None = None) -> list[m.TakedownRequest]:
    stmt = select(m.TakedownRequest).order_by(m.TakedownRequest.created_at.desc(), m.TakedownRequest.id.desc())
    if status:
        stmt = stmt.where(m.TakedownRequest.status == status)
    return list((await session.execute(stmt.limit(500))).scalars())


async def resolve_takedown(
    session: AsyncSession, takedown_id: uuid.UUID, *, approve: bool
) -> tuple[m.TakedownRequest, int]:
    """Approve (purge matching content everywhere) or reject a pending request. Returns (request, purged)."""
    request = await session.get(m.TakedownRequest, takedown_id, with_for_update=True)
    if request is None:
        raise NotFound("Takedown request not found.")
    if request.status != TakedownStatus.RECEIVED:
        raise Conflict("This takedown request was already resolved.")
    purged = await purge_by_takedown(session, url=request.url, author_handle=request.author_handle) if approve else 0
    request.status = TakedownStatus.PROCESSED if approve else TakedownStatus.REJECTED
    request.processed_at = datetime.now(UTC)
    await session.flush()
    return request, purged


# ---- source health ---------------------------------------------------------------------


def health_window(at: datetime | None = None) -> datetime:
    """Hourly buckets."""
    return (at or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)


async def record_source_health(
    session: AsyncSession, snapshots: Mapping[str, Mapping[str, Any]], *, at: datetime | None = None
) -> int:
    """Add one flush of fetcher counters (``Fetcher.drain_health()``) to this hour's rows.

    Unknown source names (e.g. the internal ``searxng``) are skipped. p95 keeps the worst value in the window.
    """
    known = {s.value for s in Source}
    window = health_window(at)
    written = 0
    for name, snap in snapshots.items():
        if name not in known or not snap.get("requests"):
            continue
        stmt = insert(m.SourceHealth).values(
            id=new_id(),
            source=Source(name),
            window_start=window,
            requests=int(snap["requests"]),
            successes=int(snap.get("successes") or 0),
            p95_ms=snap.get("p95_ms"),
        )
        excluded = stmt.excluded
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_source_health_source_window",
                set_={
                    "requests": m.SourceHealth.requests + excluded.requests,
                    "successes": m.SourceHealth.successes + excluded.successes,
                    "p95_ms": func.greatest(m.SourceHealth.p95_ms, excluded.p95_ms),
                },
            )
        )
        written += 1
    return written


async def source_health_summary(session: AsyncSession, *, hours: int = 24) -> dict[str, dict[str, Any]]:
    since = health_window() - timedelta(hours=hours - 1)
    rows = await session.execute(
        select(
            m.SourceHealth.source,
            func.sum(m.SourceHealth.requests),
            func.sum(m.SourceHealth.successes),
            func.max(m.SourceHealth.p95_ms),
        )
        .where(m.SourceHealth.window_start >= since)
        .group_by(m.SourceHealth.source)
    )
    out: dict[str, dict[str, Any]] = {}
    for source, requests, successes, p95 in rows:
        req = int(requests or 0)
        out[str(source)] = {
            "requests": req,
            "successes": int(successes or 0),
            "success_rate": round(int(successes or 0) / req, 3) if req else None,
            "p95_ms": p95,
        }
    return out


# ---- communities (global reference data) ------------------------------------------------


async def ensure_communities(session: AsyncSession, platform: Platform, names: Sequence[str]) -> dict[str, uuid.UUID]:
    """Id per community name, creating rows for communities seen in evidence for the first time."""
    names = list(dict.fromkeys(n for n in names if n))
    if not names:
        return {}
    await session.execute(
        insert(m.Community)
        .values([{"id": new_id(), "platform": platform, "name": n} for n in names])
        .on_conflict_do_nothing(constraint="uq_communities_platform_name")
    )
    rows = await session.execute(
        select(m.Community.name, m.Community.id).where(m.Community.platform == platform, m.Community.name.in_(names))
    )
    return {name: cid for name, cid in rows.tuples()}


async def list_communities(session: AsyncSession, platform: Platform | None = None) -> list[m.Community]:
    stmt = select(m.Community).order_by(m.Community.platform, m.Community.name)
    if platform is not None:
        stmt = stmt.where(m.Community.platform == platform)
    return list((await session.execute(stmt)).scalars())


async def community_rules(
    session: AsyncSession, community_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, m.CommunityRule]:
    if not community_ids:
        return {}
    stmt = select(m.CommunityRule).where(m.CommunityRule.community_id.in_(list(community_ids)))
    return {r.community_id: r for r in (await session.execute(stmt)).scalars()}


async def get_hook_patterns(
    session: AsyncSession, community_ids: Sequence[uuid.UUID | None], *, max_age_hours: int = 24
) -> list[m.HookPattern]:
    since = datetime.now(UTC) - timedelta(hours=max_age_hours)
    stmt = (
        select(m.HookPattern)
        .where(m.HookPattern.community_id.in_([c for c in community_ids if c]), m.HookPattern.updated_at >= since)
        .order_by(m.HookPattern.relative_engagement.desc())
    )
    return list((await session.execute(stmt)).scalars())


async def replace_hook_patterns(
    session: AsyncSession, community_id: uuid.UUID, platform: Platform, rows: Sequence[dict[str, Any]]
) -> None:
    await session.execute(delete(m.HookPattern).where(m.HookPattern.community_id == community_id))
    for row in rows:
        session.add(m.HookPattern(id=new_id(), community_id=community_id, platform=platform, **row))
    await session.flush()
