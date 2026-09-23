"""Add per-user durable financial change replay metadata."""

import sqlalchemy as sa
from alembic import op

revision = "057_financial_change_journal"
down_revision = "056_gmail_connection_fences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "financial_change_cursors",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("current_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_financial_change_cursors_user_id_users",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_financial_change_cursors"),
    )
    op.create_table(
        "financial_change_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_financial_change_events_user_id_users",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_change_events"),
        sa.UniqueConstraint("event_id", name="uq_financial_change_event_id"),
        sa.UniqueConstraint("user_id", "sequence", name="uq_financial_change_user_sequence"),
    )
    op.create_index(
        "ix_financial_change_events_user_id", "financial_change_events", ["user_id"]
    )
    op.create_index(
        "ix_financial_change_events_created_at", "financial_change_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_financial_change_events_created_at", table_name="financial_change_events")
    op.drop_index("ix_financial_change_events_user_id", table_name="financial_change_events")
    op.drop_table("financial_change_events")
    op.drop_table("financial_change_cursors")
