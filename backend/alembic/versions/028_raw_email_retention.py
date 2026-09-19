"""Add owned raw-email retention and redaction state.

Revision ID: 028_raw_email_retention
Revises: 027_user_timezone
"""

import sqlalchemy as sa
from alembic import op

revision = "028_raw_email_retention"
down_revision = "027_user_timezone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "raw_email_retention_days",
                sa.Integer(),
                nullable=True,
                server_default="365",
            )
        )
        batch_op.create_check_constraint(
            "ck_users_raw_email_retention_days",
            "raw_email_retention_days IS NULL OR " "raw_email_retention_days IN (30, 90, 180, 365)",
        )

    op.add_column(
        "raw_emails",
        sa.Column("content_redacted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_raw_emails_retention",
        "raw_emails",
        [
            "user_id",
            "content_redacted_at",
            "processed_flag",
            "received_at",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_raw_emails_retention", table_name="raw_emails")
    op.drop_column("raw_emails", "content_redacted_at")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_raw_email_retention_days", type_="check")
        batch_op.drop_column("raw_email_retention_days")
