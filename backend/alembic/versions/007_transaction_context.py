"""007_transaction_context

Revision ID: 007_transaction_context
Revises: 006_payment_methods
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "007_transaction_context"
down_revision = "006_payment_methods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("transactions")}
    if "transaction_status" not in columns:
        op.add_column(
            "transactions",
            sa.Column("transaction_status", sa.String(length=24), nullable=False, server_default="completed"),
        )
    if "transaction_timestamp" not in columns:
        op.add_column("transactions", sa.Column("transaction_timestamp", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("transactions")}
    if "transaction_timestamp" in columns:
        op.drop_column("transactions", "transaction_timestamp")
    if "transaction_status" in columns:
        op.drop_column("transactions", "transaction_status")
