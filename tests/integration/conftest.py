"""Postgres-backed tests. Needs TEST_DATABASE_URL (CI service container, or
`docker compose -f compose.dev.yml --profile test up -d postgres-test` locally);
skipped when the database isn't reachable."""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from deno_core.db.session import build_engine

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:54329/deno_test")
ROOT = Path(__file__).resolve().parents[2]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if here in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.integration)


async def _reachable() -> bool:
    engine = build_engine(TEST_DATABASE_URL, pool_size=1, max_overflow=0)
    try:
        async with engine.connect():
            return True
    except (OSError, Exception):
        return False
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_url() -> str:
    # This fixture drops every table; never let it near the hosted Supabase project.
    if "supabase." in (make_url(TEST_DATABASE_URL).host or ""):
        pytest.exit("TEST_DATABASE_URL points at Supabase; tests need a throwaway Postgres", returncode=2)
    if not asyncio.run(_reachable()):
        pytest.skip("test Postgres not reachable (set TEST_DATABASE_URL)")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.cmd_opts = type("o", (), {"x": [f"url={TEST_DATABASE_URL}"]})()  # type: ignore[assignment]
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return TEST_DATABASE_URL


@pytest.fixture
async def engine(migrated_url: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_url, pool_size=2, max_overflow=0)
    yield eng
    await eng.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Each test runs inside a transaction that is rolled back afterwards."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        yield conn
        await trans.rollback()


@pytest.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as s:
        yield s
