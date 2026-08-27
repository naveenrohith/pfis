"""Persist non-secret balance-provider consent lifecycle state."""

import sqlalchemy as sa
from alembic import op

revision = "050_balance_provider_connections"
down_revision = "049_balance_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "balance_provider_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("consent_reference_hash", sa.String(length=64), nullable=True),
        sa.Column("consent_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider_type",
            name="uq_balance_provider_connections_user_provider",
        ),
    )
    op.create_index(
        "ix_balance_provider_connections_user_id",
        "balance_provider_connections",
        ["user_id"],
    )
    op.create_index(
        "ix_balance_provider_connections_user_status",
        "balance_provider_connections",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_balance_provider_connections_user_status",
        table_name="balance_provider_connections",
    )
    op.drop_index(
        "ix_balance_provider_connections_user_id",
        table_name="balance_provider_connections",
    )
    op.drop_table("balance_provider_connections")
