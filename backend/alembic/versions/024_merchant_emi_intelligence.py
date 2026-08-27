"""Add explainable merchant and EMI statement intelligence.

Revision ID: 024_merchant_emi_intelligence
Revises: 023_account_link_rules
"""

from alembic import op
import sqlalchemy as sa


revision = "024_merchant_emi_intelligence"
down_revision = "023_account_link_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "statement_lines",
        sa.Column("component_kind", sa.String(length=32), nullable=False, server_default="ordinary"),
    )
    op.add_column(
        "statement_lines",
        sa.Column("issuer_plan_reference", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "statement_lines",
        sa.Column("installment_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "statement_lines",
        sa.Column("merchant_normalized", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "statement_lines",
        sa.Column("merchant_confidence", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_statement_lines_component_kind", "statement_lines", ["component_kind"]
    )
    op.create_index(
        "ix_statement_lines_issuer_plan_reference",
        "statement_lines",
        ["issuer_plan_reference"],
    )


def downgrade() -> None:
    op.drop_index("ix_statement_lines_issuer_plan_reference", table_name="statement_lines")
    op.drop_index("ix_statement_lines_component_kind", table_name="statement_lines")
    for column in (
        "merchant_confidence",
        "merchant_normalized",
        "installment_number",
        "issuer_plan_reference",
        "component_kind",
    ):
        op.drop_column("statement_lines", column)
