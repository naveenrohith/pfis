"""bill, dispute, health, household, and settlement extensions

Revision ID: 021_roadmap_extensions
Revises: 020_transaction_management
"""

import sqlalchemy as sa
from alembic import op

revision = "021_roadmap_extensions"
down_revision = "020_transaction_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roadmap_bills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id")),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("bill_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("cadence", sa.String(20)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_identifier", sa.String(128)),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_roadmap_bills_user_id", "roadmap_bills", ["user_id"])
    op.create_index(
        "ix_roadmap_bills_user_due",
        "roadmap_bills",
        ["user_id", "due_date", "status"],
    )
    op.create_table(
        "health_checklist_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_type", sa.String(40), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "item_type", name="uq_health_checklist_user_type"),
    )
    op.create_index("ix_health_checklist_items_user_id", "health_checklist_items", ["user_id"])
    op.create_table(
        "card_disputes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("statement_line_id", sa.String(36), sa.ForeignKey("statement_lines.id")),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("complaint_date", sa.Date(), nullable=False),
        sa.Column("reference_number", sa.String(100)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_card_disputes_user_id", "card_disputes", ["user_id"])
    op.create_index("ix_card_disputes_financial_account_id", "card_disputes", ["financial_account_id"])
    op.create_index(
        "ix_card_disputes_user_status",
        "card_disputes",
        ["user_id", "status", "complaint_date"],
    )
    op.create_table(
        "households",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_households_owner_user_id", "households", ["owner_user_id"])
    op.create_table(
        "household_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("visibility", sa.String(32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("household_id", "user_id", name="uq_household_member"),
    )
    op.create_index("ix_household_members_household_id", "household_members", ["household_id"])
    op.create_index("ix_household_members_user_id", "household_members", ["user_id"])
    op.create_table(
        "household_expenses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("payer_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("splits_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_household_expenses_household_id", "household_expenses", ["household_id"])
    op.create_index(
        "ix_household_expenses_household_date",
        "household_expenses",
        ["household_id", "expense_date"],
    )
    op.create_table(
        "household_settlements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("from_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("to_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("note", sa.String(240)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_household_settlements_household_id", "household_settlements", ["household_id"])
    op.create_index(
        "ix_household_settlements_household_status",
        "household_settlements",
        ["household_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("household_settlements")
    op.drop_table("household_expenses")
    op.drop_table("household_members")
    op.drop_table("households")
    op.drop_table("card_disputes")
    op.drop_table("health_checklist_items")
    op.drop_table("roadmap_bills")
