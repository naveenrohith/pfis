"""Add source-scoped parser quality telemetry.

Revision ID: 030_parser_source_telemetry
Revises: 029_account_deletion
"""

import sqlalchemy as sa
from alembic import op

revision = "030_parser_source_telemetry"
down_revision = "029_account_deletion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_events",
        sa.Column("source_institution", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_pipeline_events_source_created",
        "pipeline_events",
        ["source_institution", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_events_source_created", table_name="pipeline_events")
    op.drop_column("pipeline_events", "source_institution")
