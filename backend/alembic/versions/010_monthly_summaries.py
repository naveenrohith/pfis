"""010_monthly_summaries

Revision ID: 010_monthly_summaries
Revises: 009_financial_accounts
Create Date: 2026-07-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "010_monthly_summaries"
down_revision = "009_financial_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "monthly_summaries" not in inspector.get_table_names():
        op.create_table(
            "monthly_summaries",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "month", "year", name="uq_monthly_summaries_user_period"),
        )

    indexes = {index["name"] for index in inspect(bind).get_indexes("monthly_summaries")}
    for index_name, columns in (
        ("ix_monthly_summaries_user_id", ["user_id"]),
        ("ix_monthly_summaries_user_period", ["user_id", "year", "month"]),
    ):
        if index_name not in indexes:
            op.create_index(index_name, "monthly_summaries", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "monthly_summaries" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("monthly_summaries")}
    for index_name in ("ix_monthly_summaries_user_period", "ix_monthly_summaries_user_id"):
        if index_name in indexes:
            op.drop_index(index_name, table_name="monthly_summaries")
    op.drop_table("monthly_summaries")
