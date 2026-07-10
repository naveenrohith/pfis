"""006_payment_methods

Revision ID: 006_payment_methods
Revises: 005_pipeline_observability
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "006_payment_methods"
down_revision = "005_pipeline_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "transactions" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("transactions")}
    if "payment_method" not in columns:
        op.add_column(
            "transactions",
            sa.Column("payment_method", sa.String(length=20), nullable=False, server_default="other"),
        )

    # Backfill retained email-based transactions so existing data immediately
    # contributes to the UPI, debit-card, and credit-card visuals.
    op.execute(
        """
        UPDATE transactions
        SET payment_method = COALESCE(
            (
                SELECT CASE
                    WHEN upper(COALESCE(raw_emails.subject, '') || ' ' || COALESCE(raw_emails.body, '')) LIKE '%UPI%'
                         OR upper(COALESCE(raw_emails.subject, '') || ' ' || COALESCE(raw_emails.body, '')) LIKE '%VPA%'
                        THEN 'upi'
                    WHEN upper(COALESCE(raw_emails.subject, '') || ' ' || COALESCE(raw_emails.body, '')) LIKE '%CREDIT CARD%'
                        THEN 'credit_card'
                    WHEN upper(COALESCE(raw_emails.subject, '') || ' ' || COALESCE(raw_emails.body, '')) LIKE '%DEBIT CARD%'
                        THEN 'debit_card'
                    ELSE 'other'
                END
                FROM raw_emails
                WHERE raw_emails.id = transactions.source_email_id
            ),
            'other'
        )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "transactions" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("transactions")}
        if "payment_method" in columns:
            op.drop_column("transactions", "payment_method")
