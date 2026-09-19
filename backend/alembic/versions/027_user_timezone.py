"""Add the user financial timezone.

Revision ID: 027_user_timezone
Revises: 026_spend_truth
"""

import sqlalchemy as sa
from alembic import op

revision = "027_user_timezone"
down_revision = "026_spend_truth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Kolkata",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "timezone")
