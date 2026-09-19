"""Add durable user decisions for recomputable temporal events.

Revision ID: 031_temporal_event_decisions
Revises: 030_parser_source_telemetry
"""

import sqlalchemy as sa
from alembic import op

revision = "031_temporal_event_decisions"
down_revision = "030_parser_source_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temporal_event_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("event_kind", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("event_ruleset_version", sa.String(length=40), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=True),
        sa.Column("observed_date", sa.Date(), nullable=True),
        sa.Column("observed_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_id", name="uq_temporal_decision_user_event"),
    )
    op.create_index(
        "ix_temporal_event_decisions_user_id",
        "temporal_event_decisions",
        ["user_id"],
    )
    op.create_index(
        "ix_temporal_decisions_user_date",
        "temporal_event_decisions",
        ["user_id", "occurrence_date"],
    )
    op.create_index(
        "ix_temporal_decisions_user_state",
        "temporal_event_decisions",
        ["user_id", "decision"],
    )


def downgrade() -> None:
    op.drop_index("ix_temporal_decisions_user_state", table_name="temporal_event_decisions")
    op.drop_index("ix_temporal_decisions_user_date", table_name="temporal_event_decisions")
    op.drop_index("ix_temporal_event_decisions_user_id", table_name="temporal_event_decisions")
    op.drop_table("temporal_event_decisions")
