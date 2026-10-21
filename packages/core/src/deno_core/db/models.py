"""Relational schema (docs/08 Phase 2).

Conventions: UUIDv7 primary keys; ``created_at``/``updated_at`` timestamptz;
every tenant table carries an indexed ``user_id`` (the Supabase auth user id);
soft delete via ``deleted_at`` where users delete things. Global reference
tables (communities, hook patterns, quotas, source health, flags) have no owner.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Computed, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deno_core.db.base import Base, IdMixin, SoftDeleteMixin, TenantMixin, TimestampMixin
from deno_core.db.enums import (
    DraftStatus,
    Plan,
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

EMBEDDING_DIM = 2048  # nvidia/nemotron-3-embed-1b (ADR-007); halfvec because HNSW on `vector` caps at 2000


def enum_col(enum: type[StrEnum]) -> sa.Enum:
    return sa.Enum(
        enum,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
        name=enum.__name__.lower(),
    )


def fk(target: str, ondelete: str = "CASCADE") -> ForeignKey:
    return ForeignKey(target, ondelete=ondelete)


# --------------------------------------------------------------------------- identity


class Profile(TimestampMixin, Base):
    """One row per Supabase auth user (id = auth.users.id). Created on first API call or by trigger."""

    __tablename__ = "profiles"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str | None] = mapped_column(sa.String(120))
    role: Mapped[str] = mapped_column(sa.String(16), server_default="user")
    plan: Mapped[Plan] = mapped_column(enum_col(Plan), server_default=Plan.FREE.value)
    # Shown in drafts and disclosures ("who the posts are from"); edited only through the API.
    product_name: Mapped[str | None] = mapped_column(sa.String(120))
    product_url: Mapped[str | None] = mapped_column(sa.Text)
    timezone: Mapped[str | None] = mapped_column(sa.String(64))
    founder_role: Mapped[str | None] = mapped_column(sa.String(40))
    handles: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    voice_preset: Mapped[str | None] = mapped_column(sa.String(40))
    notification_prefs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # Per-dimension quality weights (nullable; when null, defaults from deno_gates.quality are used).
    # Keys are dimension names, values are floats (e.g. {"hook_strength": 2.0, "readability": 0.5}).
    quality_weights: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Override the default quality threshold (1–10). NULL = use system default (7).
    quality_threshold: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)


class ApiAuditLog(IdMixin, Base):
    __tablename__ = "api_audit_log"
    user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(sa.String(64))
    target: Mapped[str | None] = mapped_column(sa.String(128))
    request_id: Mapped[str | None] = mapped_column(sa.String(64))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now(), index=True)


# --------------------------------------------------------------------------- projects & runs


class Project(IdMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "projects"
    title: Mapped[str] = mapped_column(sa.String(200))
    idea: Mapped[str] = mapped_column(sa.Text)
    author_handle: Mapped[str | None] = mapped_column(sa.String(64))
    status: Mapped[ProjectStatus] = mapped_column(enum_col(ProjectStatus), server_default=ProjectStatus.DRAFT.value)

    runs: Mapped[list[ValidationRun]] = relationship(back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_projects_user_active", "user_id", "created_at", postgresql_where=text("deleted_at IS NULL")),
    )


class ValidationRun(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "validation_runs"
    project_id: Mapped[uuid.UUID] = mapped_column(fk("projects.id"), index=True)
    status: Mapped[RunStatus] = mapped_column(enum_col(RunStatus), server_default=RunStatus.QUEUED.value)
    thread_id: Mapped[str] = mapped_column(sa.String(64), unique=True)  # LangGraph checkpointer thread
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(128))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    cost_usd: Mapped[Decimal] = mapped_column(sa.Numeric(10, 4), server_default="0")
    error_code: Mapped[str | None] = mapped_column(sa.String(64))

    project: Mapped[Project] = relationship(back_populates="runs")

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_validation_runs_user_idempotency"),
        Index(
            "ix_validation_runs_user_active",
            "user_id",
            postgresql_where=text("status IN ('queued', 'running', 'awaiting_review')"),
        ),
    )


class Query(IdMixin, TenantMixin, Base):
    """What the query planner searched for, per source, and how many hits it got."""

    __tablename__ = "queries"
    run_id: Mapped[uuid.UUID] = mapped_column(fk("validation_runs.id"), index=True)
    source: Mapped[Source] = mapped_column(enum_col(Source))
    query: Mapped[str] = mapped_column(sa.Text)
    hits: Mapped[int] = mapped_column(server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())


# --------------------------------------------------------------------------- evidence


class SourceDocument(IdMixin, TenantMixin, Base):
    __tablename__ = "source_documents"
    run_id: Mapped[uuid.UUID] = mapped_column(fk("validation_runs.id"), index=True)
    source: Mapped[Source] = mapped_column(enum_col(Source))
    url: Mapped[str] = mapped_column(sa.Text)
    canonical_url: Mapped[str] = mapped_column(sa.Text)
    author_handle: Mapped[str | None] = mapped_column(sa.String(128))
    community: Mapped[str | None] = mapped_column(sa.String(128))
    published_at: Mapped[datetime | None]
    engagement: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # Untrusted scraped text; purged after the retention window (URL + hash kept).
    raw_text: Mapped[str | None] = mapped_column(sa.Text)
    content_hash: Mapped[str] = mapped_column(sa.String(64), index=True)
    fetch_tier: Mapped[str] = mapped_column(sa.String(32))
    fetched_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    purged_at: Mapped[datetime | None]

    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("run_id", "canonical_url", name="uq_source_documents_run_url"),
        Index("ix_source_documents_fetched_unpurged", "fetched_at", postgresql_where=text("purged_at IS NULL")),
    )


class Chunk(IdMixin, TenantMixin, Base):
    __tablename__ = "chunks"
    document_id: Mapped[uuid.UUID] = mapped_column(fk("source_documents.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(fk("validation_runs.id"), index=True)
    ordinal: Mapped[int]
    text: Mapped[str] = mapped_column(sa.Text)
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIM))
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed("to_tsvector('english', coalesce(text, ''))", persisted=True))

    document: Mapped[SourceDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_chunks_document_ordinal"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )


# --------------------------------------------------------------------------- findings


class Claim(IdMixin, TenantMixin, Base):
    __tablename__ = "claims"
    run_id: Mapped[uuid.UUID] = mapped_column(fk("validation_runs.id"), index=True)
    analyst: Mapped[str] = mapped_column(sa.String(32))
    text: Mapped[str] = mapped_column(sa.Text)
    stance: Mapped[Stance] = mapped_column(enum_col(Stance))
    dropped: Mapped[bool] = mapped_column(server_default=sa.false())  # failed citation validation
    flagged_wrong: Mapped[bool] = mapped_column(server_default=sa.false())  # founder feedback (interrupt)
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())

    citations: Mapped[list[Citation]] = relationship(back_populates="claim", cascade="all, delete-orphan")


class Citation(IdMixin, TenantMixin, Base):
    __tablename__ = "citations"
    claim_id: Mapped[uuid.UUID] = mapped_column(fk("claims.id"), index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(fk("chunks.id"), index=True)
    entailment_score: Mapped[float | None]
    verified: Mapped[bool] = mapped_column(server_default=sa.false())

    claim: Mapped[Claim] = relationship(back_populates="citations")

    __table_args__ = (UniqueConstraint("claim_id", "chunk_id", name="uq_citations_claim_chunk"),)


class Signal(IdMixin, TenantMixin, Base):
    """Deterministic metrics computed from the evidence (no LLM)."""

    __tablename__ = "signals"
    run_id: Mapped[uuid.UUID] = mapped_column(fk("validation_runs.id"), index=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    value: Mapped[float]
    method: Mapped[str] = mapped_column(sa.String(200))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_signals_run_name"),)


class Verdict(IdMixin, TenantMixin, Base):
    __tablename__ = "verdicts"
    run_id: Mapped[uuid.UUID] = mapped_column(fk("validation_runs.id"), unique=True)
    verdict: Mapped[VerdictKind] = mapped_column(enum_col(VerdictKind))
    confidence: Mapped[float]
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    reasons: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    rationale: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())

    __table_args__ = (sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),)


# --------------------------------------------------------------------------- communities (global)


class Community(IdMixin, TimestampMixin, Base):
    __tablename__ = "communities"
    platform: Mapped[Platform] = mapped_column(enum_col(Platform))
    name: Mapped[str] = mapped_column(sa.String(128))
    url: Mapped[str | None] = mapped_column(sa.Text)
    audience: Mapped[str | None] = mapped_column(sa.String(200))

    rules: Mapped[list[CommunityRule]] = relationship(back_populates="community", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("platform", "name", name="uq_communities_platform_name"),)


class CommunityRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "community_rules"
    community_id: Mapped[uuid.UUID] = mapped_column(fk("communities.id"), index=True)
    karma_gate: Mapped[str | None] = mapped_column(sa.String(200))
    promo_policy: Mapped[str | None] = mapped_column(sa.Text)
    ai_policy: Mapped[str | None] = mapped_column(sa.Text)
    cadence: Mapped[str | None] = mapped_column(sa.String(100))
    min_days_between_posts: Mapped[int | None]
    value_to_promo_ratio: Mapped[int | None]
    source_url: Mapped[str | None] = mapped_column(sa.Text)
    verified_at: Mapped[datetime | None]  # NULL = not yet checked against the live rules page

    community: Mapped[Community] = relationship(back_populates="rules")


class RunCommunity(TenantMixin, Base):
    __tablename__ = "run_communities"
    run_id: Mapped[uuid.UUID] = mapped_column(fk("validation_runs.id"), primary_key=True)
    community_id: Mapped[uuid.UUID] = mapped_column(fk("communities.id"), primary_key=True)
    relevance: Mapped[float]
    evidence_count: Mapped[int] = mapped_column(server_default="0")


# --------------------------------------------------------------------------- voice


class VoiceSample(IdMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "voice_samples"
    text: Mapped[str] = mapped_column(sa.Text)
    source_url: Mapped[str | None] = mapped_column(sa.Text)


class VoiceProfile(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "voice_profiles"
    version: Mapped[int] = mapped_column(server_default="1")
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    delta_baseline: Mapped[dict[str, Any]] = mapped_column(JSONB)
    few_shot_sample_ids: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_voice_profiles_user_version"),)


class StoryBankEntry(IdMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "story_bank_entries"
    category: Mapped[StoryCategory] = mapped_column(enum_col(StoryCategory))
    headline: Mapped[str] = mapped_column(sa.String(300))
    details: Mapped[str] = mapped_column(sa.Text)
    numbers: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    tags: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))


# --------------------------------------------------------------------------- content


class ContentPlan(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "content_plans"
    project_id: Mapped[uuid.UUID] = mapped_column(fk("projects.id"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(fk("validation_runs.id", ondelete="SET NULL"))
    days: Mapped[int]
    status: Mapped[RunStatus] = mapped_column(enum_col(RunStatus), server_default=RunStatus.QUEUED.value)
    thread_id: Mapped[str] = mapped_column(sa.String(64), unique=True)


class ContentBrief(IdMixin, TenantMixin, Base):
    __tablename__ = "content_briefs"
    plan_id: Mapped[uuid.UUID] = mapped_column(fk("content_plans.id"), index=True)
    day: Mapped[int]
    platform: Mapped[Platform] = mapped_column(enum_col(Platform))
    community_id: Mapped[uuid.UUID | None] = mapped_column(fk("communities.id", ondelete="SET NULL"))
    hook_formula: Mapped[str | None] = mapped_column(sa.String(16))
    angle: Mapped[str] = mapped_column(sa.Text)
    is_promotional: Mapped[bool] = mapped_column(server_default=sa.false())
    story_entry_id: Mapped[uuid.UUID | None] = mapped_column(fk("story_bank_entries.id", ondelete="SET NULL"))


class ContentDraft(IdMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "content_drafts"
    brief_id: Mapped[uuid.UUID] = mapped_column(fk("content_briefs.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(fk("content_plans.id"), index=True)
    version: Mapped[int] = mapped_column(server_default="1")
    text: Mapped[str] = mapped_column(sa.Text)
    first_comment: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[DraftStatus] = mapped_column(enum_col(DraftStatus), server_default=DraftStatus.DRAFT.value)
    edited_by_user: Mapped[bool] = mapped_column(server_default=sa.false())

    __table_args__ = (UniqueConstraint("brief_id", "version", name="uq_content_drafts_brief_version"),)


class GateResult(IdMixin, TenantMixin, Base):
    __tablename__ = "gate_results"
    draft_id: Mapped[uuid.UUID] = mapped_column(fk("content_drafts.id"), index=True)
    layer: Mapped[str] = mapped_column(sa.String(32))
    passed: Mapped[bool]
    score: Mapped[float | None]
    findings: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    # Structured, machine-readable extras for a layer (e.g. the quality_verification layer's
    # real per-dimension weight and plain-English explanation). NULL for every other layer.
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())

    __table_args__ = (Index("ix_gate_results_user_layer_created", "user_id", "layer", "created_at"),)


class HookPattern(IdMixin, TimestampMixin, Base):
    """Hook formulas observed in top posts, per community/topic (global, cached 24 h)."""

    __tablename__ = "hook_patterns"
    formula_id: Mapped[str] = mapped_column(sa.String(16))
    platform: Mapped[Platform] = mapped_column(enum_col(Platform))
    community_id: Mapped[uuid.UUID | None] = mapped_column(fk("communities.id", ondelete="SET NULL"), index=True)
    topic: Mapped[str] = mapped_column(sa.String(200))
    relative_engagement: Mapped[float]
    sample_urls: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))


# --------------------------------------------------------------------------- billing


class Subscription(TenantMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    plan: Mapped[Plan] = mapped_column(enum_col(Plan), server_default=Plan.FREE.value)
    status: Mapped[str] = mapped_column(sa.String(32), server_default="active")
    stripe_customer_id: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    current_period_end: Mapped[datetime | None]


class UsageEvent(IdMixin, TenantMixin, Base):
    """Append-only ledger for quotas and cost accounting."""

    __tablename__ = "usage_events"
    kind: Mapped[UsageKind] = mapped_column(enum_col(UsageKind))
    units: Mapped[int] = mapped_column(server_default="1")
    cost_usd: Mapped[Decimal] = mapped_column(sa.Numeric(10, 6), server_default="0")
    run_id: Mapped[uuid.UUID | None] = mapped_column(fk("validation_runs.id", ondelete="SET NULL"))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())

    __table_args__ = (Index("ix_usage_events_user_kind_time", "user_id", "kind", "created_at"),)


class Quota(Base):
    __tablename__ = "quotas"
    plan: Mapped[Plan] = mapped_column(enum_col(Plan), primary_key=True)
    kind: Mapped[UsageKind] = mapped_column(enum_col(UsageKind), primary_key=True)
    monthly_limit: Mapped[int]
    max_concurrent: Mapped[int] = mapped_column(server_default="1")


class StripeEvent(Base):
    __tablename__ = "stripe_events"
    id: Mapped[str] = mapped_column(sa.String(255), primary_key=True)
    type: Mapped[str] = mapped_column(sa.String(128))
    received_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    processed_at: Mapped[datetime | None]


# --------------------------------------------------------------------------- ops (global)


class SourceHealth(IdMixin, Base):
    __tablename__ = "source_health"
    source: Mapped[Source] = mapped_column(enum_col(Source))
    window_start: Mapped[datetime]
    requests: Mapped[int] = mapped_column(server_default="0")
    successes: Mapped[int] = mapped_column(server_default="0")
    p95_ms: Mapped[int | None]

    __table_args__ = (UniqueConstraint("source", "window_start", name="uq_source_health_source_window"),)


class TakedownRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "takedown_requests"
    url: Mapped[str | None] = mapped_column(sa.Text)
    author_handle: Mapped[str | None] = mapped_column(sa.String(128))
    reason: Mapped[str] = mapped_column(sa.Text)
    contact: Mapped[str | None] = mapped_column(sa.String(320))
    status: Mapped[TakedownStatus] = mapped_column(
        enum_col(TakedownStatus), server_default=TakedownStatus.RECEIVED.value
    )
    processed_at: Mapped[datetime | None]

    __table_args__ = (sa.CheckConstraint("url IS NOT NULL OR author_handle IS NOT NULL", name="has_target"),)


class FeatureFlag(TimestampMixin, Base):
    __tablename__ = "feature_flags"
    key: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(server_default=sa.false())
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


TENANT_TABLES: tuple[str, ...] = tuple(
    sorted(t.name for t in Base.metadata.sorted_tables if "user_id" in t.c and t.name != "api_audit_log")
)
GLOBAL_TABLES: tuple[str, ...] = tuple(
    sorted(t.name for t in Base.metadata.sorted_tables if t.name not in TENANT_TABLES)
)
