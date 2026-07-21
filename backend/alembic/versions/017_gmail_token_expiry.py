"""017_gmail_token_expiry

Revision ID: 017_gmail_token_expiry
Revises: 016_durable_jobs
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "017_gmail_token_expiry"
down_revision = "016_durable_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("gmail_accounts")}
    if "token_expires_at" not in columns:
        with op.batch_alter_table("gmail_accounts") as batch_op:
            batch_op.add_column(sa.Column("token_expires_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("gmail_accounts")}
    if "token_expires_at" in columns:
        with op.batch_alter_table("gmail_accounts") as batch_op:
            batch_op.drop_column("token_expires_at")
