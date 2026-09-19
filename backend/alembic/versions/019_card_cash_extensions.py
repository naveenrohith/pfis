"""card and cash extensions

Revision ID: 019_card_cash_extensions
Revises: 018_financial_position
"""

import sqlalchemy as sa
from alembic import op

revision = "019_card_cash_extensions"
down_revision = "018_financial_position"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("preferred_payment_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id")),
        sa.Column("utilization_target_pct", sa.Numeric(5, 2)),
        sa.Column("reward_rules_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "financial_account_id", name="uq_card_preferences_user_account"),
    )
    op.create_table(
        "card_payment_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("paying_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id")),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("planned_for", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("note", sa.String(240)),
        sa.Column("transfer_group_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_card_payment_intents_user_date", "card_payment_intents", ["user_id", "planned_for", "status"])
    op.create_table(
        "card_calendar_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_card_calendar_events_user_date", "card_calendar_events", ["user_id", "event_date"])


def downgrade() -> None:
    op.drop_table("card_calendar_events")
    op.drop_table("card_payment_intents")
    op.drop_table("card_preferences")
