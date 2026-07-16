"""013_merchant_intelligence_foundation

Revision ID: 013_merchant_intel
Revises: 012_financial_rhythm
Create Date: 2026-07-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "013_merchant_intel"
down_revision = "012_financial_rhythm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "user_merchant_rules" not in tables:
        op.create_table(
            "user_merchant_rules",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("raw_descriptor", sa.String(255), nullable=False),
            sa.Column("descriptor_key", sa.String(255), nullable=False),
            sa.Column("normalized_name", sa.String(255), nullable=False),
            sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=True),
            sa.Column(
                "source", sa.String(32), nullable=False, server_default="user_correction"
            ),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
            sa.Column("source_transaction_id", sa.String(36), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
            sa.UniqueConstraint(
                "user_id", "descriptor_key", name="uq_user_merchant_rule_descriptor"
            ),
        )
        op.create_index("ix_user_merchant_rules_user_id", "user_merchant_rules", ["user_id"])
        op.create_index(
            "ix_user_merchant_rules_user_name",
            "user_merchant_rules",
            ["user_id", "normalized_name"],
        )

    transaction_columns = {
        column["name"] for column in inspect(bind).get_columns("transactions")
    }
    with op.batch_alter_table("transactions") as batch_op:
        if "merchant_resolution_source" not in transaction_columns:
            batch_op.add_column(
                sa.Column(
                    "merchant_resolution_source",
                    sa.String(32),
                    nullable=False,
                    server_default="legacy",
                )
            )
        if "merchant_resolution_confidence" not in transaction_columns:
            batch_op.add_column(
                sa.Column("merchant_resolution_confidence", sa.Float(), nullable=True)
            )
        if "merchant_rule_id" not in transaction_columns:
            batch_op.add_column(sa.Column("merchant_rule_id", sa.String(36), nullable=True))
        if "merchant_resolver_version" not in transaction_columns:
            batch_op.add_column(
                sa.Column(
                    "merchant_resolver_version",
                    sa.Integer(),
                    nullable=False,
                    server_default="1",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "transactions" in inspector.get_table_names():
        transaction_columns = {
            column["name"] for column in inspector.get_columns("transactions")
        }
        with op.batch_alter_table("transactions") as batch_op:
            for column_name in (
                "merchant_resolver_version",
                "merchant_rule_id",
                "merchant_resolution_confidence",
                "merchant_resolution_source",
            ):
                if column_name in transaction_columns:
                    batch_op.drop_column(column_name)

    if "user_merchant_rules" in inspect(bind).get_table_names():
        op.drop_index("ix_user_merchant_rules_user_name", table_name="user_merchant_rules")
        op.drop_index("ix_user_merchant_rules_user_id", table_name="user_merchant_rules")
        op.drop_table("user_merchant_rules")
