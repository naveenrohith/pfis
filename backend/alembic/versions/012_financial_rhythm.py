"""012_financial_rhythm

Revision ID: 012_financial_rhythm
Revises: 011_premium_workspace
Create Date: 2026-07-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "012_financial_rhythm"
down_revision = "011_premium_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "dashboard_preferences" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("dashboard_preferences")}
    if "briefing_cadence" not in columns:
        with op.batch_alter_table("dashboard_preferences") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "briefing_cadence",
                    sa.String(16),
                    nullable=False,
                    server_default="daily",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "dashboard_preferences" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("dashboard_preferences")}
    if "briefing_cadence" in columns:
        with op.batch_alter_table("dashboard_preferences") as batch_op:
            batch_op.drop_column("briefing_cadence")
