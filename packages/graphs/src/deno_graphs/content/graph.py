"""Content graph.

brief_planner ─► [Send] draft×brief (write → L1 autofix → gates → rewrite failing spans ≤2 → L5 judge)
              ─► assemble

Honesty rules enforced in code, not just in prompts:
- A draft may contain a number only if it appears in the Story Bank entry it draws on (L1 unsourced-number
  check with ``allowed_numbers``). Anything else blocks the draft.
- Drafts are never posted. Approval, edits and export happen through the API; an edited draft is re-gated.
- Promotional slots are capped (≤1 in 10) and never placed in communities whose rules forbid promotion.
"""

from __future__ import annotations

import operator
import re
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from deno_core.db import models as m
from deno_core.db.enums import DraftStatus, Platform
from deno_core.db.repositories import UserScope, community_rules, get_hook_patterns
from deno_core.gcp import searxng_auth_headers
from deno_core.logging import get_logger
from deno_core.observability import GATE_RESULTS
from deno_core.runs import RunContext
from deno_gates import CommunityRules, GateContext, VoiceProfile, autofix, number_words_in, numbers_in, run_gates
from deno_graphs.content.hooks import HOOKS, NEEDS_STORY, NO_STORY_HOOKS, hook_list
from deno_llm import LLMStack, Role, get_prompt

log = get_logger(__name__)
MAX_REWRITES = 2
NO_PROMO = re.compile(r"strict|feedback thread only|no self|not allowed|banned|zero", re.IGNORECASE)


# ---- schemas ---------------------------------------------------------------------------


class SlotAngle(BaseModel):
    slot: str
    angle: str
    hook_formula: str
    story_id: str | None = None


class BriefPlan(BaseModel):
    slots: list[SlotAngle]


class JudgeCheck(BaseModel):
    tell: int = Field(ge=1, le=22)
    quote: str
    fix: str


class JudgeVerdict(BaseModel):
    passed: bool
    issues: list[JudgeCheck]


_VERDICT_LINE = re.compile(r"VERDICT:\s*(PASS|FAIL)", re.IGNORECASE)
_TELL_LINE = re.compile(r"^\W*(\d{1,2})\s*\|\s*(.*?)\s*\|\s*(.+)$", re.MULTILINE)


def parse_judge(text: str) -> JudgeVerdict:
    """Line protocol (guided JSON stalls on this model). No parsable verdict counts as a failure."""
    verdict = _VERDICT_LINE.search(text)
    issues = [
        JudgeCheck(tell=int(m.group(1)), quote=m.group(2).strip('"')[:200], fix=m.group(3).strip()[:300])
        for m in _TELL_LINE.finditer(text)
        if 1 <= int(m.group(1)) <= 22
    ]
    passed = bool(verdict and verdict.group(1).upper() == "PASS") and not any(i.tell == 21 for i in issues)
    return JudgeVerdict(passed=passed, issues=issues)


class ContentState(TypedDict, total=False):
    plan_id: str
    project_id: str
    run_id: str | None
    days: int
    briefs: list[dict[str, Any]]
    drafted: Annotated[list[dict[str, Any]], operator.add]
    summary: dict[str, Any]


@dataclass
class ContentDeps:
    ctx: RunContext  # run_id = plan id; events go to the plan's stream
    stack: LLMStack

    async def scope(self) -> Any:
        return _Tx(self)


class _Tx:
    def __init__(self, deps: ContentDeps) -> None:
        self._deps = deps
        self._session: Any = None

    async def __aenter__(self) -> UserScope:
        self._session = self._deps.ctx.sessionmaker()
        await self._session.__aenter__()
        await self._session.begin()
        return self._deps.ctx.scope(self._session)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            await self._session.commit()
        else:
            await self._session.rollback()
        await self._session.__aexit__(exc_type, exc, tb)


def deps_of(config: RunnableConfig) -> ContentDeps:
    return config["configurable"]["deps"]  # type: ignore[no-any-return]


# ---- scheduling (deterministic) ------------------------------------------------------------


@dataclass(frozen=True)
class Slot:
    id: str
    day: int
    platform: Literal["linkedin", "reddit"]
    community_id: uuid.UUID | None
    community: str
    rules: str
    promo_allowed: bool
    is_promotional: bool = False


def schedule(days: int, communities: list[tuple[m.Community, m.CommunityRule | None]]) -> list[Slot]:
    """LinkedIn on alternate days; each Reddit community no more often than its rules allow (default weekly).
    At most one promotional slot per ten, only where promotion is allowed, never before day 5."""
    slots: list[Slot] = []
    for day in range(1, days + 1, 2):
        slots.append(Slot(f"S{len(slots) + 1}", day, "linkedin", None, "", "LinkedIn feed", True))
    for index, (community, rule) in enumerate(communities[:4]):
        gap = max(rule.min_days_between_posts if rule and rule.min_days_between_posts else 7, 4)
        promo_policy = (rule.promo_policy or "") if rule else ""
        text_rules = "; ".join(
            x for x in (promo_policy, rule.ai_policy if rule else None, rule.cadence if rule else None) if x
        )
        for day in range(2 + index, days + 1, gap):
            slots.append(
                Slot(
                    f"S{len(slots) + 1}",
                    day,
                    "reddit",
                    community.id,
                    community.name,
                    text_rules or "No published rules on file; read the sidebar before posting",
                    bool(promo_policy) and not NO_PROMO.search(promo_policy),
                )
            )
    slots.sort(key=lambda s: (s.day, s.platform))
    promo_budget = len(slots) // 10
    out: list[Slot] = []
    for slot in slots:
        make_promo = promo_budget > 0 and slot.promo_allowed and slot.day >= 5
        if make_promo:
            promo_budget -= 1
        out.append(
            Slot(
                slot.id,
                slot.day,
                slot.platform,
                slot.community_id,
                slot.community,
                slot.rules,
                slot.promo_allowed,
                make_promo,
            )
        )
    return out


# ---- trend miner ---------------------------------------------------------------------------

_HOOK_LINE = re.compile(r"^\W*(S\d+)\W*\|\s*(F\d{1,2})\b", re.MULTILINE)


async def mine_hooks(d: ContentDeps, communities: list[m.Community]) -> None:
    """Top posts of the last 30 days per community → hook formula per post → formulas ranked by engagement
    relative to the community median. Stored in hook_patterns (global, reused for 24 h). Best effort."""
    import statistics
    from datetime import UTC, datetime, timedelta

    from deno_core.db.repositories import replace_hook_patterns
    from deno_core.settings import get_settings
    from deno_llm import UNTRUSTED_RULE, SourceBlock, wrap_sources
    from deno_sources import ValkeyCache, build_fetcher
    from deno_sources.reddit import RedditClient
    from deno_sources.registry import SourceConfig

    settings = get_settings()
    fetcher = build_fetcher(
        SourceConfig(
            searxng_url=settings.searxng_url,
            robots_opt_in=settings.sources_robots_opt_in,
            searxng_headers=searxng_auth_headers(settings),
        ),
        cache=ValkeyCache(d.ctx.events.redis),
    )
    p = get_prompt("content.hook_classifier")
    try:
        for community in communities[:2]:
            try:
                posts = await RedditClient(fetcher).top_posts(
                    community.name, since=datetime.now(UTC) - timedelta(days=30), limit=30
                )
            except Exception as exc:
                log.warning("hook_miner_fetch_failed", community=community.name, error=type(exc).__name__)
                continue
            if len(posts) < 5:
                continue
            labelled = {f"S{i + 1}": post for i, post in enumerate(posts)}
            blocks = [
                SourceBlock(id=k, url=v.canonical_url, source=community.name, text=v.text[:300])
                for k, v in labelled.items()
            ]
            raw = await d.stack.router.chat(Role.FAST, temperature=0).ainvoke(
                p.messages(untrusted_rule=UNTRUSTED_RULE, hooks=hook_list(), posts=wrap_sources(blocks)),
                config=p.config(),
            )
            formula_of = {
                m_.group(1): m_.group(2) for m_ in _HOOK_LINE.finditer(str(raw.content)) if m_.group(2) in HOOKS
            }
            median = max(1.0, statistics.median(post.engagement.score or 0 for post in posts))
            by_formula: dict[str, list[tuple[float, str]]] = {}
            for key, post in labelled.items():
                if key in formula_of:
                    by_formula.setdefault(formula_of[key], []).append(
                        ((post.engagement.score or 0) / median, post.canonical_url)
                    )
            rows = [
                {
                    "formula_id": formula,
                    "topic": community.name,
                    "relative_engagement": round(statistics.mean(r for r, _ in items), 3),
                    "sample_urls": [u for _, u in sorted(items, reverse=True)[:3]],
                }
                for formula, items in by_formula.items()
                if len(items) >= 2  # one post is an anecdote, not a pattern
            ]
            async with await d.scope() as scope:
                await replace_hook_patterns(scope.session, community.id, Platform.REDDIT, rows)
            log.info("hooks_mined", community=community.name, posts=len(posts), formulas=len(rows))
    finally:
        await fetcher.aclose()


# ---- nodes -------------------------------------------------------------------------------


async def brief_planner(state: ContentState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    await d.ctx.emit("node_started", node="brief_planner")
    async with await d.scope() as scope:
        project = await scope.get_project(uuid.UUID(state["project_id"]))
        claims: list[m.Claim] = []
        run_communities: list[tuple[m.RunCommunity, m.Community]] = []
        if state.get("run_id"):
            run_id = uuid.UUID(str(state["run_id"]))
            claims = await scope.list_claims(run_id)
            run_communities = await scope.list_run_communities(run_id)
        rules = await community_rules(scope.session, [c.id for _, c in run_communities])
        stories = await scope.list_stories()
        hooks = await get_hook_patterns(scope.session, [c.id for _, c in run_communities])
    communities = [(c, rules.get(c.id)) for _, c in run_communities if c.platform == Platform.REDDIT]
    if not hooks and communities:
        await d.ctx.emit("log", message="Measuring which openings work in your communities right now…")
        try:
            await mine_hooks(d, [c for c, _ in communities])
        except Exception as exc:  # trends are a bonus; planning goes on without them
            log.warning("hook_miner_failed", error=type(exc).__name__)
        async with await d.scope() as scope:
            hooks = await get_hook_patterns(scope.session, [c.id for c, _ in communities])
    slots = schedule(state["days"], communities)
    pain = [c for c in claims if c.analyst in ("pain", "demand", "icp") and not c.dropped][:12]
    popular_hooks = (
        "; ".join(f"{h.formula_id} in {h.topic} ({h.relative_engagement}x median)" for h in hooks[:6])
        or "none measured yet"
    )
    p = get_prompt("content.brief_planner")
    plan = await d.stack.router.structured(Role.STRONG, BriefPlan, temperature=0.5).ainvoke(
        p.messages(
            product=project.idea[:400],
            claims="\n".join(f"- {c.text}" for c in pain) or "- (no validation run yet)",
            stories="\n".join(f"{s.id}: [{s.category.value}] {s.headline} :: {s.details[:300]}" for s in stories)
            or "(empty: write from general experience, no figures)",
            hooks=hook_list() + f"\nHooks that do well in these communities right now: {popular_hooks}",
            slots="\n".join(
                f"{s.id}, day {s.day}, {s.platform}, {s.community or '-'}, {'promo' if s.is_promotional else 'value'}"
                for s in slots
            ),
        ),
        config=p.config(),
    )
    by_slot = {a.slot: a for a in plan.slots}
    story_ids = {str(s.id) for s in stories}
    briefs = []
    swaps = 0
    for s in slots:
        a = by_slot.get(s.id)
        if a is None:
            continue
        hook = a.hook_formula if a.hook_formula in HOOKS else "F20"
        has_story = a.story_id in story_ids
        if not has_story and hook in NEEDS_STORY:
            hook = NO_STORY_HOOKS[swaps % len(NO_STORY_HOOKS)]  # no invented experiences to hang it on
            swaps += 1
        briefs.append(
            {
                "day": s.day,
                "platform": Platform(s.platform),
                "community_id": s.community_id,
                "hook_formula": hook,
                "angle": a.angle.strip()[:1000],
                "is_promotional": s.is_promotional,
                "story_entry_id": uuid.UUID(a.story_id) if a.story_id in story_ids else None,
                "_rules": s.rules,
                "_community": s.community,
            }
        )
    async with await d.scope() as scope:
        rows = await scope.replace_briefs(
            uuid.UUID(state["plan_id"]), [{k: v for k, v in b.items() if not k.startswith("_")} for b in briefs]
        )
    out = [
        {"brief_id": str(row.id), "rules": b["_rules"], "community": b["_community"]}
        for row, b in zip(rows, briefs, strict=True)
    ]
    await d.ctx.emit("node_finished", node="brief_planner", briefs=len(out))
    return {"briefs": out}


def fan_out(state: ContentState) -> list[Send] | str:
    if not state.get("briefs"):
        return "assemble"
    return [Send("draft", {**b, "plan_id": state["plan_id"], "run_id": state.get("run_id")}) for b in state["briefs"]]


def _findings_text(report: Any, judge: JudgeVerdict | None = None) -> str:
    lines = [
        f'- {f.rule_id}: "{f.quote}" → {f.fix}' for r in report.failing for f in r.findings if f.severity == "block"
    ]
    if judge:
        lines += [f'- judge tell {i.tell}: "{i.quote}" → {i.fix}' for i in judge.issues]
    return "\n".join(lines[:25])


async def draft(payload: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    brief_id = uuid.UUID(payload["brief_id"])
    await d.ctx.emit("node_started", node="draft", brief_id=str(brief_id))
    async with await d.scope() as scope:
        brief = await scope.get_brief(brief_id)
        story = await scope.get_story(brief.story_entry_id) if brief.story_entry_id else None
        samples = await scope.list_voice_samples()
        profile_row = await scope.latest_voice_profile()
        claims: list[m.Claim] = []
        if payload.get("run_id"):
            claims = [c for c in await scope.list_claims(uuid.UUID(str(payload["run_id"]))) if c.analyst == "pain"][:6]
        rule_row = (
            (await community_rules(scope.session, [brief.community_id])).get(brief.community_id)
            if brief.community_id
            else None
        )
    platform = brief.platform.value
    allowed: set[str] = set()
    allowed_words: set[str] = set()
    story_text = ""
    if story:
        story_text = f"{story.headline} {story.details} {' '.join(map(str, story.numbers))}"
        allowed = numbers_in(story_text)
        allowed_words = number_words_in(story_text)
    profile = VoiceProfile.from_dict(profile_row.delta_baseline) if profile_row and profile_row.delta_baseline else None
    ctx = GateContext(
        platform="reddit" if platform == "reddit" else "linkedin",
        community=CommunityRules(
            name=payload.get("community") or "",
            platform="reddit" if platform == "reddit" else "linkedin",
            promo_policy=rule_row.promo_policy if rule_row else None,
            ai_policy=rule_row.ai_policy if rule_row else None,
        ),
        is_promotional=brief.is_promotional,
        allowed_numbers=frozenset(allowed),
        allowed_number_words=frozenset(allowed_words),
        check_numbers=True,
        story_attached=story is not None,
    )
    p = get_prompt("content.draft")
    writer = d.stack.router.chat(Role.STRONG, temperature=0.8)
    community_line = f" ({payload['community']})" if payload.get("community") else ""
    text = str(
        (
            await writer.ainvoke(
                p.messages(
                    promo_rule="You may mention the product once, plainly, near the end."
                    if brief.is_promotional
                    else "Do not mention any product.",
                    voice_examples="\n---\n".join(s.text[:800] for s in samples[:3])
                    or "(no samples yet: write plainly)",
                    platform=platform,
                    community_line=community_line,
                    rules=payload.get("rules") or "-",
                    angle=brief.angle,
                    hook=f"{brief.hook_formula}: {HOOKS.get(brief.hook_formula or 'F20', '')}",
                    story=f"{story.headline}\n{story.details}\nNumbers you may use: {', '.join(map(str, story.numbers)) or 'none'}"
                    if story
                    else "none (so: no numbers, no invented anecdotes)",
                    context="\n".join(f"- {c.text}" for c in claims) or "-",
                ),
                config=p.config(brief_id=str(brief_id)),
            )
        ).content
    )
    text = autofix(text)
    report = run_gates(text, ctx, profile=profile)
    judge: JudgeVerdict | None = None
    rewrites = 0
    rewrite_prompt = get_prompt("content.rewrite")
    judge_prompt = get_prompt("content.judge")
    while True:
        if report.passed and judge is None:
            try:
                raw = await d.stack.router.chat(Role.JUDGE, temperature=0).ainvoke(
                    judge_prompt.messages(
                        platform=platform,
                        community_line=community_line,
                        story=story_text or "none (so any specific personal story or number is invented)",
                        text=text,
                    ),
                    config=judge_prompt.config(),
                )
                judge = parse_judge(str(raw.content))
            except Exception as exc:  # no editor check available: the draft stays unapproved
                log.warning("content_judge_failed", error=type(exc).__name__)
                judge = JudgeVerdict(
                    passed=False,
                    issues=[JudgeCheck(tell=22, quote="", fix="Editor check unavailable; review it yourself.")],
                )
        done = report.passed and (judge is None or judge.passed)
        if done or rewrites >= MAX_REWRITES:
            break
        rewrites += 1
        fixed = await d.stack.router.chat(Role.STRONG, temperature=0.4).ainvoke(
            rewrite_prompt.messages(
                story=story_text or "none",
                text=text,
                findings=_findings_text(report, judge if report.passed else None),
            ),
            config=rewrite_prompt.config(brief_id=str(brief_id)),
        )
        text = autofix(str(fixed.content))
        report = run_gates(text, ctx, profile=profile)
        judge = None
    layers = cast(list[dict[str, Any]], report.to_dict()["layers"])
    if judge is not None:
        layers.append(
            {
                "layer": "L5_judge",
                "passed": judge.passed,
                # Tells listed alongside a PASS are advice, not blockers.
                "score": None,
                "findings": [
                    {
                        "rule_id": f"L5.tell{i.tell}",
                        "message": "Reads as AI",
                        "quote": i.quote,
                        "fix": i.fix,
                        "severity": "block" if not judge.passed else "warn",
                    }
                    for i in judge.issues
                ],
            }
        )
    passed = report.passed and (judge is None or judge.passed)
    GATE_RESULTS.labels("passed" if passed else "failed").inc()
    async with await d.scope() as scope:
        brief = await scope.get_brief(brief_id)
        row = await scope.add_draft(
            brief,
            text=text,
            first_comment=None,
            status=DraftStatus.GATED if passed else DraftStatus.DRAFT,
            gate_layers=layers,
        )
    await d.ctx.emit("node_finished", node="draft", brief_id=str(brief_id), passed=passed, rewrites=rewrites)
    return {"drafted": [{"brief_id": str(brief_id), "draft_id": str(row.id), "passed": passed, "rewrites": rewrites}]}


async def assemble(state: ContentState, config: RunnableConfig) -> dict[str, Any]:
    drafted = state.get("drafted", [])
    summary = {
        "drafts": len(drafted),
        "passed": sum(1 for x in drafted if x["passed"]),
        "rewrites": sum(x["rewrites"] for x in drafted),
    }
    await deps_of(config).ctx.emit("progress", **summary)
    return {"summary": summary}


def build_content_graph(checkpointer: BaseCheckpointSaver[Any] | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    g = StateGraph(ContentState)
    g.add_node("brief_planner", brief_planner)
    g.add_node("draft", cast(Any, draft))
    g.add_node("assemble", assemble)
    g.add_edge(START, "brief_planner")
    g.add_conditional_edges("brief_planner", fan_out, ["draft", "assemble"])
    g.add_edge("draft", "assemble")
    g.add_edge("assemble", END)
    return g.compile(checkpointer=checkpointer)


async def run_content_plan(ctx: RunContext, *, settings: Any = None) -> dict[str, Any]:
    """Execute a content plan (ctx.run_id is the plan id). Returns the summary."""
    from deno_core.db.enums import RunStatus
    from deno_core.settings import get_settings
    from deno_graphs.validation.runner import checkpointer
    from deno_llm import build_stack

    settings = settings or get_settings()
    async with ctx.sessionmaker() as session, session.begin():
        scope = ctx.scope(session)
        plan = await scope.get_content_plan(ctx.run_id)
        plan.status = RunStatus.RUNNING
        thread_id, project_id, run_id, days = plan.thread_id, plan.project_id, plan.run_id, plan.days
    await ctx.emit("status", status="running")
    deps = ContentDeps(ctx=ctx, stack=build_stack(settings, ctx.events.redis))
    # max_concurrency: drafts fan out one branch per brief; each holds a DB connection and calls NIM
    # (40 req/min), so run a few at a time instead of all 14.
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "deps": deps},
        "recursion_limit": 40,
        "max_concurrency": 4,
    }
    status = RunStatus.SUCCEEDED
    summary: dict[str, Any] = {}
    try:
        async with checkpointer(settings) as saver:
            graph = build_content_graph(saver)
            snapshot = await graph.aget_state(config)
            payload = (
                None
                if snapshot.next
                else {
                    "plan_id": str(ctx.run_id),
                    "project_id": str(project_id),
                    "run_id": str(run_id) if run_id else None,
                    "days": days,
                }
            )
            result = await graph.ainvoke(payload, config)
            summary = dict(result.get("summary") or {})
    except Exception:
        log.exception("content_plan_failed")
        status = RunStatus.FAILED
    async with ctx.sessionmaker() as session, session.begin():
        plan = await ctx.scope(session).get_content_plan(ctx.run_id)
        plan.status = status
        usage = deps.stack.usage.summary()
        if usage["total_tokens"]:
            from deno_core.db.enums import UsageKind

            await ctx.scope(session).record_usage(
                UsageKind.LLM_TOKENS,
                units=int(usage["total_tokens"]),
                cost_usd=float(usage["cost_usd"]),
                plan_id=str(ctx.run_id),
            )
    await ctx.emit("status", status=status.value, **summary)
    return summary
