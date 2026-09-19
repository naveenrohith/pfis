"""Fence stale Gmail OAuth callbacks and normalize legacy message identities.

Revision ID: 056_gmail_connection_fences
Revises: 055_deposit_line_review
"""

import sqlalchemy as sa
from alembic import op

revision = "056_gmail_connection_fences"
down_revision = "055_deposit_line_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "gmail_connection_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "oauth_states",
        sa.Column(
            "connection_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # The pre-multi-user schema stored Gmail message IDs globally. Prefix old
    # rows with their owner so the connector can use the same identity scheme
    # for every user. If a partially upgraded database already has the target
    # prefixed row, retain both rows and let the ingestion compatibility lookup
    # treat the legacy row as the duplicate; this avoids deleting source or
    # derived evidence during migration.
    op.execute(
        sa.text(
            """
            UPDATE raw_emails AS legacy
            SET gmail_message_id = legacy.user_id || ':' || legacy.gmail_message_id
            WHERE legacy.gmail_message_id IS NOT NULL
              AND legacy.gmail_message_id NOT LIKE legacy.user_id || ':%'
              AND NOT EXISTS (
                  SELECT 1
                  FROM raw_emails AS scoped
                  WHERE scoped.id <> legacy.id
                    AND scoped.gmail_message_id =
                        legacy.user_id || ':' || legacy.gmail_message_id
              )
            """
        )
    )


def downgrade() -> None:
    # Message IDs cannot be safely unprefixed after this migration because a
    # prefixed value may have been created by the new connector. Keep the
    # normalized identity values and only remove the lifecycle columns.
    op.drop_column("oauth_states", "connection_generation")
    op.drop_column("users", "gmail_connection_generation")
