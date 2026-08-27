"""Add auditable recommendation decisions and outcomes.

Revision ID: 033_recommendation_decisions
Revises: 032_forecast_accountability
"""

import sqlalchemy as sa
from alembic import op

revision = "033_recommendation_decisions"
down_revision = "032_forecast_accountability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recommendation_states", sa.Column("recommendation_type", sa.String(length=24)))
    op.add_column("recommendation_states", sa.Column("title", sa.String(length=200)))
    op.add_column("recommendation_states", sa.Column("target", sa.String(length=80)))
    op.add_column("recommendation_states", sa.Column("expected_impact", sa.Text()))
    op.add_column("recommendation_states", sa.Column("evidence_json", sa.Text()))
    op.add_column("recommendation_states", sa.Column("reason_codes_json", sa.Text()))
    op.add_column(
        "recommendation_states", sa.Column("guidance_ruleset_version", sa.String(length=40))
    )
    op.add_column("recommendation_states", sa.Column("decision_as_of", sa.Date()))
    op.add_column("recommendation_states", sa.Column("decision_note", sa.String(length=500)))
    op.add_column("recommendation_states", sa.Column("baseline_metric_key", sa.String(length=40)))
    op.add_column(
        "recommendation_states",
        sa.Column("baseline_metric_value", sa.Numeric(precision=18, scale=2)),
    )
    op.add_column("recommendation_states", sa.Column("baseline_metric_unit", sa.String(length=24)))
    op.add_column("recommendation_states", sa.Column("decided_at", sa.DateTime(timezone=True)))

    op.create_table(
        "recommendation_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("actual_impact_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("actual_impact_unit", sa.String(length=24), nullable=True),
        sa.Column("baseline_metric_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("observed_metric_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("automatic_impact_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("metric_key", sa.String(length=40), nullable=True),
        sa.Column("metric_unit", sa.String(length=24), nullable=True),
        sa.Column("outcome_ruleset_version", sa.String(length=40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["recommendation_states.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id", name="uq_recommendation_outcome_decision"),
    )
    op.create_index("ix_recommendation_outcomes_user_id", "recommendation_outcomes", ["user_id"])
    op.create_index(
        "ix_recommendation_outcomes_user_observed",
        "recommendation_outcomes",
        ["user_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_recommendation_outcomes_user_observed", table_name="recommendation_outcomes")
    op.drop_index("ix_recommendation_outcomes_user_id", table_name="recommendation_outcomes")
    op.drop_table("recommendation_outcomes")
    op.drop_column("recommendation_states", "decided_at")
    op.drop_column("recommendation_states", "decision_note")
    op.drop_column("recommendation_states", "baseline_metric_unit")
    op.drop_column("recommendation_states", "baseline_metric_value")
    op.drop_column("recommendation_states", "baseline_metric_key")
    op.drop_column("recommendation_states", "decision_as_of")
    op.drop_column("recommendation_states", "guidance_ruleset_version")
    op.drop_column("recommendation_states", "reason_codes_json")
    op.drop_column("recommendation_states", "evidence_json")
    op.drop_column("recommendation_states", "expected_impact")
    op.drop_column("recommendation_states", "target")
    op.drop_column("recommendation_states", "title")
    op.drop_column("recommendation_states", "recommendation_type")
