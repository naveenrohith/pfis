"""Persist reconciled deposit-account statements and source lines."""

import sqlalchemy as sa
from alembic import op

revision = "053_deposit_statement_ledger"
down_revision = "052_provider_account_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deposit_account_statements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("statement_import_id", sa.String(length=36), nullable=False),
        sa.Column("financial_account_id", sa.String(length=36), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("closing_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "opening_balance >= 0", name="ck_deposit_statement_opening_nonnegative"
        ),
        sa.CheckConstraint(
            "closing_balance >= 0", name="ck_deposit_statement_closing_nonnegative"
        ),
        sa.ForeignKeyConstraint(["financial_account_id"], ["financial_accounts.id"]),
        sa.ForeignKeyConstraint(["statement_import_id"], ["statement_imports.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "financial_account_id",
            "period_start",
            "period_end",
            name="uq_deposit_statement_account_period",
        ),
        sa.UniqueConstraint("statement_import_id", name="uq_deposit_statement_import"),
    )
    op.create_index(
        "ix_deposit_account_statements_user_id",
        "deposit_account_statements",
        ["user_id"],
    )
    op.create_index(
        "ix_deposit_account_statements_financial_account_id",
        "deposit_account_statements",
        ["financial_account_id"],
    )
    op.create_index(
        "ix_deposit_statements_user_period",
        "deposit_account_statements",
        ["user_id", "period_end"],
    )

    op.create_table(
        "deposit_statement_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("deposit_account_statement_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("reference_id", sa.String(length=100), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("transaction_type", sa.String(length=12), nullable=False),
        sa.Column("payment_rail", sa.String(length=20), nullable=False),
        sa.Column("balance_after", sa.Numeric(18, 2), nullable=False),
        sa.Column("review_outcome", sa.String(length=24), nullable=False),
        sa.Column("created_transaction_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_deposit_statement_line_amount_positive"),
        sa.CheckConstraint(
            "balance_after >= 0", name="ck_deposit_statement_line_balance_nonnegative"
        ),
        sa.CheckConstraint(
            "transaction_type IN ('debit', 'credit')",
            name="ck_deposit_statement_line_type",
        ),
        sa.ForeignKeyConstraint(
            ["created_transaction_id"],
            ["transactions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["deposit_account_statement_id"],
            ["deposit_account_statements.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deposit_account_statement_id",
            "line_number",
            name="uq_deposit_statement_line_number",
        ),
    )
    op.create_index(
        "ix_deposit_statement_lines_user_id",
        "deposit_statement_lines",
        ["user_id"],
    )
    op.create_index(
        "ix_deposit_statement_lines_deposit_account_statement_id",
        "deposit_statement_lines",
        ["deposit_account_statement_id"],
    )
    op.create_index(
        "ix_deposit_statement_lines_user_review",
        "deposit_statement_lines",
        ["user_id", "review_outcome"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deposit_statement_lines_user_review",
        table_name="deposit_statement_lines",
    )
    op.drop_index(
        "ix_deposit_statement_lines_deposit_account_statement_id",
        table_name="deposit_statement_lines",
    )
    op.drop_index(
        "ix_deposit_statement_lines_user_id",
        table_name="deposit_statement_lines",
    )
    op.drop_table("deposit_statement_lines")
    op.drop_index(
        "ix_deposit_statements_user_period",
        table_name="deposit_account_statements",
    )
    op.drop_index(
        "ix_deposit_account_statements_financial_account_id",
        table_name="deposit_account_statements",
    )
    op.drop_index(
        "ix_deposit_account_statements_user_id",
        table_name="deposit_account_statements",
    )
    op.drop_table("deposit_account_statements")
