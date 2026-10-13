"""The 2FA lookup against a Supabase-shaped ``auth.mfa_factors`` table."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from deno_api import deps


async def test_lookup_without_table_and_with_verified_or_unverified_factors(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    deps._mfa_cache.clear()
    verified, unverified = uuid.uuid4(), uuid.uuid4()
    # Plain Postgres has no auth.mfa_factors: nobody counts as enrolled.
    assert await deps._has_verified_factor(maker, verified) is False

    deps._mfa_cache.clear()
    async with engine.begin() as conn:
        await conn.execute(
            text("CREATE TABLE auth.mfa_factors (id uuid PRIMARY KEY, user_id uuid NOT NULL, status text NOT NULL)")
        )
        await conn.execute(
            text(
                "INSERT INTO auth.mfa_factors VALUES (gen_random_uuid(), :v, 'verified'), (gen_random_uuid(), :u, 'unverified')"
            ),
            {"v": verified, "u": unverified},
        )
    try:
        assert await deps._has_verified_factor(maker, verified) is True
        assert await deps._has_verified_factor(maker, unverified) is False
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE auth.mfa_factors"))
        deps._mfa_cache.clear()
