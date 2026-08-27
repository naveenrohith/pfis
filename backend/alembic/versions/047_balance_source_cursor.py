"""Persist provider-neutral balance connector cursors."""

import sqlalchemy as sa
from alembic import op

revision = "047_balance_source_cursor"
down_revision = "046_balance_source_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_balance_sources",
        sa.Column("cursor_token", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("account_balance_sources", "cursor_token")
