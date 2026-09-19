"""Make connector balance observations retry-safe."""

import sqlalchemy as sa
from alembic import op

revision = "044_balance_source_identity"
down_revision = "043_balance_position_truth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_balance_snapshots",
        sa.Column("source_record_id", sa.String(length=128), nullable=True),
    )
    op.create_unique_constraint(
        "uq_account_balance_snapshots_source_record",
        "account_balance_snapshots",
        ["financial_account_id", "source", "source_record_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_account_balance_snapshots_source_record",
        "account_balance_snapshots",
        type_="unique",
    )
    op.drop_column("account_balance_snapshots", "source_record_id")
