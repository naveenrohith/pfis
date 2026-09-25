"""Persist subscription review actions."""

import sqlalchemy as sa
from alembic import op

revision = "059_subscription_review_actions"
down_revision = "058_card_calendar_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_review_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("stream_key", sa.String(length=64), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=False),
        sa.Column("financial_account_id", sa.String(length=36), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "stream_key", name="uq_subscription_review_user_stream"),
    )
    op.create_index(
        "ix_subscription_review_actions_user_id",
        "subscription_review_actions",
        ["user_id"],
    )
    op.create_index(
        "ix_subscription_review_actions_user_action",
        "subscription_review_actions",
        ["user_id", "action"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscription_review_actions_user_action",
        table_name="subscription_review_actions",
    )
    op.drop_index(
        "ix_subscription_review_actions_user_id", table_name="subscription_review_actions"
    )
    op.drop_table("subscription_review_actions")
