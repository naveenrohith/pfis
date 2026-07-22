"""002_gmail_auto_sync

Revision ID: 002_gmail_auto_sync
Revises: 001_baseline
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = "002_gmail_auto_sync"
down_revision = "001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gmail_accounts", sa.Column("last_history_id", sa.String(64), nullable=True))
    op.add_column(
        "gmail_accounts",
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "gmail_accounts",
        sa.Column("auto_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "gmail_accounts",
        sa.Column("auto_sync_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
    )
    op.add_column(
        "gmail_accounts",
        sa.Column("auto_sync_status", sa.String(20), nullable=False, server_default="idle"),
    )
    op.add_column("gmail_accounts", sa.Column("auto_sync_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("gmail_accounts", "auto_sync_error")
    op.drop_column("gmail_accounts", "auto_sync_status")
    op.drop_column("gmail_accounts", "auto_sync_interval_seconds")
    op.drop_column("gmail_accounts", "auto_sync_enabled")
    op.drop_column("gmail_accounts", "last_sync_started_at")
    op.drop_column("gmail_accounts", "last_history_id")
