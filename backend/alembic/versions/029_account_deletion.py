"""Add account tombstones and inactive household membership.

Revision ID: 029_account_deletion
Revises: 028_raw_email_retention
"""

import sqlalchemy as sa
from alembic import op

revision = "029_account_deletion"
down_revision = "028_raw_email_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])
    op.add_column(
        "users",
        sa.Column("deletion_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_deletion_started_at",
        "users",
        ["deletion_started_at"],
    )
    op.add_column(
        "household_members",
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_household_members_active",
        "household_members",
        ["household_id", "left_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_household_members_active", table_name="household_members")
    op.drop_column("household_members", "left_at")
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_index("ix_users_deletion_started_at", table_name="users")
    op.drop_column("users", "deletion_started_at")
    op.drop_column("users", "deleted_at")
