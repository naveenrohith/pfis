"""Persist consequence ranges and conflict-aware recommendation context.

Revision ID: 035_rec_conflict_contract
Revises: 034_account_deletion_compat
"""

import sqlalchemy as sa
from alembic import op

revision = "035_rec_conflict_contract"
down_revision = "034_account_deletion_compat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recommendation_states", sa.Column("smallest_action", sa.Text()))
    op.add_column("recommendation_states", sa.Column("consequence_json", sa.Text()))
    op.add_column("recommendation_states", sa.Column("conflicts_json", sa.Text()))
    op.add_column("recommendation_states", sa.Column("goal_links_json", sa.Text()))
    op.add_column(
        "recommendation_states",
        sa.Column(
            "confidence", sa.Numeric(precision=5, scale=4), nullable=False, server_default="0"
        ),
    )
    op.add_column("recommendation_states", sa.Column("freshness_as_of", sa.Date()))
    op.add_column(
        "recommendation_states",
        sa.Column("urgency", sa.String(length=16), nullable=False, server_default="monitor"),
    )
    op.add_column(
        "recommendation_states",
        sa.Column(
            "reversibility", sa.String(length=24), nullable=False, server_default="reversible"
        ),
    )


def downgrade() -> None:
    op.drop_column("recommendation_states", "reversibility")
    op.drop_column("recommendation_states", "urgency")
    op.drop_column("recommendation_states", "freshness_as_of")
    op.drop_column("recommendation_states", "confidence")
    op.drop_column("recommendation_states", "goal_links_json")
    op.drop_column("recommendation_states", "conflicts_json")
    op.drop_column("recommendation_states", "consequence_json")
    op.drop_column("recommendation_states", "smallest_action")
