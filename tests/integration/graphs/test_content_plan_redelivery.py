"""A content-plan job delivered twice must not redo (and so wipe) the plan."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from deno_core.db import models as m
from deno_core.db.enums import DraftStatus, Platform, RunStatus
from deno_core.db.repositories import UserScope
from deno_core.events import RunEvents
from deno_core.runs import RunContext, lease_key
from deno_graphs.content.graph import run_content_plan

VALKEY_URL = "redis://127.0.0.1:6379/15"


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(VALKEY_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip("Valkey not reachable on 127.0.0.1:6379")
    yield client
    await client.flushdb()
    await client.aclose()


async def _plan_with_approved_draft(
    maker: async_sessionmaker[AsyncSession], status: RunStatus
) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    async with maker() as session, session.begin():
        scope = UserScope(session, user_id)
        await scope.ensure_profile()
        project = await scope.create_project("Onboarding emails that people actually open")
        plan = await scope.create_content_plan(project.id, None, 7)
        plan.status = status
        (brief,) = await scope.replace_briefs(
            plan.id, [{"day": 1, "platform": Platform.LINKEDIN, "angle": "why onboarding emails get ignored"}]
        )
        await scope.add_draft(brief, text="An edited, approved post.", first_comment=None, status=DraftStatus.APPROVED)
    return user_id, plan.id


async def _status(maker: async_sessionmaker[AsyncSession], plan_id: uuid.UUID) -> RunStatus:
    async with maker() as session:
        plan = await session.get(m.ContentPlan, plan_id)
        assert plan is not None
        return plan.status


async def _drafts(maker: async_sessionmaker[AsyncSession], plan_id: uuid.UUID) -> list[m.ContentDraft]:
    async with maker() as session:
        return list((await session.execute(select(m.ContentDraft).where(m.ContentDraft.plan_id == plan_id))).scalars())


async def test_a_finished_plan_delivered_again_is_left_alone(engine: AsyncEngine, redis: Redis) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id, plan_id = await _plan_with_approved_draft(maker, RunStatus.SUCCEEDED)
    ctx = RunContext(run_id=plan_id, user_id=user_id, events=RunEvents(redis), sessionmaker=maker)

    assert await run_content_plan(ctx) == {}

    drafts = await _drafts(maker, plan_id)
    assert [d.status for d in drafts] == [DraftStatus.APPROVED], "the founder's approved draft survives"
    assert await _status(maker, plan_id) == RunStatus.SUCCEEDED, "the plan was not started over"


async def test_a_plan_already_being_executed_is_not_started_twice(engine: AsyncEngine, redis: Redis) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id, plan_id = await _plan_with_approved_draft(maker, RunStatus.RUNNING)
    await redis.set(lease_key(str(plan_id)), "another-worker", ex=60)
    ctx = RunContext(run_id=plan_id, user_id=user_id, events=RunEvents(redis), sessionmaker=maker)

    assert await run_content_plan(ctx) == {}
    assert len(await _drafts(maker, plan_id)) == 1
    assert await _status(maker, plan_id) == RunStatus.RUNNING, "the other worker's run is untouched"
