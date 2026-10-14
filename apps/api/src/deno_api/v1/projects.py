"""Projects and the runs that validate them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, Query, Response, status
from sqlalchemy import select

from deno_api.deps import Scope
from deno_api.v1.schemas import (
    LatestRunOut,
    ProjectCreate,
    ProjectOut,
    ProjectPage,
    ProjectPatch,
    RunCreated,
    RunOut,
)
from deno_core.db.enums import Plan, RunStatus, UsageKind
from deno_core.db.models import Quota
from deno_core.errors import Conflict, QuotaExceeded, RateLimited
from deno_core.jobs import TASK_VALIDATION_RUN, enqueue

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, scope: Scope) -> ProjectOut:
    await scope.ensure_profile()
    project = await scope.create_project(body.idea, body.author_handle)
    return ProjectOut.model_validate(project)


@router.get("")
async def list_projects(
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> ProjectPage:
    page = await scope.list_projects(limit=limit, cursor=cursor)
    latest = await scope.latest_runs([p.id for p in page.items])
    items = []
    for p in page.items:
        out = ProjectOut.model_validate(p)
        if p.id in latest:
            run, verdict = latest[p.id]
            out.latest_run = LatestRunOut(
                id=run.id,
                status=run.status,
                error_code=run.error_code,
                created_at=run.created_at,
                finished_at=run.finished_at,
                verdict=verdict.verdict if verdict else None,
                confidence=verdict.confidence if verdict else None,
            )
        items.append(out)
    return ProjectPage(items=items, next_cursor=page.next_cursor)


@router.get("/{project_id}")
async def get_project(project_id: uuid.UUID, scope: Scope) -> ProjectOut:
    return ProjectOut.model_validate(await scope.get_project(project_id))


@router.patch("/{project_id}")
async def update_project(project_id: uuid.UUID, body: ProjectPatch, scope: Scope) -> ProjectOut:
    project = await scope.update_project(project_id, title=body.title, status=body.status)
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, scope: Scope) -> Response:
    await scope.delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/runs")
async def list_runs(project_id: uuid.UUID, scope: Scope) -> list[RunOut]:
    return [RunOut.model_validate(r) for r in await scope.list_runs(project_id)]


async def _check_quota(scope: Scope) -> None:
    profile = await scope.ensure_profile()
    plan = profile.plan or Plan.FREE
    quota = (
        await scope.session.execute(select(Quota).where(Quota.plan == plan, Quota.kind == UsageKind.VALIDATION_RUN))
    ).scalar_one_or_none()
    if quota is None:
        return
    if await scope.count_active_runs() >= quota.max_concurrent:
        raise RateLimited("You already have a validation running. Wait for it to finish, or cancel it.")
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if await scope.usage_since(UsageKind.VALIDATION_RUN, month_start) >= quota.monthly_limit:
        raise QuotaExceeded(f"Your plan includes {quota.monthly_limit} validation runs a month.")


@router.post("/{project_id}/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    project_id: uuid.UUID,
    scope: Scope,
    response: Response,
    background: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
) -> RunCreated:
    """Queue a validation run. Retrying with the same `Idempotency-Key` returns the same run (200)."""
    await scope.get_project(project_id)
    if idempotency_key and (existing := await scope.find_run_by_idempotency_key(idempotency_key)):
        if existing.project_id != project_id:
            raise Conflict("That idempotency key was used for another project.")
        response.status_code = status.HTTP_200_OK
        return RunCreated(run_id=existing.id, status=existing.status, events_url=_events_url(existing.id))
    await _check_quota(scope)
    run, _ = await scope.create_run(project_id, idempotency_key)
    await scope.record_usage(UsageKind.VALIDATION_RUN, run_id=run.id)
    # Background tasks run after the request transaction commits, so the worker
    # always finds the row. A lost enqueue is repaired by the requeue cron.
    background.add_task(enqueue, TASK_VALIDATION_RUN, run_id=str(run.id), user_id=str(scope.user_id))
    return RunCreated(run_id=run.id, status=RunStatus.QUEUED, events_url=_events_url(run.id))


def _events_url(run_id: uuid.UUID) -> str:
    return f"/api/v1/runs/{run_id}/events"
