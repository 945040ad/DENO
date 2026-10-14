"""Set a user's plan by e-mail (free | pro | internal). Uses DATABASE_URL from .env.

    uv run python scripts/set_plan.py founder@example.com internal

`internal` = team/tester account with effectively unlimited quotas (migration 0004); billing never changes it.
The user must have signed up (and confirmed their e-mail) first.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from deno_core.db.enums import Plan
from deno_core.db.session import build_engine
from deno_core.settings import get_settings


async def main(email: str, plan: Plan) -> int:
    engine = build_engine(get_settings().database_url)
    async with engine.begin() as conn:
        user_id = await conn.scalar(text("SELECT id FROM auth.users WHERE lower(email) = lower(:e)"), {"e": email})
        if user_id is None:
            print(f"no Supabase user with e-mail {email}; sign up first")
            return 1
        await conn.execute(
            text("INSERT INTO profiles (id, plan) VALUES (:id, :plan) ON CONFLICT (id) DO UPDATE SET plan = :plan"),
            {"id": user_id, "plan": plan.value},
        )
    await engine.dispose()
    print(f"{email} → {plan.value}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in {p.value for p in Plan}:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1], Plan(sys.argv[2]))))
