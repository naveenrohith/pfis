"""011_premium_workspace

Revision ID: 011_premium_workspace
Revises: 010_monthly_summaries
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "011_premium_workspace"
down_revision = "010_monthly_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    account_columns = {column["name"] for column in inspector.get_columns("financial_accounts")}
    if "balance_kind" not in account_columns:
        with op.batch_alter_table("financial_accounts") as batch_op:
            batch_op.add_column(
                sa.Column("balance_kind", sa.String(16), nullable=False, server_default="asset")
            )

    transaction_columns = {column["name"] for column in inspect(bind).get_columns("transactions")}
    with op.batch_alter_table("transactions") as batch_op:
        if "transfer_group_id" not in transaction_columns:
            batch_op.add_column(sa.Column("transfer_group_id", sa.String(36), nullable=True))
            batch_op.create_index("ix_transactions_transfer_group_id", ["transfer_group_id"])
        if "is_transfer" not in transaction_columns:
            batch_op.add_column(
                sa.Column("is_transfer", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )
            batch_op.create_index("ix_transactions_is_transfer", ["is_transfer"])

    if "account_balance_snapshots" not in tables:
        op.create_table(
            "account_balance_snapshots",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "financial_account_id",
                sa.String(36),
                sa.ForeignKey("financial_accounts.id"),
                nullable=False,
            ),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
            sa.Column("as_of", sa.Date(), nullable=False),
            sa.Column("source", sa.String(24), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "financial_account_id",
                "as_of",
                name="uq_account_balance_snapshots_account_as_of",
            ),
        )
        op.create_index("ix_account_balance_snapshots_user_id", "account_balance_snapshots", ["user_id"])
        op.create_index(
            "ix_account_balance_snapshots_financial_account_id",
            "account_balance_snapshots",
            ["financial_account_id"],
        )
        op.create_index(
            "ix_account_balance_snapshots_user_as_of",
            "account_balance_snapshots",
            ["user_id", "as_of"],
        )

    if "dashboard_preferences" not in tables:
        op.create_table(
            "dashboard_preferences",
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("layout_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("widgets_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("theme", sa.String(16), nullable=False, server_default="system"),
            sa.Column("density", sa.String(16), nullable=False, server_default="comfortable"),
            sa.Column("favorites_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("onboarding_goal", sa.String(40), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "recommendation_states" not in tables:
        op.create_table(
            "recommendation_states",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("recommendation_id", sa.String(80), nullable=False),
            sa.Column("state", sa.String(16), nullable=False),
            sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "user_id", "recommendation_id", name="uq_recommendation_state_user_rec"
            ),
        )
        op.create_index("ix_recommendation_states_user_id", "recommendation_states", ["user_id"])
        op.create_index(
            "ix_recommendation_states_user_state",
            "recommendation_states",
            ["user_id", "state"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if "recommendation_states" in tables:
        op.drop_table("recommendation_states")
    if "dashboard_preferences" in tables:
        op.drop_table("dashboard_preferences")
    if "account_balance_snapshots" in tables:
        op.drop_table("account_balance_snapshots")

    transaction_columns = {column["name"] for column in inspect(bind).get_columns("transactions")}
    with op.batch_alter_table("transactions") as batch_op:
        if "is_transfer" in transaction_columns:
            batch_op.drop_index("ix_transactions_is_transfer")
            batch_op.drop_column("is_transfer")
        if "transfer_group_id" in transaction_columns:
            batch_op.drop_index("ix_transactions_transfer_group_id")
            batch_op.drop_column("transfer_group_id")

    account_columns = {column["name"] for column in inspect(bind).get_columns("financial_accounts")}
    if "balance_kind" in account_columns:
        with op.batch_alter_table("financial_accounts") as batch_op:
            batch_op.drop_column("balance_kind")
