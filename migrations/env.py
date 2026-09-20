"""Alembic environment (async, asyncpg)."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from deno_core.db import models
from deno_core.db.session import build_engine
from deno_core.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = models.Base.metadata


def database_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or get_settings().database_url
    if not url:
        raise RuntimeError("Set DATABASE_URL or pass -x url=postgresql+asyncpg://...")
    return url


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # Only manage our own schema: ignore Supabase/LangGraph tables we didn't declare.
    return not (type_ == "table" and reflected and compare_to is None)


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = build_engine(database_url(), pool_size=1, max_overflow=0)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()
    await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
