"""004_goals

Revision ID: 004_goals
Revises: 003_connector_audit_events
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "004_goals"
down_revision = "003_connector_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "goals" not in inspector.get_table_names():
        op.create_table(
            "goals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("goal_type", sa.String(40), nullable=False),
            sa.Column("label", sa.String(160), nullable=False),
            sa.Column("target_amount", sa.Float(), nullable=False),
            sa.Column("target_key", sa.String(160), nullable=True),
            sa.Column("target_month", sa.Integer(), nullable=True),
            sa.Column("target_year", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )

    existing_indexes = {index["name"] for index in inspect(bind).get_indexes("goals")}
    _create_index_if_missing(existing_indexes, "ix_goals_user_id", ["user_id"])
    _create_index_if_missing(existing_indexes, "ix_goals_goal_type", ["goal_type"])
    _create_index_if_missing(existing_indexes, "ix_goals_is_active", ["is_active"])
    _create_index_if_missing(existing_indexes, "ix_goals_created_at", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "goals" not in inspector.get_table_names():
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes("goals")}
    for index_name in (
        "ix_goals_created_at",
        "ix_goals_is_active",
        "ix_goals_goal_type",
        "ix_goals_user_id",
    ):
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="goals")
    op.drop_table("goals")


def _create_index_if_missing(existing_indexes: set[str], index_name: str, columns: list[str]) -> None:
    if index_name in existing_indexes:
        return
    op.create_index(index_name, "goals", columns)
    existing_indexes.add(index_name)
