"""Persist typed issuer facts for live credit-card positions."""

import sqlalchemy as sa
from alembic import op

revision = "051_card_position_observations"
down_revision = "050_balance_provider_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_position_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("financial_account_id", sa.String(length=36), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("current_outstanding", sa.Numeric(18, 2), nullable=False),
        sa.Column("billed_due", sa.Numeric(18, 2), nullable=True),
        sa.Column("pending_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("credit_limit", sa.Numeric(18, 2), nullable=True),
        sa.Column("available_credit", sa.Numeric(18, 2), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="connector"),
        sa.Column("source_record_id", sa.String(length=128), nullable=False),
        sa.Column("source_account_id", sa.String(length=128), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_cadence_minutes", sa.Integer(), nullable=True),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_outstanding >= 0",
            name="ck_card_position_current_outstanding_nonnegative",
        ),
        sa.CheckConstraint(
            "billed_due IS NULL OR billed_due >= 0",
            name="ck_card_position_billed_due_nonnegative",
        ),
        sa.CheckConstraint(
            "pending_amount IS NULL OR pending_amount >= 0",
            name="ck_card_position_pending_nonnegative",
        ),
        sa.CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0",
            name="ck_card_position_credit_limit_nonnegative",
        ),
        sa.CheckConstraint(
            "available_credit IS NULL OR available_credit >= 0",
            name="ck_card_position_available_credit_nonnegative",
        ),
        sa.CheckConstraint(
            "expected_cadence_minutes IS NULL OR expected_cadence_minutes > 0",
            name="ck_card_position_cadence_positive",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["financial_account_id"], ["financial_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "financial_account_id",
            "source",
            "source_record_id",
            name="uq_card_position_observations_source_record",
        ),
    )
    op.create_index(
        "ix_card_position_observations_user_id",
        "card_position_observations",
        ["user_id"],
    )
    op.create_index(
        "ix_card_position_observations_financial_account_id",
        "card_position_observations",
        ["financial_account_id"],
    )
    op.create_index(
        "ix_card_position_observations_user_account_as_of",
        "card_position_observations",
        ["user_id", "financial_account_id", "as_of"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_card_position_observations_user_account_as_of",
        table_name="card_position_observations",
    )
    op.drop_index(
        "ix_card_position_observations_financial_account_id",
        table_name="card_position_observations",
    )
    op.drop_index("ix_card_position_observations_user_id", table_name="card_position_observations")
    op.drop_table("card_position_observations")
