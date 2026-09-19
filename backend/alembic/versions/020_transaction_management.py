"""transaction notes, tags, and split allocations

Revision ID: 020_transaction_management
Revises: 019_card_cash_extensions
"""

import sqlalchemy as sa
from alembic import op

revision = "020_transaction_management"
down_revision = "019_card_cash_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("note", sa.Text(), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "transaction_splits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "transaction_id",
            sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id")),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_transaction_splits_amount_positive"),
    )
    op.create_index(
        "ix_transaction_splits_user_transaction",
        "transaction_splits",
        ["user_id", "transaction_id"],
    )
    op.create_index("ix_transaction_splits_user_id", "transaction_splits", ["user_id"])
    op.create_index(
        "ix_transaction_splits_transaction_id",
        "transaction_splits",
        ["transaction_id"],
    )


def downgrade() -> None:
    op.drop_table("transaction_splits")
    op.drop_column("transactions", "tags_json")
    op.drop_column("transactions", "note")
