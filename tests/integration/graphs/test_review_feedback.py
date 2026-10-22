"""What the founder does around a run (flag claims, delete the idea) is respected by the graphs."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from deno_core.db import models as m
from deno_core.db.enums import ProjectStatus, Stance
from deno_core.db.repositories import UserScope
from deno_core.runs import RunContext
from deno_graphs.content.graph import BriefPlan, ContentDeps, brief_planner
from deno_graphs.validation.nodes import GraphDeps, finalize


class Events:
    async def publish(self, run_id: str, event: Any) -> str:
        return "0-1"

    async def is_cancelled(self, run_id: str) -> bool:
        return False


class CapturingRouter:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def structured(self, role: Any, schema: Any, **kwargs: Any) -> Any:
        router = self

        class Runnable:
            async def ainvoke(self, messages: list[Any], config: Any) -> BriefPlan:
                router.prompts.append("\n".join(str(msg.content) for msg in messages))
                return BriefPlan(slots=[])

        return Runnable()


async def test_claims_flagged_wrong_never_reach_the_content_plan(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with maker() as session, session.begin():
        scope = UserScope(session, user_id)
        await scope.ensure_profile()
        project = await scope.create_project("Onboarding emails that people actually open")
        run, _ = await scope.create_run(project.id)
        kept = await scope.add_claim(
            run.id,
            analyst="pain",
            text="Founders rewrite onboarding emails weekly",
            stance=Stance.SUPPORTS,
            chunk_ids=[],
        )
        wrong = await scope.add_claim(
            run.id, analyst="pain", text="Everyone reads every onboarding email", stance=Stance.SUPPORTS, chunk_ids=[]
        )
        await scope.flag_claims(run.id, [wrong.id])
        plan = await scope.create_content_plan(project.id, run.id, 7)
    router = CapturingRouter()
    ctx = RunContext(run_id=plan.id, user_id=user_id, events=Events(), sessionmaker=maker)  # type: ignore[arg-type]
    deps = ContentDeps(ctx=ctx, stack=SimpleNamespace(router=router))  # type: ignore[arg-type]

    state = {"plan_id": str(plan.id), "project_id": str(project.id), "run_id": str(run.id), "days": 7}
    await brief_planner(state, {"configurable": {"deps": deps}})  # type: ignore[arg-type]

    (prompt,) = router.prompts
    assert kept.text in prompt
    assert wrong.text not in prompt


async def test_a_run_whose_idea_was_deleted_still_finishes(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with maker() as session, session.begin():
        scope = UserScope(session, user_id)
        project = await scope.create_project("Onboarding emails that people actually open")
        run, _ = await scope.create_run(project.id)
        await scope.delete_project(project.id)
    ctx = RunContext(run_id=run.id, user_id=user_id, events=Events(), sessionmaker=maker)  # type: ignore[arg-type]
    deps = GraphDeps(ctx=ctx, settings=None, stack=None, fetcher=None)  # type: ignore[arg-type]

    out = await finalize({}, {"configurable": {"deps": deps}})

    assert out["review"]["flagged_any"] is False
    async with maker() as session:
        row = await session.get(m.Project, project.id)
        assert row is not None and row.deleted_at is not None
        assert row.status != ProjectStatus.VALIDATED
