"""Async engine and session factory (SQLAlchemy 2.0 + asyncpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from deno_core.settings import get_settings

SUPABASE_TRANSACTION_POOLER_PORT = 6543


def build_engine(url: str, **overrides: Any) -> AsyncEngine:
    connect_args: dict[str, Any] = {"server_settings": {"application_name": "deno"}, "timeout": 10}
    if make_url(url).port == SUPABASE_TRANSACTION_POOLER_PORT:
        # PgBouncer in transaction mode can't keep prepared statements.
        connect_args |= {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    options: dict[str, Any] = {
        # At most 10 connections per process. Supabase's session pooler (:5432) allows 15 clients for the
        # whole project, so production uses the transaction pooler (:6543); see docs/09.
        "pool_size": 5,
        "max_overflow": 5,
        "pool_timeout": 30,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "connect_args": connect_args,
    }
    options.update(overrides)
    return create_async_engine(url, **options)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return build_engine(url)


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def session_scope(maker: async_sessionmaker[AsyncSession] | None = None) -> AsyncIterator[AsyncSession]:
    """One transaction: commit on success, roll back on error."""
    async with (maker or get_sessionmaker())() as session, session.begin():
        yield session
