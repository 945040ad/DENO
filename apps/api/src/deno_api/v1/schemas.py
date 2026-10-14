"""API v1 contract (request/response models). Everything here appears in OpenAPI."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from deno_core.db import models as m
from deno_core.db.enums import ProjectStatus, RunStatus, Source, Stance, TakedownStatus, VerdictKind
from deno_core.text import CleanText


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str
    request_id: str | None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


_ERRORS = {
    400: "Malformed request",
    401: "Missing or invalid session",
    402: "Plan quota exceeded",
    404: "Not found (also returned for resources owned by someone else)",
    409: "Conflicts with the current state",
    413: "Request body too large",
    422: "Invalid input",
    429: "Rate limited; see Retry-After",
}
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorEnvelope, "description": desc} for code, desc in _ERRORS.items()
}

# At least five visible characters (not whitespace or control characters) — the
# same rule the domain applies after CleanText, so the contract and the check agree.
IDEA_PATTERN = r"(?:[^\s\x00-\x1f\x7f-\x9f][\s\S]*){5}"


# ---- projects ------------------------------------------------------------------


class ProjectCreate(BaseModel):
    idea: CleanText = Field(
        min_length=5,
        max_length=4000,
        pattern=IDEA_PATTERN,
        description="The idea in plain words, or a landing-page URL",
    )
    author_handle: CleanText | None = Field(default=None, max_length=64)


class ProjectPatch(BaseModel):
    title: CleanText | None = Field(default=None, min_length=1, max_length=200)
    status: Literal[ProjectStatus.ARCHIVED, ProjectStatus.DRAFT] | None = None


class LatestRunOut(BaseModel):
    """The project's newest validation run, so lists can show real progress and the verdict."""

    id: uuid.UUID
    status: RunStatus
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    verdict: VerdictKind | None = None
    confidence: float | None = None


class ProjectOut(_Out):
    id: uuid.UUID
    title: str
    idea: str
    author_handle: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    latest_run: LatestRunOut | None = None


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    next_cursor: str | None


# ---- runs ----------------------------------------------------------------------


class RunCreated(BaseModel):
    run_id: uuid.UUID
    status: RunStatus
    events_url: str


class RunOut(_Out):
    id: uuid.UUID
    project_id: uuid.UUID
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    created_at: datetime


class ResumeRequest(BaseModel):
    """Answer to the review interrupt: which claims the founder says are wrong."""

    approve: bool = True
    wrong_claim_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


# ---- evidence & report ---------------------------------------------------------------


class EvidenceOut(_Out):
    id: uuid.UUID
    source: Source
    url: str
    author_handle: str | None
    community: str | None
    published_at: datetime | None
    engagement: dict[str, Any]
    excerpt: str | None = Field(description="First 500 characters of the post; null once past retention")
    fetched_at: datetime

    @classmethod
    def of(cls, doc: m.SourceDocument) -> EvidenceOut:
        return cls(
            id=doc.id,
            source=doc.source,
            url=doc.url,
            author_handle=doc.author_handle,
            community=doc.community,
            published_at=doc.published_at,
            engagement=doc.engagement,
            excerpt=doc.raw_text[:500] if doc.raw_text else None,
            fetched_at=doc.fetched_at,
        )


class EvidencePage(BaseModel):
    items: list[EvidenceOut]
    next_cursor: str | None


class CitationOut(BaseModel):
    chunk_id: uuid.UUID
    quote: str
    verified: bool
    entailment_score: float | None
    document: EvidenceOut


class ClaimOut(BaseModel):
    id: uuid.UUID
    analyst: str
    text: str
    stance: Stance
    dropped: bool
    flagged_wrong: bool
    citations: list[CitationOut]

    @classmethod
    def of(cls, claim: m.Claim, cites: list[tuple[m.Citation, m.Chunk, m.SourceDocument]]) -> ClaimOut:
        return cls(
            id=claim.id,
            analyst=claim.analyst,
            text=claim.text,
            stance=claim.stance,
            dropped=claim.dropped,
            flagged_wrong=claim.flagged_wrong,
            citations=[
                CitationOut(
                    chunk_id=chunk.id,
                    quote=chunk.text[:600],
                    verified=cite.verified,
                    entailment_score=cite.entailment_score,
                    document=EvidenceOut.of(doc),
                )
                for cite, chunk, doc in cites
            ],
        )


class SignalOut(_Out):
    name: str
    value: float
    method: str
    inputs: dict[str, Any]


class VerdictOut(_Out):
    verdict: VerdictKind
    confidence: float
    coverage: dict[str, Any]
    reasons: list[Any]
    rationale: str | None


class ReportOut(BaseModel):
    run: RunOut
    verdict: VerdictOut | None
    signals: list[SignalOut]
    claims: list[ClaimOut]


# ---- account ----------------------------------------------------------------------


NOTIFICATION_KEYS = ("verdict_ready", "draft_ready", "rule_changed", "ban_risk", "weekly_digest", "product_updates")
VOICE_PRESETS = ("terse_engineer", "build_in_public", "dry_humour", "data_first", "storyteller")
FOUNDER_ROLES = ("solo_founder", "co_founder", "indie_hacker", "founding_marketer")


class Handle(BaseModel):
    platform: Literal["reddit", "x", "linkedin", "hn"]
    handle: CleanText = Field(min_length=2, max_length=120, pattern=r"^[^\s]+$")


class MeOut(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None
    plan: str
    role: str
    product_name: str | None = None
    product_url: str | None = None
    timezone: str | None = None
    founder_role: str | None = None
    handles: list[Handle] = Field(default_factory=list)
    voice_preset: str | None = None
    notification_prefs: dict[str, bool] = Field(default_factory=dict)


class MeUpdate(BaseModel):
    """Only the fields you send change. The email is managed by the login provider, not here."""

    display_name: CleanText | None = Field(default=None, max_length=120)
    product_name: CleanText | None = Field(default=None, max_length=120)
    product_url: CleanText | None = Field(default=None, max_length=500)
    timezone: CleanText | None = Field(default=None, max_length=64, description="IANA name, e.g. Asia/Kolkata")
    founder_role: Literal["solo_founder", "co_founder", "indie_hacker", "founding_marketer"] | None = None
    handles: list[Handle] | None = Field(default=None, max_length=10)
    voice_preset: Literal["terse_engineer", "build_in_public", "dry_humour", "data_first", "storyteller"] | None = None
    notification_prefs: (
        dict[
            Literal["verdict_ready", "draft_ready", "rule_changed", "ban_risk", "weekly_digest", "product_updates"],
            StrictBool,
        ]
        | None
    ) = None


# ---- takedowns --------------------------------------------------------------------


class TakedownCreate(BaseModel):
    url: CleanText | None = Field(
        default=None, max_length=2048, pattern=r"^https?://\S+$", description="The post to remove"
    )
    author_handle: CleanText | None = Field(
        default=None, max_length=128, pattern=r"^@?[\w.\-]{1,127}$", description="Remove everything by this author"
    )
    reason: CleanText = Field(min_length=3, max_length=2000)
    contact: CleanText | None = Field(default=None, max_length=320, description="Where we can confirm the outcome")

    @model_validator(mode="after")
    def _has_target(self) -> TakedownCreate:
        if not self.url and not self.author_handle:
            raise ValueError("Give a URL or an author handle.")
        return self


class TakedownReceipt(BaseModel):
    id: uuid.UUID
    status: TakedownStatus


class TakedownOut(_Out):
    id: uuid.UUID
    url: str | None
    author_handle: str | None
    reason: str
    contact: str | None
    status: TakedownStatus
    created_at: datetime
    processed_at: datetime | None


class TakedownResolved(BaseModel):
    id: uuid.UUID
    status: TakedownStatus
    purged_documents: int
