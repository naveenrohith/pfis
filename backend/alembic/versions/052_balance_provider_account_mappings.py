"""Separate provider account identities from generic connector state."""

import sqlalchemy as sa
from alembic import op

revision = "052_provider_account_mappings"
down_revision = "051_card_position_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "balance_provider_account_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("financial_account_id", sa.String(length=36), nullable=False),
        sa.Column("provider_type", sa.String(length=50), nullable=False),
        sa.Column("provider_account_id", sa.String(length=128), nullable=False),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="provider_discovery",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["financial_account_id"], ["financial_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider_type",
            "financial_account_id",
            name="uq_balance_provider_mappings_user_provider_account",
        ),
        sa.UniqueConstraint(
            "user_id",
            "provider_type",
            "provider_account_id",
            name="uq_balance_provider_mappings_user_provider_identity",
        ),
    )
    op.create_index(
        "ix_balance_provider_mappings_user_id",
        "balance_provider_account_mappings",
        ["user_id"],
    )
    op.create_index(
        "ix_balance_provider_mappings_financial_account_id",
        "balance_provider_account_mappings",
        ["financial_account_id"],
    )
    op.create_index(
        "ix_balance_provider_mappings_user_provider",
        "balance_provider_account_mappings",
        ["user_id", "provider_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_balance_provider_mappings_user_provider",
        table_name="balance_provider_account_mappings",
    )
    op.drop_index(
        "ix_balance_provider_mappings_financial_account_id",
        table_name="balance_provider_account_mappings",
    )
    op.drop_index(
        "ix_balance_provider_mappings_user_id",
        table_name="balance_provider_account_mappings",
    )
    op.drop_table("balance_provider_account_mappings")
