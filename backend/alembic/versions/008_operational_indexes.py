"""008_operational_indexes

Revision ID: 008_operational_indexes
Revises: 007_transaction_context
Create Date: 2026-07-10
"""

from alembic import op
from sqlalchemy import inspect


revision = "008_operational_indexes"
down_revision = "007_transaction_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    _create_index_if_missing(
        inspector, "ix_raw_emails_user_received", "raw_emails", ["user_id", "received_at"]
    )
    _create_index_if_missing(
        inspector, "ix_sync_runs_user_started", "sync_runs", ["user_id", "start_time"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table_name, index_name in (
        ("sync_runs", "ix_sync_runs_user_started"),
        ("raw_emails", "ix_raw_emails_user_received"),
    ):
        if table_name in inspector.get_table_names():
            indexes = {index["name"] for index in inspector.get_indexes(table_name)}
            if index_name in indexes:
                op.drop_index(index_name, table_name=table_name)


def _create_index_if_missing(
    inspector, index_name: str, table_name: str, columns: list[str]
) -> None:
    if table_name not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns)
