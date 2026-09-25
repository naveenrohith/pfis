"""Extend card calendar with sourced fee and milestone details."""

import sqlalchemy as sa
from alembic import op

revision = "058_card_calendar_extensions"
down_revision = "057_financial_change_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "card_calendar_events",
        sa.Column(
            "source_label",
            sa.String(length=160),
            server_default="User-entered",
            nullable=False,
        ),
    )
    op.add_column(
        "card_calendar_events",
        sa.Column("source_identifier", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "card_calendar_events",
        sa.Column("annual_fee_amount", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "card_calendar_events",
        sa.Column("fee_reversal_condition", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "card_calendar_events",
        sa.Column("fee_reversal_status", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "card_calendar_events",
        sa.Column("milestone_spend_target", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "card_calendar_events",
        sa.Column("milestone_period_start", sa.Date(), nullable=True),
    )
    op.add_column(
        "card_calendar_events",
        sa.Column("milestone_period_end", sa.Date(), nullable=True),
    )
    op.create_index(
        "ix_card_calendar_events_user_account_date",
        "card_calendar_events",
        ["user_id", "financial_account_id", "event_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_card_calendar_events_user_account_date",
        table_name="card_calendar_events",
    )
    op.drop_column("card_calendar_events", "milestone_period_end")
    op.drop_column("card_calendar_events", "milestone_period_start")
    op.drop_column("card_calendar_events", "milestone_spend_target")
    op.drop_column("card_calendar_events", "fee_reversal_status")
    op.drop_column("card_calendar_events", "fee_reversal_condition")
    op.drop_column("card_calendar_events", "annual_fee_amount")
    op.drop_column("card_calendar_events", "source_identifier")
    op.drop_column("card_calendar_events", "source_label")
