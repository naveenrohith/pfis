"""Persist daily account forecast cutoffs and observed outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "048_account_balance_forecast"
down_revision = "047_balance_source_cursor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_balance_forecast_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("financial_account_id", sa.String(length=36), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("balance_kind", sa.String(length=16), nullable=False),
        sa.Column("cutoff_date", sa.Date(), nullable=False),
        sa.Column("horizon_start", sa.Date(), nullable=False),
        sa.Column("horizon_end", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("forecast_ruleset_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("starting_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("starting_balance_as_of", sa.Date(), nullable=True),
        sa.Column("starting_balance_basis", sa.String(length=16), nullable=True),
        sa.Column("expected_ending_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("expected_change", sa.Numeric(18, 2), nullable=True),
        sa.Column("lowest_expected_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("lowest_expected_date", sa.Date(), nullable=True),
        sa.Column("first_shortfall_date", sa.Date(), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("historical_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "historical_activity_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("coverage_status", sa.String(length=12), nullable=False),
        sa.Column("position_status", sa.String(length=24), nullable=False),
        sa.Column("position_confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("data_sufficiency", sa.String(length=12), nullable=False),
        sa.Column("position_reason_codes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("points_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "horizon_days BETWEEN 1 AND 180",
            name="ck_account_balance_forecast_snapshot_horizon",
        ),
        sa.ForeignKeyConstraint(["financial_account_id"], ["financial_accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "financial_account_id",
            "cutoff_date",
            "horizon_days",
            "forecast_ruleset_version",
            name="uq_account_balance_forecast_snapshot_cutoff",
        ),
    )
    op.create_index(
        "ix_account_balance_forecast_snapshots_user_id",
        "account_balance_forecast_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_account_balance_forecast_snapshots_financial_account_id",
        "account_balance_forecast_snapshots",
        ["financial_account_id"],
    )
    op.create_index(
        "ix_account_balance_forecast_snapshots_user_account_cutoff",
        "account_balance_forecast_snapshots",
        ["user_id", "financial_account_id", "cutoff_date"],
    )

    op.create_table(
        "account_balance_forecast_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("financial_account_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("actual_observation_id", sa.String(length=36), nullable=False),
        sa.Column("actual_source", sa.String(length=24), nullable=False),
        sa.Column("actual_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("expected_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("low_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("high_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("signed_error", sa.Numeric(18, 2), nullable=False),
        sa.Column("absolute_error", sa.Numeric(18, 2), nullable=False),
        sa.Column("interval_covered", sa.Boolean(), nullable=True),
        sa.Column("predicted_risk", sa.String(length=24), nullable=False),
        sa.Column("outcome_ruleset_version", sa.String(length=40), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actual_balance >= 0",
            name="ck_account_balance_forecast_outcome_actual_nonnegative",
        ),
        sa.ForeignKeyConstraint(["financial_account_id"], ["financial_accounts.id"]),
        sa.ForeignKeyConstraint(["actual_observation_id"], ["account_balance_snapshots.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["account_balance_forecast_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "target_date",
            name="uq_account_balance_forecast_outcome_snapshot_date",
        ),
    )
    op.create_index(
        "ix_account_balance_forecast_outcomes_user_id",
        "account_balance_forecast_outcomes",
        ["user_id"],
    )
    op.create_index(
        "ix_account_balance_forecast_outcomes_financial_account_id",
        "account_balance_forecast_outcomes",
        ["financial_account_id"],
    )
    op.create_index(
        "ix_account_balance_forecast_outcomes_user_account_date",
        "account_balance_forecast_outcomes",
        ["user_id", "financial_account_id", "target_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_balance_forecast_outcomes_user_account_date",
        table_name="account_balance_forecast_outcomes",
    )
    op.drop_index(
        "ix_account_balance_forecast_outcomes_financial_account_id",
        table_name="account_balance_forecast_outcomes",
    )
    op.drop_index(
        "ix_account_balance_forecast_outcomes_user_id",
        table_name="account_balance_forecast_outcomes",
    )
    op.drop_table("account_balance_forecast_outcomes")
    op.drop_index(
        "ix_account_balance_forecast_snapshots_user_account_cutoff",
        table_name="account_balance_forecast_snapshots",
    )
    op.drop_index(
        "ix_account_balance_forecast_snapshots_financial_account_id",
        table_name="account_balance_forecast_snapshots",
    )
    op.drop_index(
        "ix_account_balance_forecast_snapshots_user_id",
        table_name="account_balance_forecast_snapshots",
    )
    op.drop_table("account_balance_forecast_snapshots")
