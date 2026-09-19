"""user-approved account link rules

Revision ID: 023_account_link_rules
Revises: 022_statement_review_history
"""

import sqlalchemy as sa
from alembic import op

revision = "023_account_link_rules"
down_revision = "022_statement_review_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_link_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "financial_account_id",
            sa.String(36),
            sa.ForeignKey("financial_accounts.id"),
            nullable=False,
        ),
        sa.Column("evidence_kind", sa.String(32), nullable=False),
        sa.Column("evidence_value", sa.String(128), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "evidence_kind",
            "evidence_value",
            "currency",
            name="uq_account_link_rules_user_evidence",
        ),
    )
    op.create_index(
        "ix_account_link_rules_user_id", "account_link_rules", ["user_id"]
    )
    op.create_index(
        "ix_account_link_rules_financial_account_id",
        "account_link_rules",
        ["financial_account_id"],
    )
    op.create_index(
        "ix_account_link_rules_user_active",
        "account_link_rules",
        ["user_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_table("account_link_rules")
