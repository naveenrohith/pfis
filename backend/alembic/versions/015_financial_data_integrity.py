"""015_financial_data_integrity

Revision ID: 015_financial_integrity
Revises: 014_auth_sessions
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "015_financial_integrity"
down_revision = "014_auth_sessions"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(precision=18, scale=2)


def _column_is_money(bind, table: str, column: str) -> bool:
    column_type = next(
        item["type"] for item in inspect(bind).get_columns(table) if item["name"] == column
    )
    return isinstance(column_type, sa.Numeric) and column_type.scale == 2


def _constraint_names(bind, table: str, kind: str) -> set[str | None]:
    inspector = inspect(bind)
    constraints = (
        inspector.get_unique_constraints(table)
        if kind == "unique"
        else inspector.get_check_constraints(table)
    )
    return {constraint["name"] for constraint in constraints}


def _assert_no_duplicates(bind, table: str, columns: tuple[str, ...]) -> None:
    column_sql = ", ".join(columns)
    duplicate = bind.execute(
        sa.text(
            f"SELECT {column_sql} FROM {table} "
            f"GROUP BY {column_sql} HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            f"Cannot add unique constraint to {table}({column_sql}); "
            "resolve duplicate rows before retrying the migration"
        )


def _assert_positive_money(bind, table: str, column: str, *, allow_zero: bool) -> None:
    operator = "<" if allow_zero else "<="
    invalid = bind.execute(
        sa.text(f"SELECT 1 FROM {table} WHERE {column} {operator} 0 LIMIT 1")
    ).first()
    if invalid is not None:
        rule = "non-negative" if allow_zero else "positive"
        raise RuntimeError(
            f"Cannot constrain {table}.{column}; resolve values that are not {rule} first"
        )


def upgrade() -> None:
    bind = op.get_bind()
    _assert_no_duplicates(bind, "budgets", ("user_id", "category_id"))
    _assert_no_duplicates(bind, "gmail_accounts", ("user_id",))
    _assert_no_duplicates(bind, "gmail_accounts", ("google_account_id",))
    _assert_positive_money(bind, "transactions", "amount", allow_zero=False)
    _assert_positive_money(bind, "budgets", "monthly_limit", allow_zero=False)
    _assert_positive_money(bind, "account_balance_snapshots", "amount", allow_zero=True)
    _assert_positive_money(bind, "goals", "target_amount", allow_zero=False)

    transaction_checks = _constraint_names(bind, "transactions", "check")
    with op.batch_alter_table("transactions") as batch_op:
        if not _column_is_money(bind, "transactions", "amount"):
            batch_op.alter_column("amount", existing_type=sa.Float(), type_=MONEY, nullable=False)
        if "ck_transactions_amount_positive" not in transaction_checks:
            batch_op.create_check_constraint("ck_transactions_amount_positive", "amount > 0")

    budget_checks = _constraint_names(bind, "budgets", "check")
    budget_uniques = _constraint_names(bind, "budgets", "unique")
    with op.batch_alter_table("budgets") as batch_op:
        if not _column_is_money(bind, "budgets", "monthly_limit"):
            batch_op.alter_column(
                "monthly_limit", existing_type=sa.Float(), type_=MONEY, nullable=False
            )
        if "ck_budgets_monthly_limit_positive" not in budget_checks:
            batch_op.create_check_constraint(
                "ck_budgets_monthly_limit_positive", "monthly_limit > 0"
            )
        if "uq_budgets_user_category" not in budget_uniques:
            batch_op.create_unique_constraint(
                "uq_budgets_user_category", ["user_id", "category_id"]
            )

    balance_checks = _constraint_names(bind, "account_balance_snapshots", "check")
    with op.batch_alter_table("account_balance_snapshots") as batch_op:
        if not _column_is_money(bind, "account_balance_snapshots", "amount"):
            batch_op.alter_column("amount", existing_type=sa.Float(), type_=MONEY, nullable=False)
        if "ck_account_balance_amount_nonnegative" not in balance_checks:
            batch_op.create_check_constraint("ck_account_balance_amount_nonnegative", "amount >= 0")

    goal_checks = _constraint_names(bind, "goals", "check")
    with op.batch_alter_table("goals") as batch_op:
        if not _column_is_money(bind, "goals", "target_amount"):
            batch_op.alter_column(
                "target_amount", existing_type=sa.Float(), type_=MONEY, nullable=False
            )
        if "ck_goals_target_amount_positive" not in goal_checks:
            batch_op.create_check_constraint("ck_goals_target_amount_positive", "target_amount > 0")

    gmail_uniques = _constraint_names(bind, "gmail_accounts", "unique")
    with op.batch_alter_table("gmail_accounts") as batch_op:
        if "uq_gmail_accounts_user" not in gmail_uniques:
            batch_op.create_unique_constraint("uq_gmail_accounts_user", ["user_id"])
        if "uq_gmail_accounts_google_account" not in gmail_uniques:
            batch_op.create_unique_constraint(
                "uq_gmail_accounts_google_account", ["google_account_id"]
            )

    account_uniques = _constraint_names(bind, "financial_accounts", "unique")
    with op.batch_alter_table("financial_accounts") as batch_op:
        if "uq_financial_accounts_user_masked" in account_uniques:
            batch_op.drop_constraint("uq_financial_accounts_user_masked", type_="unique")
        if "uq_financial_accounts_user_identity" not in account_uniques:
            batch_op.create_unique_constraint(
                "uq_financial_accounts_user_identity",
                ["user_id", "institution_name", "account_type", "masked_number"],
            )


def downgrade() -> None:
    with op.batch_alter_table("financial_accounts") as batch_op:
        batch_op.drop_constraint("uq_financial_accounts_user_identity", type_="unique")
        batch_op.create_unique_constraint(
            "uq_financial_accounts_user_masked", ["user_id", "masked_number"]
        )

    with op.batch_alter_table("gmail_accounts") as batch_op:
        batch_op.drop_constraint("uq_gmail_accounts_google_account", type_="unique")
        batch_op.drop_constraint("uq_gmail_accounts_user", type_="unique")

    with op.batch_alter_table("goals") as batch_op:
        batch_op.drop_constraint("ck_goals_target_amount_positive", type_="check")
        batch_op.alter_column(
            "target_amount", existing_type=MONEY, type_=sa.Float(), nullable=False
        )

    with op.batch_alter_table("account_balance_snapshots") as batch_op:
        batch_op.drop_constraint("ck_account_balance_amount_nonnegative", type_="check")
        batch_op.alter_column("amount", existing_type=MONEY, type_=sa.Float(), nullable=False)

    with op.batch_alter_table("budgets") as batch_op:
        batch_op.drop_constraint("uq_budgets_user_category", type_="unique")
        batch_op.drop_constraint("ck_budgets_monthly_limit_positive", type_="check")
        batch_op.alter_column(
            "monthly_limit", existing_type=MONEY, type_=sa.Float(), nullable=False
        )

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint("ck_transactions_amount_positive", type_="check")
        batch_op.alter_column("amount", existing_type=MONEY, type_=sa.Float(), nullable=False)
