"""009_financial_accounts

Revision ID: 009_financial_accounts
Revises: 008_operational_indexes
Create Date: 2026-07-10
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "009_financial_accounts"
down_revision = "008_operational_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    # SQLite batch operations can leave an empty temporary table when a prior
    # migration attempt is interrupted. Recover only the provably empty case;
    # a populated table requires manual inspection to avoid data loss.
    if "_alembic_tmp_transactions" in tables:
        temp_rows = bind.execute(
            sa.text("SELECT COUNT(*) FROM _alembic_tmp_transactions")
        ).scalar_one()
        if temp_rows:
            raise RuntimeError(
                "Refusing to remove populated _alembic_tmp_transactions; inspect it manually"
            )
        op.drop_table("_alembic_tmp_transactions")
        tables = inspect(bind).get_table_names()

    if "financial_accounts" not in tables:
        op.create_table(
            "financial_accounts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("institution_name", sa.String(160), nullable=False, server_default="Unknown"),
            sa.Column("account_type", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("masked_number", sa.String(32), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
            sa.Column("connector_account_id", sa.String(36), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "user_id", "masked_number", name="uq_financial_accounts_user_masked"
            ),
        )

    indexes = {index["name"] for index in inspect(bind).get_indexes("financial_accounts")}
    for index_name, columns in (
        ("ix_financial_accounts_user_id", ["user_id"]),
        ("ix_financial_accounts_connector_account_id", ["connector_account_id"]),
        ("ix_financial_accounts_is_active", ["is_active"]),
        ("ix_financial_accounts_user_active", ["user_id", "is_active"]),
    ):
        if index_name not in indexes:
            op.create_index(index_name, "financial_accounts", columns)
            indexes.add(index_name)

    if "transactions" not in tables:
        return

    transaction_columns = {column["name"] for column in inspect(bind).get_columns("transactions")}
    if "financial_account_id" not in transaction_columns:
        # SQLite requires a copy-and-move migration when adding a foreign key.
        # Batch mode also keeps the migration portable to PostgreSQL.
        with op.batch_alter_table("transactions") as batch_op:
            batch_op.add_column(sa.Column("financial_account_id", sa.String(36), nullable=True))
            batch_op.create_foreign_key(
                "fk_transactions_financial_account_id",
                "financial_accounts",
                ["financial_account_id"],
                ["id"],
            )
            batch_op.create_index("ix_transactions_financial_account_id", ["financial_account_id"])

    # Backfill only masked metadata already present in PFIS. Full account numbers
    # are never reconstructed or stored.
    rows = bind.execute(
        sa.text(
            """
            SELECT t.user_id, t.account_last4, COALESCE(t.currency, 'INR') AS currency
            FROM transactions t
            WHERE t.account_last4 IS NOT NULL AND t.account_last4 <> ''
            GROUP BY t.user_id, t.account_last4, t.currency
            """
        )
    ).mappings()
    for row in rows:
        masked_number = f"****{row['account_last4']}"
        existing = bind.execute(
            sa.text(
                "SELECT id FROM financial_accounts WHERE user_id = :user_id AND masked_number = :masked_number"
            ),
            {"user_id": row["user_id"], "masked_number": masked_number},
        ).scalar_one_or_none()
        account_id = existing or str(uuid.uuid4())
        if existing is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO financial_accounts
                    (id, user_id, institution_name, account_type, masked_number, currency, is_active, created_at)
                    VALUES (:id, :user_id, 'Unknown', 'unknown', :masked_number, :currency, :is_active, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": account_id,
                    "user_id": row["user_id"],
                    "masked_number": masked_number,
                    "currency": row["currency"],
                    "is_active": True,
                },
            )
        bind.execute(
            sa.text(
                """
                UPDATE transactions
                SET financial_account_id = :account_id
                WHERE user_id = :user_id AND account_last4 = :account_last4
                  AND financial_account_id IS NULL
                """
            ),
            {
                "account_id": account_id,
                "user_id": row["user_id"],
                "account_last4": row["account_last4"],
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "transactions" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("transactions")}
        if "financial_account_id" in {
            column["name"] for column in inspector.get_columns("transactions")
        }:
            with op.batch_alter_table("transactions") as batch_op:
                if "ix_transactions_financial_account_id" in indexes:
                    batch_op.drop_index("ix_transactions_financial_account_id")
                batch_op.drop_constraint("fk_transactions_financial_account_id", type_="foreignkey")
                batch_op.drop_column("financial_account_id")

    if "financial_accounts" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("financial_accounts")}
        for index_name in (
            "ix_financial_accounts_user_active",
            "ix_financial_accounts_is_active",
            "ix_financial_accounts_connector_account_id",
            "ix_financial_accounts_user_id",
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="financial_accounts")
        op.drop_table("financial_accounts")
