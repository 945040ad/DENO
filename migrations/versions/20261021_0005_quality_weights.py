"""Quality verification: per-user weights/threshold on profiles, structured verdict on gate_results.

Revision ID: 20261021_0005_quality_weights
Revises: 20261014_0004_internal_plan
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261021_0005_quality_weights"
down_revision = "20261014_0004_internal_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("quality_weights", JSONB, nullable=True))
    op.add_column("profiles", sa.Column("quality_threshold", sa.Integer(), nullable=True))
    # The full QualityVerdict (per-dimension weight + explanation) for the quality_verification
    # layer. ``findings`` stays the human-readable per-dimension list; this keeps the numbers
    # the API needs (real weight, explanation) machine-readable instead of parsed back out of text.
    op.add_column("gate_results", sa.Column("meta", JSONB, nullable=True))
    # /content/quality/history and the adaptive threshold both scan one layer for one user,
    # newest first.
    op.create_index(
        "ix_gate_results_user_layer_created",
        "gate_results",
        ["user_id", "layer", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_gate_results_user_layer_created", table_name="gate_results")
    op.drop_column("gate_results", "meta")
    op.drop_column("profiles", "quality_threshold")
    op.drop_column("profiles", "quality_weights")
