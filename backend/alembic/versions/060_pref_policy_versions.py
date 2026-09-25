"""Add versioned user preference policies."""

import sqlalchemy as sa
from alembic import op

revision = "060_pref_policy_versions"
down_revision = "059_subscription_review_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preference_policy_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("based_on_version", sa.Integer(), nullable=True),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "version", name="uq_user_preference_policy_version"),
    )
    op.create_index(
        "ix_user_preference_policy_versions_user_id",
        "user_preference_policy_versions",
        ["user_id"],
    )
    op.create_index(
        "ix_user_preference_policy_versions_user_created",
        "user_preference_policy_versions",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_preference_policy_versions_user_created",
        table_name="user_preference_policy_versions",
    )
    op.drop_index(
        "ix_user_preference_policy_versions_user_id",
        table_name="user_preference_policy_versions",
    )
    op.drop_table("user_preference_policy_versions")
