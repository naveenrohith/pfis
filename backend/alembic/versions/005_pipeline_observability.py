"""005_pipeline_observability

Revision ID: 005_pipeline_observability
Revises: 004_goals
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "005_pipeline_observability"
down_revision = "004_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "parse_failures" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("parse_failures")}
        _add_column_if_missing(columns, "failure_stage", sa.Column("failure_stage", sa.String(60), nullable=True))
        _add_column_if_missing(columns, "failure_code", sa.Column("failure_code", sa.String(80), nullable=True))
        _add_column_if_missing(columns, "parser_name", sa.Column("parser_name", sa.String(100), nullable=True))
        _add_column_if_missing(columns, "pattern_version", sa.Column("pattern_version", sa.Integer(), nullable=True))
        _add_column_if_missing(columns, "confidence_version", sa.Column("confidence_version", sa.Integer(), nullable=True))
        _add_column_if_missing(columns, "normalization_version", sa.Column("normalization_version", sa.Integer(), nullable=True))
        _add_column_if_missing(columns, "diagnostic_json", sa.Column("diagnostic_json", sa.Text(), nullable=True))

        existing_indexes = {index["name"] for index in inspector.get_indexes("parse_failures")}
        _create_index_if_missing(existing_indexes, "ix_parse_failures_failure_stage", "parse_failures", ["failure_stage"])
        _create_index_if_missing(existing_indexes, "ix_parse_failures_failure_code", "parse_failures", ["failure_code"])

    if "pipeline_events" not in inspector.get_table_names():
        op.create_table(
            "pipeline_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("email_id", sa.String(36), sa.ForeignKey("raw_emails.id"), nullable=True),
            sa.Column("transaction_id", sa.String(36), sa.ForeignKey("transactions.id"), nullable=True),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("stage", sa.String(60), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("parser_name", sa.String(100), nullable=True),
            sa.Column("parser_version", sa.Integer(), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("duration_ms", sa.Float(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        existing_indexes = set()
    else:
        existing_indexes = {index["name"] for index in inspector.get_indexes("pipeline_events")}

    for index_name, columns in (
        ("ix_pipeline_events_user_id", ["user_id"]),
        ("ix_pipeline_events_email_id", ["email_id"]),
        ("ix_pipeline_events_transaction_id", ["transaction_id"]),
        ("ix_pipeline_events_event_type", ["event_type"]),
        ("ix_pipeline_events_stage", ["stage"]),
        ("ix_pipeline_events_status", ["status"]),
        ("ix_pipeline_events_created_at", ["created_at"]),
    ):
        _create_index_if_missing(existing_indexes, index_name, "pipeline_events", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "pipeline_events" in inspector.get_table_names():
        existing_indexes = {index["name"] for index in inspector.get_indexes("pipeline_events")}
        for index_name in (
            "ix_pipeline_events_created_at",
            "ix_pipeline_events_status",
            "ix_pipeline_events_stage",
            "ix_pipeline_events_event_type",
            "ix_pipeline_events_transaction_id",
            "ix_pipeline_events_email_id",
            "ix_pipeline_events_user_id",
        ):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="pipeline_events")
        op.drop_table("pipeline_events")


def _add_column_if_missing(existing_columns: set[str], column_name: str, column: sa.Column) -> None:
    if column_name in existing_columns:
        return
    op.add_column("parse_failures", column)
    existing_columns.add(column_name)


def _create_index_if_missing(
    existing_indexes: set[str], index_name: str, table_name: str, columns: list[str]
) -> None:
    if index_name in existing_indexes:
        return
    op.create_index(index_name, table_name, columns)
    existing_indexes.add(index_name)
