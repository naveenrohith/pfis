"""Persist provider query coverage on sync runs.

Revision ID: 042_sync_coverage_metrics
Revises: 041_anomaly_prediction_label
"""

import sqlalchemy as sa
from alembic import op

revision = "042_sync_coverage_metrics"
down_revision = "041_anomaly_prediction_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sync_runs",
        sa.Column("coverage_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "sync_runs",
        sa.Column("coverage_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "sync_runs",
        sa.Column("coverage_pages", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sync_runs",
        sa.Column(
            "coverage_result_size_estimate",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    for column in (
        "coverage_complete",
        "coverage_truncated",
        "coverage_pages",
        "coverage_result_size_estimate",
    ):
        op.alter_column("sync_runs", column, server_default=None)


def downgrade() -> None:
    op.drop_column("sync_runs", "coverage_result_size_estimate")
    op.drop_column("sync_runs", "coverage_pages")
    op.drop_column("sync_runs", "coverage_truncated")
    op.drop_column("sync_runs", "coverage_complete")
