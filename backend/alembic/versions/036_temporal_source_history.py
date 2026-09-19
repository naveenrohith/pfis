"""Add append-only temporal source snapshots for historical evaluation.

Revision ID: 036_temporal_source_history
Revises: 035_rec_conflict_contract
"""

import sqlalchemy as sa
from alembic import op

revision = "036_temporal_source_history"
down_revision = "035_rec_conflict_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temporal_source_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column(
            "ruleset_version",
            sa.String(length=40),
            nullable=False,
            server_default="pfis-temporal-source-history-1",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_temporal_source_snapshots_user_id",
        "temporal_source_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_temporal_source_snapshots_user_source_time",
        "temporal_source_snapshots",
        ["user_id", "source_type", "source_id", "captured_at"],
    )
    op.create_index(
        "ix_temporal_source_snapshots_user_time",
        "temporal_source_snapshots",
        ["user_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_temporal_source_snapshots_user_time", table_name="temporal_source_snapshots")
    op.drop_index(
        "ix_temporal_source_snapshots_user_source_time",
        table_name="temporal_source_snapshots",
    )
    op.drop_index("ix_temporal_source_snapshots_user_id", table_name="temporal_source_snapshots")
    op.drop_table("temporal_source_snapshots")
