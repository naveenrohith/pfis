"""Persist bounded statement analysis artifacts for explicit review."""

import sqlalchemy as sa
from alembic import op

revision = "054_statement_analysis_reviews"
down_revision = "053_deposit_statement_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_analysis_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("document_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("institution", sa.String(length=40), nullable=True),
        sa.Column("product_type", sa.String(length=24), nullable=False),
        sa.Column("format_id", sa.String(length=80), nullable=True),
        sa.Column("support_status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("detector_version", sa.String(length=32), nullable=False),
        sa.Column("activity_types", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("analysis_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "document_fingerprint",
            name="uq_statement_analysis_review_user_fingerprint",
        ),
    )
    op.create_index(
        "ix_statement_analysis_reviews_user_id",
        "statement_analysis_reviews",
        ["user_id"],
    )
    op.create_index(
        "ix_statement_analysis_reviews_user_status_created",
        "statement_analysis_reviews",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_statement_analysis_reviews_user_status_created",
        table_name="statement_analysis_reviews",
    )
    op.drop_index(
        "ix_statement_analysis_reviews_user_id",
        table_name="statement_analysis_reviews",
    )
    op.drop_table("statement_analysis_reviews")
