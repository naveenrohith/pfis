"""Allow multiple balance observations on the same financial day.

Provider observations, statement conclusions, and user-entered checks can all
share a calendar date while carrying different effective times and provenance.
The source-record identity constraint remains the retry/idempotency boundary.

Revision ID: 045_balance_observation_multi
Revises: 044_balance_source_identity
"""

from alembic import op

revision = "045_balance_observation_multi"
down_revision = "044_balance_source_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_account_balance_snapshots_account_as_of",
        "account_balance_snapshots",
        type_="unique",
    )
    op.create_index(
        "ix_account_balance_snapshots_account_effective",
        "account_balance_snapshots",
        ["financial_account_id", "as_of", "effective_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_balance_snapshots_account_effective",
        table_name="account_balance_snapshots",
    )
    op.create_unique_constraint(
        "uq_account_balance_snapshots_account_as_of",
        "account_balance_snapshots",
        ["financial_account_id", "as_of"],
    )
