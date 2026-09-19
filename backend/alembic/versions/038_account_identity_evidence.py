"""Persist account identity confidence and lifecycle evidence.

Revision ID: 038_account_identity_evidence
Revises: 037_recommendation_resolution
"""

import sqlalchemy as sa
from alembic import op

revision = "038_account_identity_evidence"
down_revision = "037_recommendation_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "financial_accounts",
        sa.Column(
            "identity_status",
            sa.String(length=20),
            nullable=False,
            server_default="unresolved",
        ),
    )
    op.add_column(
        "financial_accounts",
        sa.Column(
            "identity_confidence",
            sa.Numeric(precision=4, scale=3),
            nullable=False,
            server_default="0.350",
        ),
    )
    op.add_column(
        "financial_accounts",
        sa.Column("identity_evidence_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "financial_accounts",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE financial_accounts
            SET identity_status = CASE
                    WHEN account_type = 'unknown'
                      OR lower(institution_name) = 'unknown'
                    THEN 'unresolved'
                    ELSE 'confirmed'
                END,
                identity_confidence = CASE
                    WHEN account_type = 'unknown'
                      OR lower(institution_name) = 'unknown'
                    THEN 0.350
                    ELSE 0.950
                END
            """
        )
    )


def downgrade() -> None:
    op.drop_column("financial_accounts", "updated_at")
    op.drop_column("financial_accounts", "identity_evidence_json")
    op.drop_column("financial_accounts", "identity_confidence")
    op.drop_column("financial_accounts", "identity_status")
