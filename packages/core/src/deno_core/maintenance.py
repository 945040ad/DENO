"""Scheduled maintenance, shared by the taskiq scheduler (compose / VPS) and the
API's /internal/cron endpoints (Cloud Scheduler on the free-tier deploy)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deno_core.db.repositories import purge_scraped_text, stale_queued_runs
from deno_core.jobs import TASK_VALIDATION_RUN, enqueue
from deno_core.logging import get_logger
from deno_core.settings import get_settings

log = get_logger(__name__)


async def purge_old_scraped_text(maker: async_sessionmaker[AsyncSession]) -> int:
    async with maker() as session, session.begin():
        purged = await purge_scraped_text(session, get_settings().scraped_text_retention_days)
    log.info("purged_scraped_text", documents=purged)
    return purged


async def requeue_stale_runs(maker: async_sessionmaker[AsyncSession]) -> int:
    """Outbox repair: re-send runs whose enqueue was lost (API committed, broker call failed)."""
    async with maker() as session:
        stale = await stale_queued_runs(session)
    for run_id, user_id in stale:
        await enqueue(TASK_VALIDATION_RUN, run_id=str(run_id), user_id=str(user_id))
    if stale:
        log.warning("requeued_stale_runs", count=len(stale))
    return len(stale)
