"""financial position foundation

Revision ID: 018_financial_position
Revises: 017_gmail_token_expiry
"""

from alembic import op
import sqlalchemy as sa


revision = "018_financial_position"
down_revision = "017_gmail_token_expiry"
branch_labels = None
depends_on = None


def _assert_credit_account_normalization_safe(bind) -> None:
    collision = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM financial_accounts
            WHERE LOWER(account_type) IN ('credit', 'credit card', 'credit_card')
            GROUP BY user_id, institution_name, masked_number
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if collision is not None:
        raise RuntimeError(
            "Cannot normalize legacy credit-card accounts because account identities collide"
        )


def upgrade() -> None:
    _assert_credit_account_normalization_safe(op.get_bind())
    op.execute(
        "UPDATE financial_accounts SET account_type = 'credit_card' "
        "WHERE LOWER(account_type) IN ('credit', 'credit card')"
    )
    op.execute(
        "UPDATE financial_accounts SET balance_kind = 'liability' "
        "WHERE account_type = 'credit_card'"
    )
    op.add_column("transactions", sa.Column("payment_rail", sa.String(length=20), nullable=False, server_default="other"))
    op.add_column("transactions", sa.Column("card_event", sa.String(length=20), nullable=False, server_default="none"))
    op.add_column("transactions", sa.Column("source_kind", sa.String(length=24), nullable=False, server_default="manual"))
    op.add_column("transactions", sa.Column("source_identifier", sa.String(length=128), nullable=True))
    op.add_column("transactions", sa.Column("review_outcome", sa.String(length=24), nullable=False, server_default="newly_imported"))
    op.create_index("ix_transactions_review_outcome", "transactions", ["review_outcome"])
    op.add_column("account_balance_snapshots", sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("account_balance_snapshots", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE account_balance_snapshots SET observed_at = created_at WHERE observed_at IS NULL")
    op.alter_column("account_balance_snapshots", "observed_at", nullable=False)

    op.create_table(
        "statement_imports",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id"), nullable=False), sa.Column("issuer", sa.String(40), nullable=False),
        sa.Column("document_fingerprint", sa.String(64), nullable=False), sa.Column("extractor_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("rejection_reason", sa.String(240)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "document_fingerprint", name="uq_statement_import_user_fingerprint"),
    )
    op.create_index("ix_statement_imports_user_created", "statement_imports", ["user_id", "created_at"])
    op.create_table(
        "credit_card_statements",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("statement_import_id", sa.String(36), sa.ForeignKey("statement_imports.id"), nullable=False, unique=True), sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=False), sa.Column("period_start", sa.Date(), nullable=False), sa.Column("period_end", sa.Date(), nullable=False), sa.Column("due_date", sa.Date()),
        *[sa.Column(name, sa.Numeric(18, 2)) for name in ("total_due", "minimum_due", "credit_limit", "available_credit_limit", "available_cash_limit", "previous_due", "payments_credits", "purchases_debits", "finance_charges")],
        sa.Column("currency", sa.String(3), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("financial_account_id", "statement_date", name="uq_card_statement_account_date"),
    )
    op.create_index("ix_card_statements_user_date", "credit_card_statements", ["user_id", "statement_date"])
    op.create_table(
        "statement_lines",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("credit_card_statement_id", sa.String(36), sa.ForeignKey("credit_card_statements.id"), nullable=False), sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False), sa.Column("description", sa.String(500), nullable=False), sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reference_id", sa.String(100)), sa.Column("transaction_type", sa.String(12), nullable=False), sa.Column("card_event", sa.String(20), nullable=False),
        sa.Column("review_outcome", sa.String(24), nullable=False), sa.Column("created_transaction_id", sa.String(36), sa.ForeignKey("transactions.id")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("credit_card_statement_id", "line_number", name="uq_statement_line_number"),
    )
    op.create_index("ix_statement_lines_user_review", "statement_lines", ["user_id", "review_outcome"])
    op.create_table("statement_line_matches", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("statement_line_id", sa.String(36), sa.ForeignKey("statement_lines.id"), nullable=False), sa.Column("transaction_id", sa.String(36), sa.ForeignKey("transactions.id"), nullable=False), sa.Column("match_method", sa.String(32), nullable=False), sa.Column("confidence", sa.Numeric(4, 3), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("statement_line_id", name="uq_statement_line_match_line"), sa.UniqueConstraint("transaction_id", name="uq_statement_line_match_transaction"))
    op.create_table("liabilities", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id")), sa.Column("label", sa.String(160), nullable=False), sa.Column("liability_type", sa.String(32), nullable=False), sa.Column("source_kind", sa.String(24), nullable=False), sa.Column("source_confidence", sa.Numeric(4, 3)), sa.Column("outstanding_principal", sa.Numeric(18, 2)), sa.Column("monthly_due", sa.Numeric(18, 2)), sa.Column("next_due_date", sa.Date()), sa.Column("end_date", sa.Date()), sa.Column("interest_rate", sa.Numeric(7, 4)), sa.Column("tenure_months", sa.Integer()), sa.Column("remaining_installments", sa.Integer()), sa.Column("complete_schedule", sa.Boolean(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_liabilities_user_active", "liabilities", ["user_id", "is_active"])
    op.create_table("commitments", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id")), sa.Column("liability_id", sa.String(36), sa.ForeignKey("liabilities.id")), sa.Column("label", sa.String(160), nullable=False), sa.Column("commitment_type", sa.String(32), nullable=False), sa.Column("amount", sa.Numeric(18, 2), nullable=False), sa.Column("due_date", sa.Date(), nullable=False), sa.Column("cadence", sa.String(20)), sa.Column("source_kind", sa.String(24), nullable=False), sa.Column("source_identifier", sa.String(128)), sa.Column("confirmed", sa.Boolean(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_commitments_user_due", "commitments", ["user_id", "due_date", "is_active"])
    op.create_table("cash_plans", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("primary_financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id"), nullable=False), sa.Column("next_income_date", sa.Date()), sa.Column("next_income_amount", sa.Numeric(18, 2)), sa.Column("show_daily_allowance", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("user_id", name="uq_cash_plan_user"))
    op.create_table("reserve_plans", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id"), nullable=False), sa.Column("label", sa.String(160), nullable=False), sa.Column("target_amount", sa.Numeric(18, 2), nullable=False), sa.Column("due_date", sa.Date(), nullable=False), sa.Column("monthly_allocation", sa.Numeric(18, 2), nullable=False), sa.Column("approved", sa.Boolean(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_reserve_plans_user_due", "reserve_plans", ["user_id", "due_date", "approved"])
    op.create_table("liability_schedule_items", sa.Column("id", sa.String(36), primary_key=True), sa.Column("liability_id", sa.String(36), sa.ForeignKey("liabilities.id"), nullable=False), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("due_date", sa.Date(), nullable=False), sa.Column("installment_amount", sa.Numeric(18, 2), nullable=False), sa.Column("principal_amount", sa.Numeric(18, 2)), sa.Column("interest_amount", sa.Numeric(18, 2)), sa.Column("status", sa.String(20), nullable=False), sa.UniqueConstraint("liability_id", "due_date", name="uq_liability_schedule_due"))


def downgrade() -> None:
    for table in ("liability_schedule_items", "reserve_plans", "cash_plans", "commitments", "liabilities", "statement_line_matches", "statement_lines", "credit_card_statements", "statement_imports"):
        op.drop_table(table)
    op.drop_index("ix_transactions_review_outcome", table_name="transactions")
    for column in ("review_outcome", "source_identifier", "source_kind", "card_event", "payment_rail"):
        op.drop_column("transactions", column)
    op.drop_column("account_balance_snapshots", "observed_at")
    op.drop_column("account_balance_snapshots", "verified")
