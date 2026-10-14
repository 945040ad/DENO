"""internal plan: team and tester accounts with effectively unlimited quotas

Grant it with: UPDATE profiles SET plan = 'internal' WHERE id = '<auth user id>';
(or `uv run python scripts/set_plan.py <email> internal`).

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("profiles", "quotas", "subscriptions")
UNLIMITED = 1_000_000
# Concurrency stays bounded: every run shares one NIM key (40 req/min).
QUOTAS = [("internal", kind, UNLIMITED, 3) for kind in ("validation_run", "content_plan", "audit")]


def _plans(values: str) -> None:
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_plan"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_plan"), table, f"plan IN ({values})")


def upgrade() -> None:
    _plans("'free', 'pro', 'internal'")
    quotas = sa.table(
        "quotas",
        sa.column("plan", sa.String),
        sa.column("kind", sa.String),
        sa.column("monthly_limit", sa.Integer),
        sa.column("max_concurrent", sa.Integer),
    )
    op.bulk_insert(
        quotas, [{"plan": p, "kind": k, "monthly_limit": lim, "max_concurrent": c} for p, k, lim, c in QUOTAS]
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE profiles SET plan = 'free' WHERE plan = 'internal'"))
    op.execute(sa.text("UPDATE subscriptions SET plan = 'free' WHERE plan = 'internal'"))
    op.execute(sa.text("DELETE FROM quotas WHERE plan = 'internal'"))
    _plans("'free', 'pro'")
