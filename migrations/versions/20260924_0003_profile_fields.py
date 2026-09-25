"""profile fields for the account page (product, timezone, role, handles, voice preset, notifications)

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("product_name", sa.String(length=120), nullable=True))
    op.add_column("profiles", sa.Column("product_url", sa.Text(), nullable=True))
    op.add_column("profiles", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column("profiles", sa.Column("founder_role", sa.String(length=40), nullable=True))
    op.add_column(
        "profiles",
        sa.Column(
            "handles", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
    )
    op.add_column("profiles", sa.Column("voice_preset", sa.String(length=40), nullable=True))
    op.add_column(
        "profiles",
        sa.Column(
            "notification_prefs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    for column in (
        "notification_prefs",
        "voice_preset",
        "handles",
        "founder_role",
        "timezone",
        "product_url",
        "product_name",
    ):
        op.drop_column("profiles", column)
