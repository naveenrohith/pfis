"""Add evidence-backed liability and EMI anatomy fields.

Revision ID: 025_liability_evidence
Revises: 024_merchant_emi_intelligence
"""

from alembic import op
import sqlalchemy as sa


revision = "025_liability_evidence"
down_revision = "024_merchant_emi_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("source_identifier", sa.String(length=160), nullable=True),
        sa.Column("issuer_plan_reference", sa.String(length=64), nullable=True),
        sa.Column("observed_original_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("observed_monthly_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("observed_principal_component", sa.Numeric(18, 2), nullable=True),
        sa.Column("observed_interest_component", sa.Numeric(18, 2), nullable=True),
        sa.Column("observed_tax_component", sa.Numeric(18, 2), nullable=True),
        sa.Column("observed_fee_component", sa.Numeric(18, 2), nullable=True),
        sa.Column("last_observed_statement_date", sa.Date(), nullable=True),
        sa.Column(
            "evidence_line_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "schedule_status",
            sa.String(length=24),
            nullable=False,
            server_default="not_provided",
        ),
    ):
        op.add_column("liabilities", column)
    op.create_unique_constraint(
        "uq_liability_user_account_plan",
        "liabilities",
        ["user_id", "financial_account_id", "issuer_plan_reference"],
    )
    op.create_index(
        "ix_liabilities_user_schedule_status",
        "liabilities",
        ["user_id", "schedule_status"],
    )

    for column in (
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("fee_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column(
            "source_kind",
            sa.String(length=24),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("source_identifier", sa.String(length=160), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
    ):
        op.add_column("liability_schedule_items", column)


def downgrade() -> None:
    for column in (
        "confidence",
        "source_identifier",
        "source_kind",
        "fee_amount",
        "tax_amount",
    ):
        op.drop_column("liability_schedule_items", column)
    op.drop_index("ix_liabilities_user_schedule_status", table_name="liabilities")
    op.drop_constraint(
        "uq_liability_user_account_plan",
        "liabilities",
        type_="unique",
    )
    for column in (
        "schedule_status",
        "evidence_line_count",
        "last_observed_statement_date",
        "observed_fee_component",
        "observed_tax_component",
        "observed_interest_component",
        "observed_principal_component",
        "observed_monthly_amount",
        "observed_original_amount",
        "issuer_plan_reference",
        "source_identifier",
    ):
        op.drop_column("liabilities", column)
