"""Track balance-source cadence and provider coverage windows."""

from alembic import op
import sqlalchemy as sa

revision = "046_balance_source_coverage"
down_revision = "045_balance_observation_multi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_balance_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("financial_account_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("source_account_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("expected_cadence_minutes", sa.Integer(), nullable=True),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_source_record_id", sa.String(length=128), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expected_cadence_minutes IS NULL OR expected_cadence_minutes > 0",
            name="ck_account_balance_sources_cadence_positive",
        ),
        sa.ForeignKeyConstraint(["financial_account_id"], ["financial_accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "financial_account_id",
            "source",
            "source_account_id",
            name="uq_account_balance_sources_account_source",
        ),
    )
    op.create_index(
        "ix_account_balance_sources_user_id",
        "account_balance_sources",
        ["user_id"],
    )
    op.create_index(
        "ix_account_balance_sources_financial_account_id",
        "account_balance_sources",
        ["financial_account_id"],
    )
    op.create_index(
        "ix_account_balance_sources_user_updated",
        "account_balance_sources",
        ["user_id", "updated_at"],
    )
    op.create_index(
        "ix_account_balance_sources_account_source",
        "account_balance_sources",
        ["financial_account_id", "source"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_balance_sources_account_source",
        table_name="account_balance_sources",
    )
    op.drop_index(
        "ix_account_balance_sources_user_updated",
        table_name="account_balance_sources",
    )
    op.drop_index(
        "ix_account_balance_sources_financial_account_id",
        table_name="account_balance_sources",
    )
    op.drop_index("ix_account_balance_sources_user_id", table_name="account_balance_sources")
    op.drop_table("account_balance_sources")
