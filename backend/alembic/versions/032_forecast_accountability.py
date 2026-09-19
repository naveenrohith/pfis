"""Add immutable cash-flow forecast snapshots and outcomes.

Revision ID: 032_forecast_accountability
Revises: 031_temporal_event_decisions
"""

import sqlalchemy as sa
from alembic import op

revision = "032_forecast_accountability"
down_revision = "031_temporal_event_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cash_flow_forecast_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("target_year", sa.Integer(), nullable=False),
        sa.Column("target_month", sa.Integer(), nullable=False),
        sa.Column("cutoff_date", sa.Date(), nullable=False),
        sa.Column("forecast_ruleset_version", sa.String(length=40), nullable=False),
        sa.Column("temporal_ruleset_version", sa.String(length=40), nullable=True),
        sa.Column("projected_spend", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("projected_net", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("projected_range_low", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("projected_range_high", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("expected_income", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("temporal_expected_income", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("temporal_expected_outflows", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "temporal_conflicted_outflows", sa.Numeric(precision=18, scale=2), nullable=False
        ),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("data_sufficiency", sa.String(length=12), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.CheckConstraint("target_month BETWEEN 1 AND 12", name="ck_forecast_snapshot_month"),
        sa.CheckConstraint("target_year BETWEEN 2020 AND 2030", name="ck_forecast_snapshot_year"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "target_year",
            "target_month",
            "cutoff_date",
            "forecast_ruleset_version",
            name="uq_cash_flow_forecast_snapshot_cutoff",
        ),
    )
    op.create_index(
        "ix_cash_flow_forecast_snapshots_user_id",
        "cash_flow_forecast_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_cash_flow_forecast_snapshots_user_target",
        "cash_flow_forecast_snapshots",
        ["user_id", "target_year", "target_month", "cutoff_date"],
    )
    op.create_table(
        "cash_flow_forecast_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("outcome_ruleset_version", sa.String(length=40), nullable=False),
        sa.Column("actual_income", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("actual_spend", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("actual_net", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("spend_absolute_error", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "spend_absolute_percentage_error", sa.Numeric(precision=8, scale=3), nullable=True
        ),
        sa.Column("spend_range_covered", sa.Boolean(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["cash_flow_forecast_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", name="uq_cash_flow_forecast_outcome_snapshot"),
    )
    op.create_index(
        "ix_cash_flow_forecast_outcomes_user_id",
        "cash_flow_forecast_outcomes",
        ["user_id"],
    )
    op.create_index(
        "ix_cash_flow_forecast_outcomes_user_evaluated",
        "cash_flow_forecast_outcomes",
        ["user_id", "evaluated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cash_flow_forecast_outcomes_user_evaluated", table_name="cash_flow_forecast_outcomes"
    )
    op.drop_index(
        "ix_cash_flow_forecast_outcomes_user_id", table_name="cash_flow_forecast_outcomes"
    )
    op.drop_table("cash_flow_forecast_outcomes")
    op.drop_index(
        "ix_cash_flow_forecast_snapshots_user_target", table_name="cash_flow_forecast_snapshots"
    )
    op.drop_index(
        "ix_cash_flow_forecast_snapshots_user_id", table_name="cash_flow_forecast_snapshots"
    )
    op.drop_table("cash_flow_forecast_snapshots")
