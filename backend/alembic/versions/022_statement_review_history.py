"""append-only statement review decisions

Revision ID: 022_statement_review_history
Revises: 021_roadmap_extensions
"""

import sqlalchemy as sa
from alembic import op

revision = "022_statement_review_history"
down_revision = "021_roadmap_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_line_review_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "statement_line_id",
            sa.String(36),
            sa.ForeignKey("statement_lines.id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("previous_outcome", sa.String(24), nullable=False),
        sa.Column("new_outcome", sa.String(24), nullable=False),
        sa.Column(
            "matched_transaction_id",
            sa.String(36),
            sa.ForeignKey("transactions.id"),
        ),
        sa.Column(
            "paying_account_id",
            sa.String(36),
            sa.ForeignKey("financial_accounts.id"),
        ),
        sa.Column("note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_statement_line_review_decisions_user_id",
        "statement_line_review_decisions",
        ["user_id"],
    )
    op.create_index(
        "ix_statement_line_review_decisions_statement_line_id",
        "statement_line_review_decisions",
        ["statement_line_id"],
    )
    op.create_index(
        "ix_statement_review_decisions_user_created",
        "statement_line_review_decisions",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("statement_line_review_decisions")
