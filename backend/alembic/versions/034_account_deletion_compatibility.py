"""Repair legacy account-deletion schemas stamped before the final 029 shape.

Revision ID: 034_account_deletion_compat
Revises: 033_recommendation_decisions
"""

import sqlalchemy as sa
from alembic import op

revision = "034_account_deletion_compat"
down_revision = "033_recommendation_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Converge older stamped databases without changing fresh installations."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "deletion_started_at" not in user_columns:
        op.add_column(
            "users",
            sa.Column("deletion_started_at", sa.DateTime(timezone=True), nullable=True),
        )

    user_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("users")}
    if "ix_users_deletion_started_at" not in user_indexes:
        op.create_index(
            "ix_users_deletion_started_at",
            "users",
            ["deletion_started_at"],
        )


def downgrade() -> None:
    """Keep the column because revision 029 owns it on fresh databases."""
