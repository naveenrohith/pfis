"""Add an optional effective timestamp to account balance observations.

Revision ID: 043_balance_position_truth
Revises: 042_sync_coverage_metrics
"""

import sqlalchemy as sa
from alembic import op

revision = "043_balance_position_truth"
down_revision = "042_sync_coverage_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_balance_snapshots",
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("account_balance_snapshots", "effective_at")
