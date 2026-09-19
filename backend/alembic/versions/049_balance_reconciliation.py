"""Persist immutable drift evidence between verified balances."""

import sqlalchemy as sa
from alembic import op

revision = "049_balance_reconciliation"
down_revision = "048_account_balance_forecast"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_balance_reconciliations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("financial_account_id", sa.String(length=36), nullable=False),
        sa.Column("opening_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("closing_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("balance_kind", sa.String(length=16), nullable=False),
        sa.Column("opening_as_of", sa.Date(), nullable=False),
        sa.Column("closing_as_of", sa.Date(), nullable=False),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("known_movement", sa.Numeric(18, 2), nullable=False),
        sa.Column("expected_closing_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("observed_closing_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("residual", sa.Numeric(18, 2), nullable=False),
        sa.Column("absolute_residual", sa.Numeric(18, 2), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "eligible_transaction_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "excluded_transaction_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "eligible_transaction_ids_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "excluded_transaction_ids_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("reason_codes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("reconciliation_status", sa.String(length=20), nullable=False),
        sa.Column("ruleset_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["financial_account_id"], ["financial_accounts.id"]),
        sa.ForeignKeyConstraint(
            ["opening_snapshot_id"],
            ["account_balance_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["closing_snapshot_id"],
            ["account_balance_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "opening_snapshot_id",
            "closing_snapshot_id",
            name="uq_account_balance_reconciliation_interval",
        ),
    )
    op.create_index(
        "ix_account_balance_reconciliations_user_id",
        "account_balance_reconciliations",
        ["user_id"],
    )
    op.create_index(
        "ix_account_balance_reconciliations_financial_account_id",
        "account_balance_reconciliations",
        ["financial_account_id"],
    )
    op.create_index(
        "ix_account_balance_reconciliations_user_account_closing",
        "account_balance_reconciliations",
        ["user_id", "financial_account_id", "closing_as_of"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_balance_reconciliations_user_account_closing",
        table_name="account_balance_reconciliations",
    )
    op.drop_index(
        "ix_account_balance_reconciliations_financial_account_id",
        table_name="account_balance_reconciliations",
    )
    op.drop_index(
        "ix_account_balance_reconciliations_user_id",
        table_name="account_balance_reconciliations",
    )
    op.drop_table("account_balance_reconciliations")
