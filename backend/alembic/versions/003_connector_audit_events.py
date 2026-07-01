"""003_connector_audit_events

Revision ID: 003_connector_audit_events
Revises: 002_gmail_auto_sync
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "003_connector_audit_events"
down_revision = "002_gmail_auto_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "connector_audit_events" not in inspector.get_table_names():
        op.create_table(
            "connector_audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("connector_type", sa.String(50), nullable=False),
            sa.Column("connector_account_id", sa.String(36), nullable=True),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("payload_json", sa.Text(), server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )

    existing_indexes = {index["name"] for index in inspect(bind).get_indexes("connector_audit_events")}
    _create_index_if_missing(
        existing_indexes,
        "ix_connector_audit_events_user_id",
        ["user_id"],
    )
    _create_index_if_missing(
        existing_indexes,
        "ix_connector_audit_events_connector_type",
        ["connector_type"],
    )
    _create_index_if_missing(
        existing_indexes,
        "ix_connector_audit_events_connector_account_id",
        ["connector_account_id"],
    )
    _create_index_if_missing(
        existing_indexes,
        "ix_connector_audit_events_event_type",
        ["event_type"],
    )
    _create_index_if_missing(
        existing_indexes,
        "ix_connector_audit_events_created_at",
        ["created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "connector_audit_events" not in inspector.get_table_names():
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes("connector_audit_events")}
    for index_name in (
        "ix_connector_audit_events_created_at",
        "ix_connector_audit_events_event_type",
        "ix_connector_audit_events_connector_account_id",
        "ix_connector_audit_events_connector_type",
        "ix_connector_audit_events_user_id",
    ):
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="connector_audit_events")
    op.drop_table("connector_audit_events")


def _create_index_if_missing(existing_indexes: set[str], index_name: str, columns: list[str]) -> None:
    if index_name in existing_indexes:
        return
    op.create_index(index_name, "connector_audit_events", columns)
    existing_indexes.add(index_name)
