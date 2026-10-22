"""The content ``draft`` node against a real database, with a scripted LLM.

What these pin down: a quality regeneration has to clear the same bar as the original draft (gates
*and* the L5 judge, which is what catches invented anecdotes), and the stored text, gate layers and
quality score always describe the same version.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from deno_core.db import models as m
from deno_core.db.enums import Platform
from deno_core.db.repositories import UserScope
from deno_core.runs import RunContext
from deno_graphs.content.graph import ContentDeps, draft

ORIGINAL = (
    "Most onboarding emails I write get ignored. I suspect people skim the first line and move on. "
    "Does anyone have a subject line style that reliably gets opened?"
)
REGENERATED = (
    "Onboarding emails feel like shouting into a void. I suspect the subject line does most of the work. "
    "What makes you open one instead of archiving it?"
)


class Events:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, run_id: str, event: Any) -> str:
        self.published.append(event)
        return "0-1"


class ScriptedRouter:
    """Answers each prompt by name; ``judge`` and ``scores`` decide per draft text."""

    def __init__(self, judge: dict[str, str], scores: dict[str, int]) -> None:
        self.judge, self.scores = judge, scores
        self.judged: list[str] = []

    def chat(self, role: Any, temperature: float = 0) -> Any:
        router = self

        class Runnable:
            async def ainvoke(self, messages: list[Any], config: Any) -> Any:
                name, prompt = config["run_name"], str(messages[-1].content)
                if name == "content.draft":
                    return SimpleNamespace(content=ORIGINAL)
                if name == "content.quality_rewrite":
                    return SimpleNamespace(content=REGENERATED)
                text = ORIGINAL if ORIGINAL in prompt else REGENERATED
                if name == "content.judge":
                    router.judged.append(text)
                    return SimpleNamespace(content=router.judge[text])
                if name == "content.quality_scorer":
                    n = router.scores[text]
                    return SimpleNamespace(content=f"HOOK_STRENGTH: {n}\nENGAGEMENT_POTENTIAL: {n}\nORIGINALITY: {n}")
                raise AssertionError(f"unexpected prompt {name}")

        return Runnable()


async def _run_draft(engine: AsyncEngine, router: ScriptedRouter) -> tuple[m.ContentDraft, list[m.GateResult], Events]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with maker() as session, session.begin():
        scope = UserScope(session, user_id)
        profile = await scope.ensure_profile()
        profile.quality_threshold = 9  # nothing reaches it, so every regeneration is attempted
        project = await scope.create_project("Onboarding emails that people actually open")
        plan = await scope.create_content_plan(project.id, None, 7)
        (brief,) = await scope.replace_briefs(
            plan.id,
            [
                {
                    "day": 1,
                    "platform": Platform.LINKEDIN,
                    "angle": "why onboarding emails get ignored",
                    "hook_formula": "F20",
                }
            ],
        )
    events = Events()
    ctx = RunContext(run_id=plan.id, user_id=user_id, events=events, sessionmaker=maker)  # type: ignore[arg-type]
    deps = ContentDeps(ctx=ctx, stack=SimpleNamespace(router=router))  # type: ignore[arg-type]
    payload = {"brief_id": str(brief.id), "plan_id": str(plan.id), "project_id": str(project.id), "run_id": None}
    await draft(payload, {"configurable": {"deps": deps}})
    async with maker() as session:
        stored = (await session.execute(select(m.ContentDraft).where(m.ContentDraft.brief_id == brief.id))).scalar_one()
        gates = list((await session.execute(select(m.GateResult).where(m.GateResult.draft_id == stored.id))).scalars())
    return stored, gates, events


def _quality_scores(events: Events) -> dict[int, float]:
    return {e.data["attempt"]: e.data["score"] for e in events.published if e.type == "quality_check"}


async def test_a_regeneration_the_judge_rejects_is_never_stored(engine: AsyncEngine) -> None:
    router = ScriptedRouter(
        judge={ORIGINAL: "VERDICT: PASS", REGENERATED: "VERDICT: FAIL\n21 | onboarding | invented experience"},
        scores={ORIGINAL: 4, REGENERATED: 10},
    )
    stored, gates, events = await _run_draft(engine, router)

    assert REGENERATED in router.judged, "the regenerated text must go back through the judge"
    assert stored.text == ORIGINAL
    layers = {g.layer: g for g in gates}
    assert layers["L5_judge"].passed, "the stored draft carries the judge verdict for its own text"
    assert layers["quality_verification"].score == _quality_scores(events)[0]


async def test_stored_quality_score_belongs_to_the_stored_text(engine: AsyncEngine) -> None:
    router = ScriptedRouter(
        judge={ORIGINAL: "VERDICT: PASS", REGENERATED: "VERDICT: PASS"},
        scores={ORIGINAL: 8, REGENERATED: 1},
    )
    stored, gates, events = await _run_draft(engine, router)

    scores = _quality_scores(events)
    assert scores[0] > max(v for k, v in scores.items() if k > 0), "the regenerations scored worse"
    assert stored.text == ORIGINAL, "the best-scoring version is kept"
    quality = next(g for g in gates if g.layer == "quality_verification")
    assert quality.score == scores[0], "the score shown is the kept version's, not the last attempt's"
    assert {g.layer for g in gates} >= {"L5_judge", "quality_verification"}
