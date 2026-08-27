"""Store immutable, user-owned anomaly adjudication decisions.

Revision ID: 039_anomaly_adjudications
Revises: 038_account_identity_evidence
"""

import sqlalchemy as sa
from alembic import op

revision = "039_anomaly_adjudications"
down_revision = "038_account_identity_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anomaly_adjudications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("anomaly_id", sa.String(length=180), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("current_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("baseline_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("delta_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("ruleset_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_anomaly_adjudications_user_id", "anomaly_adjudications", ["user_id"]
    )
    op.create_index(
        "ix_anomaly_adjudications_user_created",
        "anomaly_adjudications",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_anomaly_adjudications_user_anomaly",
        "anomaly_adjudications",
        ["user_id", "anomaly_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_anomaly_adjudications_user_anomaly", table_name="anomaly_adjudications")
    op.drop_index("ix_anomaly_adjudications_user_created", table_name="anomaly_adjudications")
    op.drop_index("ix_anomaly_adjudications_user_id", table_name="anomaly_adjudications")
    op.drop_table("anomaly_adjudications")
