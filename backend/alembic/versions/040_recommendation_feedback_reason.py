"""Persist structured reasons for recommendation relevance feedback.

Revision ID: 040_recommend_feedback_reason
Revises: 039_anomaly_adjudications
"""

import sqlalchemy as sa
from alembic import op

revision = "040_recommend_feedback_reason"
down_revision = "039_anomaly_adjudications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendation_states",
        sa.Column("decision_reason", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recommendation_states", "decision_reason")
