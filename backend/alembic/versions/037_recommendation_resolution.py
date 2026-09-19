"""Persist deterministic recommendation resolution context.

Revision ID: 037_recommendation_resolution
Revises: 036_temporal_source_history
"""

import sqlalchemy as sa
from alembic import op

revision = "037_recommendation_resolution"
down_revision = "036_temporal_source_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recommendation_states", sa.Column("resolution_json", sa.Text()))


def downgrade() -> None:
    op.drop_column("recommendation_states", "resolution_json")
