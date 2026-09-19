"""Persist explicit review decisions for unknown deposit statement rows."""

import sqlalchemy as sa
from alembic import op

revision = "055_deposit_line_review"
down_revision = "054_statement_analysis_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deposit_statement_line_review_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("deposit_statement_line_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("previous_outcome", sa.String(length=24), nullable=False),
        sa.Column("new_outcome", sa.String(length=24), nullable=False),
        sa.Column("payment_rail", sa.String(length=20), nullable=True),
        sa.Column("created_transaction_id", sa.String(length=36), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(
            ["deposit_statement_line_id"], ["deposit_statement_lines.id"]
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deposit_statement_line_review_decisions_user_id",
        "deposit_statement_line_review_decisions",
        ["user_id"],
    )
    op.create_index(
        "ix_deposit_line_review_decisions_line_id",
        "deposit_statement_line_review_decisions",
        ["deposit_statement_line_id"],
    )
    op.create_index(
        "ix_deposit_statement_review_decisions_user_created",
        "deposit_statement_line_review_decisions",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deposit_statement_review_decisions_user_created",
        table_name="deposit_statement_line_review_decisions",
    )
    op.drop_index(
        "ix_deposit_line_review_decisions_line_id",
        table_name="deposit_statement_line_review_decisions",
    )
    op.drop_index(
        "ix_deposit_statement_line_review_decisions_user_id",
        table_name="deposit_statement_line_review_decisions",
    )
    op.drop_table("deposit_statement_line_review_decisions")
