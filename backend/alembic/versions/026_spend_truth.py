"""Separate issuer accounting entries from real financial activity.

Revision ID: 026_spend_truth
Revises: 025_liability_evidence
"""

from alembic import op
import sqlalchemy as sa


revision = "026_spend_truth"
down_revision = "025_liability_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "is_accounting_adjustment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "transactions",
        sa.Column("ledger_subtype", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_transactions_user_financial_activity",
        "transactions",
        ["user_id", "is_transfer", "is_accounting_adjustment", "transaction_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transactions_user_financial_activity",
        table_name="transactions",
    )
    op.drop_column("transactions", "ledger_subtype")
    op.drop_column("transactions", "is_accounting_adjustment")
