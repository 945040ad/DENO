"""Voice, Story Bank, content plans, drafts, gates and communities (Phase 10 surface)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deno_api.deps import Events, Scope, UserId, get_sessionmaker, rate_limit
from deno_core.db import models as m
from deno_core.db.enums import DraftStatus, Plan, RunStatus, StoryCategory, UsageKind
from deno_core.db.repositories import UserScope, community_rules
from deno_core.errors import Conflict, InvalidInput, QuotaExceeded, UpstreamUnavailable
from deno_core.events import RunEvent
from deno_core.jobs import TASK_CONTENT_PLAN, enqueue
from deno_core.settings import get_settings
from deno_core.text import CleanText
from deno_gates import (
    CommunityRules,
    GateContext,
    VoiceProfile,
    autofix,
    build_profile,
    number_words_in,
    numbers_in,
    run_gates,
)

router = APIRouter(tags=["content"])
HEARTBEAT_MS = 15_000


# ---- schemas -------------------------------------------------------------------------------


class VoiceSampleIn(BaseModel):
    text: CleanText = Field(min_length=40, max_length=5000, description="One of your own posts, pasted")
    source_url: CleanText | None = Field(default=None, max_length=500)


class VoiceSampleOut(BaseModel):
    id: uuid.UUID
    text: str
    source_url: str | None
    created_at: datetime


class VoiceProfileOut(BaseModel):
    version: int
    samples: int
    strong: bool
    threshold: float
    created_at: datetime
    avg_draft_delta: float | None = Field(default=None, description="Mean Delta of your gated drafts vs your profile")
    drafts_scored: int = 0


class StoryIn(BaseModel):
    category: StoryCategory
    headline: CleanText = Field(min_length=3, max_length=300, pattern=r"(?:[^\s\x00-\x1f\x7f-\x9f][\s\S]*){3}")
    details: CleanText = Field(min_length=10, max_length=5000, pattern=r"(?:[^\s\x00-\x1f\x7f-\x9f][\s\S]*){10}")
    numbers: list[CleanText] = Field(default_factory=list, max_length=20)
    tags: list[CleanText] = Field(default_factory=list, max_length=20)


class StoryOut(BaseModel):
    id: uuid.UUID
    category: StoryCategory
    headline: str
    details: str
    numbers: list[str]
    tags: list[str]
    created_at: datetime


class StoryExtractIn(BaseModel):
    text: CleanText = Field(min_length=20, max_length=6000)


class ProposedStory(BaseModel):
    category: StoryCategory
    headline: str
    details: str
    numbers: list[str]


class ProposedStories(BaseModel):
    stories: list[ProposedStory]


class PlanCreate(BaseModel):
    days: Literal[7, 14, 30] = 7
    run_id: uuid.UUID | None = Field(default=None, description="Validation run to build on (default: latest)")


class PlanCreated(BaseModel):
    plan_id: uuid.UUID
    status: RunStatus
    events_url: str


class GateLayerOut(BaseModel):
    layer: str
    passed: bool
    score: float | None
    findings: list[dict[str, Any]]


class DraftOut(BaseModel):
    id: uuid.UUID
    version: int
    text: str
    first_comment: str | None
    status: DraftStatus
    edited_by_user: bool
    gates: list[GateLayerOut]


class BriefOut(BaseModel):
    id: uuid.UUID
    day: int
    platform: str
    community: str | None
    hook_formula: str | None
    angle: str
    is_promotional: bool
    draft: DraftOut | None


class PlanOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID | None
    days: int
    status: RunStatus
    created_at: datetime
    briefs: list[BriefOut]


class DraftEdit(BaseModel):
    text: CleanText = Field(min_length=1, max_length=6000)


class AuditIn(BaseModel):
    text: CleanText = Field(min_length=1, max_length=6000)
    platform: Literal["linkedin", "reddit", "x", "hn"] = "linkedin"
    community: CleanText | None = Field(default=None, max_length=128)
    is_promotional: StrictBool = False


class AuditOut(BaseModel):
    passed: bool
    layers: list[GateLayerOut]
    autofixed: str


class CommunityOut(BaseModel):
    id: uuid.UUID
    platform: str
    name: str
    url: str | None
    audience: str | None
    relevance: float | None = None
    evidence_count: int | None = None
    karma_gate: str | None = None
    promo_policy: str | None = None
    ai_policy: str | None = None
    cadence: str | None = None
    rules_verified: bool = False


# ---- voice -----------------------------------------------------------------------------------


@router.get("/voice/samples")
async def list_samples(scope: Scope) -> list[VoiceSampleOut]:
    return [VoiceSampleOut.model_validate(s, from_attributes=True) for s in await scope.list_voice_samples()]


@router.post("/voice/samples", status_code=status.HTTP_201_CREATED)
async def add_sample(body: VoiceSampleIn, scope: Scope) -> VoiceSampleOut:
    await scope.ensure_profile()
    if len(await scope.list_voice_samples()) >= 50:
        raise InvalidInput("You can keep up to 50 voice samples.")
    return VoiceSampleOut.model_validate(await scope.add_voice_sample(body.text, body.source_url), from_attributes=True)


@router.delete("/voice/samples/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sample(sample_id: uuid.UUID, scope: Scope) -> Response:
    await scope.delete_voice_sample(sample_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/voice/profile")
async def build_voice_profile(scope: Scope) -> VoiceProfileOut:
    """Build (or rebuild) your stylometric profile from your samples (needs 3+ of 20+ words)."""
    samples = await scope.list_voice_samples()
    try:
        profile = build_profile([s.text for s in samples])
    except ValueError as exc:
        raise Conflict(str(exc)) from None
    row = await scope.save_voice_profile(
        features={"samples": len(samples), "mfw": len(profile.vocab)},
        delta_baseline=profile.to_dict(),
        few_shot_ids=[str(s.id) for s in samples[:3]],
    )
    return VoiceProfileOut(
        version=row.version,
        samples=len(samples),
        strong=profile.strong,
        threshold=profile.threshold,
        created_at=row.created_at,
    )


@router.get("/voice/profile")
async def get_voice_profile(scope: Scope) -> VoiceProfileOut | None:
    row = await scope.latest_voice_profile()
    if row is None:
        return None
    p = VoiceProfile.from_dict(row.delta_baseline)
    avg, count = (
        await scope.session.execute(
            select(func.avg(m.GateResult.score), func.count(m.GateResult.id)).where(
                m.GateResult.user_id == scope.user_id, m.GateResult.layer == "voice", m.GateResult.score.is_not(None)
            )
        )
    ).one()
    return VoiceProfileOut(
        version=row.version,
        samples=int(row.features.get("samples", 0)),
        strong=p.strong,
        threshold=p.threshold,
        created_at=row.created_at,
        avg_draft_delta=round(float(avg), 3) if avg is not None else None,
        drafts_scored=int(count),
    )


# ---- story bank --------------------------------------------------------------------------------


def _story_out(s: m.StoryBankEntry) -> StoryOut:
    return StoryOut(
        id=s.id,
        category=s.category,
        headline=s.headline,
        details=s.details,
        numbers=[str(n) for n in s.numbers],
        tags=[str(t) for t in s.tags],
        created_at=s.created_at,
    )


@router.get("/stories")
async def list_stories(scope: Scope) -> list[StoryOut]:
    return [_story_out(s) for s in await scope.list_stories()]


@router.post("/stories", status_code=status.HTTP_201_CREATED)
async def add_story(body: StoryIn, scope: Scope) -> StoryOut:
    await scope.ensure_profile()
    # A number is allowed only if it's literally in the story text: the Story Bank must stay true.
    text = f"{body.headline} {body.details}"
    missing = [n for n in body.numbers if n not in text]
    if missing:
        raise InvalidInput(f"These numbers aren't in the story text: {', '.join(missing[:5])}")
    entry = await scope.add_story(
        category=body.category, headline=body.headline, details=body.details, numbers=body.numbers, tags=body.tags
    )
    return _story_out(entry)


@router.delete("/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(story_id: uuid.UUID, scope: Scope) -> Response:
    await scope.delete_story(story_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/story-bank/extract")
async def extract_stories(body: StoryExtractIn, scope: Scope, request: Request) -> list[ProposedStory]:
    """Turn a free-form answer into proposed Story Bank entries (not saved). Numbers are kept only
    when they appear verbatim in your answer."""
    from deno_llm import Role, build_stack, get_prompt

    settings = getattr(request.app.state, "settings", None) or get_settings()
    stack = build_stack(settings, getattr(request.app.state, "redis", None))
    p = get_prompt("story.extract")
    try:
        out = await stack.router.structured(Role.FAST, ProposedStories, temperature=0).ainvoke(
            p.messages(text=body.text), config=p.config()
        )
    except Exception as exc:
        raise UpstreamUnavailable(
            "Story extraction is unavailable right now. Add stories by hand, or try again."
        ) from exc
    stories = []
    for s in out.stories[:8]:
        numbers = [n for n in s.numbers if n and n in body.text]
        stories.append(
            ProposedStory(category=s.category, headline=s.headline[:300], details=s.details[:5000], numbers=numbers)
        )
    return stories


# ---- content plans ---------------------------------------------------------------------------------


async def _check_plan_quota(scope: UserScope) -> None:
    profile = await scope.ensure_profile()
    quota = (
        await scope.session.execute(
            select(m.Quota).where(m.Quota.plan == (profile.plan or Plan.FREE), m.Quota.kind == UsageKind.CONTENT_PLAN)
        )
    ).scalar_one_or_none()
    if quota is None:
        return
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if await scope.usage_since(UsageKind.CONTENT_PLAN, month_start) >= quota.monthly_limit:
        raise QuotaExceeded(f"Your plan includes {quota.monthly_limit} content plans a month.")


@router.post("/projects/{project_id}/content-plans", status_code=status.HTTP_202_ACCEPTED)
async def create_plan(
    project_id: uuid.UUID, body: PlanCreate, scope: Scope, background: BackgroundTasks
) -> PlanCreated:
    await scope.get_project(project_id)
    await _check_plan_quota(scope)
    run_id = body.run_id
    if run_id is not None:
        run = await scope.get_run(run_id)
        if run.project_id != project_id or run.status not in (RunStatus.SUCCEEDED, RunStatus.AWAITING_REVIEW):
            raise InvalidInput("Build the plan on a finished validation run of this idea.")
    else:
        latest = await scope.latest_run_for_project(project_id)
        run_id = latest.id if latest and latest.status in (RunStatus.SUCCEEDED, RunStatus.AWAITING_REVIEW) else None
    plan = await scope.create_content_plan(project_id, run_id, body.days)
    await scope.record_usage(UsageKind.CONTENT_PLAN, plan_id=str(plan.id))
    background.add_task(enqueue, TASK_CONTENT_PLAN, plan_id=str(plan.id), user_id=str(scope.user_id))
    return PlanCreated(plan_id=plan.id, status=RunStatus.QUEUED, events_url=f"/api/v1/content-plans/{plan.id}/events")


@router.get("/projects/{project_id}/content-plans")
async def list_plans(project_id: uuid.UUID, scope: Scope) -> list[PlanOut]:
    return [
        PlanOut(
            id=p.id,
            project_id=p.project_id,
            run_id=p.run_id,
            days=p.days,
            status=p.status,
            created_at=p.created_at,
            briefs=[],
        )
        for p in await scope.list_content_plans(project_id)
    ]


def _draft_out(draft: m.ContentDraft, gates: list[m.GateResult]) -> DraftOut:
    return DraftOut(
        id=draft.id,
        version=draft.version,
        text=draft.text,
        first_comment=draft.first_comment,
        status=draft.status,
        edited_by_user=draft.edited_by_user,
        gates=[GateLayerOut(layer=g.layer, passed=g.passed, score=g.score, findings=list(g.findings)) for g in gates],
    )


@router.get("/content-plans/{plan_id}")
async def get_plan(plan_id: uuid.UUID, scope: Scope) -> PlanOut:
    plan = await scope.get_content_plan(plan_id)
    briefs = await scope.list_briefs(plan_id)
    drafts = {d.brief_id: d for d in await scope.latest_drafts(plan_id)}
    gates = await scope.gate_results([d.id for d in drafts.values()])
    names = {
        c.id: c.name
        for c in (
            await scope.session.execute(
                select(m.Community).where(m.Community.id.in_([b.community_id for b in briefs if b.community_id]))
            )
        ).scalars()
    }
    return PlanOut(
        id=plan.id,
        project_id=plan.project_id,
        run_id=plan.run_id,
        days=plan.days,
        status=plan.status,
        created_at=plan.created_at,
        briefs=[
            BriefOut(
                id=b.id,
                day=b.day,
                platform=b.platform.value,
                community=names.get(b.community_id) if b.community_id else None,
                hook_formula=b.hook_formula,
                angle=b.angle,
                is_promotional=b.is_promotional,
                draft=_draft_out(drafts[b.id], gates.get(drafts[b.id].id, [])) if b.id in drafts else None,
            )
            for b in briefs
        ],
    )


async def owned_plan_status(
    plan_id: uuid.UUID, user_id: UserId, maker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]
) -> RunStatus:
    async with maker() as session:
        return (await UserScope(session, user_id).get_content_plan(plan_id)).status


@router.get("/content-plans/{plan_id}/events", response_class=EventSourceResponse, dependencies=[Depends(rate_limit)])
async def plan_events(
    plan_id: uuid.UUID,
    plan_status: Annotated[RunStatus, Depends(owned_plan_status)],
    events: Events,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=64)] = None,
) -> AsyncIterable[ServerSentEvent]:
    saw_any = False
    async for event in events.follow(str(plan_id), after=last_event_id or "0-0", block_ms=HEARTBEAT_MS):
        if event is None:
            if not saw_any and plan_status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
                yield _sse(RunEvent(type="status", data={"status": plan_status.value}, id="0-1"))
                return
            yield ServerSentEvent(comment="heartbeat")
            continue
        saw_any = True
        yield _sse(event)


def _sse(event: RunEvent) -> ServerSentEvent:
    return ServerSentEvent(data={"type": event.type, "ts": event.ts, **event.data}, event=event.type, id=event.id)


# ---- drafts & gates ----------------------------------------------------------------------------------


async def _gate_context(scope: UserScope, brief: m.ContentBrief) -> tuple[GateContext, VoiceProfile | None]:
    allowed: set[str] = set()
    allowed_words: set[str] = set()
    if brief.story_entry_id:
        story = await scope.get_story(brief.story_entry_id, include_deleted=True)
        story_text = f"{story.headline} {story.details} {' '.join(map(str, story.numbers))}"
        allowed, allowed_words = numbers_in(story_text), number_words_in(story_text)
    rule = (
        (await community_rules(scope.session, [brief.community_id])).get(brief.community_id)
        if brief.community_id
        else None
    )
    platform: Literal["reddit", "linkedin"] = "reddit" if brief.platform.value == "reddit" else "linkedin"
    ctx = GateContext(
        platform=platform,
        community=CommunityRules(
            platform=platform,
            promo_policy=rule.promo_policy if rule else None,
            ai_policy=rule.ai_policy if rule else None,
        ),
        is_promotional=brief.is_promotional,
        allowed_numbers=frozenset(allowed),
        allowed_number_words=frozenset(allowed_words),
        check_numbers=True,
        story_attached=brief.story_entry_id is not None,
    )
    profile_row = await scope.latest_voice_profile()
    profile = VoiceProfile.from_dict(profile_row.delta_baseline) if profile_row else None
    return ctx, profile


@router.patch("/drafts/{draft_id}")
async def edit_draft(draft_id: uuid.UUID, body: DraftEdit, scope: Scope) -> DraftOut:
    """Save your edit as a new version and re-run the gates on it."""
    current = await scope.get_draft(draft_id)
    brief = await scope.get_brief(current.brief_id)
    ctx, profile = await _gate_context(scope, brief)
    report = run_gates(body.text, ctx, profile=profile)
    new = await scope.add_draft(
        brief,
        text=body.text,
        first_comment=current.first_comment,
        status=DraftStatus.GATED if report.passed else DraftStatus.DRAFT,
        edited_by_user=True,
        gate_layers=report.to_dict()["layers"],  # type: ignore[arg-type]
    )
    return _draft_out(new, (await scope.gate_results([new.id])).get(new.id, []))


@router.post("/drafts/{draft_id}/approve")
async def approve_draft(draft_id: uuid.UUID, scope: Scope) -> DraftOut:
    draft = await scope.get_draft(draft_id)
    if draft.status == DraftStatus.DRAFT:
        raise Conflict("This draft still fails a gate. Fix the flagged lines (or edit it) before approving.")
    draft.status = DraftStatus.APPROVED
    return _draft_out(draft, (await scope.gate_results([draft.id])).get(draft.id, []))


@router.post("/drafts/{draft_id}/reject")
async def reject_draft(draft_id: uuid.UUID, scope: Scope) -> DraftOut:
    draft = await scope.get_draft(draft_id)
    draft.status = DraftStatus.REJECTED
    return _draft_out(draft, (await scope.gate_results([draft.id])).get(draft.id, []))


@router.post("/drafts/{draft_id}/export")
async def export_draft(draft_id: uuid.UUID, scope: Scope) -> DraftOut:
    """Mark as copied out for posting. Deno never posts on your behalf."""
    draft = await scope.get_draft(draft_id)
    if draft.status != DraftStatus.APPROVED:
        raise Conflict("Approve the draft before exporting it.")
    draft.status = DraftStatus.EXPORTED
    return _draft_out(draft, (await scope.gate_results([draft.id])).get(draft.id, []))


async def _check_audit_quota(scope: UserScope) -> None:
    profile = await scope.ensure_profile()
    quota = (
        await scope.session.execute(
            select(m.Quota).where(m.Quota.plan == (profile.plan or Plan.FREE), m.Quota.kind == UsageKind.AUDIT)
        )
    ).scalar_one_or_none()
    if quota is None:
        return
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if await scope.usage_since(UsageKind.AUDIT, month_start) >= quota.monthly_limit:
        raise QuotaExceeded(f"Your plan includes {quota.monthly_limit} audits a month.")


@router.post("/gates/audit")
async def audit(body: AuditIn, scope: Scope) -> AuditOut:
    """Run the deterministic gates on any text (Ban Risk Studio). Counts toward the monthly audit quota."""
    await _check_audit_quota(scope)
    await scope.record_usage(UsageKind.AUDIT)
    rules = None
    if body.community:
        row = (
            await scope.session.execute(select(m.Community).where(m.Community.name == body.community).limit(1))
        ).scalar_one_or_none()
        if row is not None:
            rules = (await community_rules(scope.session, [row.id])).get(row.id)
    ctx = GateContext(
        platform=body.platform,
        community=CommunityRules(
            name=body.community or "",
            platform=body.platform,
            promo_policy=rules.promo_policy if rules else None,
            ai_policy=rules.ai_policy if rules else None,
        ),
        is_promotional=body.is_promotional,
    )
    profile_row = await scope.latest_voice_profile()
    profile = VoiceProfile.from_dict(profile_row.delta_baseline) if profile_row else None
    report = run_gates(body.text, ctx, profile=profile)
    layers = cast(list[dict[str, Any]], report.to_dict()["layers"])
    return AuditOut(
        passed=report.passed,
        layers=[GateLayerOut(**layer) for layer in layers],
        autofixed=autofix(body.text),
    )


# ---- communities ---------------------------------------------------------------------------------------


@router.get("/runs/{run_id}/communities")
async def run_communities(run_id: uuid.UUID, scope: Scope) -> list[CommunityOut]:
    rows = await scope.list_run_communities(run_id)
    rules = await community_rules(scope.session, [c.id for _, c in rows])
    return [_community_out(c, rules.get(c.id), rc) for rc, c in rows]


@router.get("/communities")
async def communities(scope: Scope) -> list[CommunityOut]:
    from deno_core.db.repositories import list_communities

    rows = await list_communities(scope.session)
    rules = await community_rules(scope.session, [c.id for c in rows])
    return [_community_out(c, rules.get(c.id), None) for c in rows if c.id in rules]


def _community_out(c: m.Community, rule: m.CommunityRule | None, rc: m.RunCommunity | None) -> CommunityOut:
    return CommunityOut(
        id=c.id,
        platform=c.platform.value,
        name=c.name,
        url=c.url,
        audience=c.audience,
        relevance=rc.relevance if rc else None,
        evidence_count=rc.evidence_count if rc else None,
        karma_gate=rule.karma_gate if rule else None,
        promo_policy=rule.promo_policy if rule else None,
        ai_policy=rule.ai_policy if rule else None,
        cadence=rule.cadence if rule else None,
        rules_verified=bool(rule and rule.verified_at),
    )
