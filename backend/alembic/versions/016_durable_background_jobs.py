"""016_durable_background_jobs

Revision ID: 016_durable_jobs
Revises: 015_financial_integrity
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "016_durable_jobs"
down_revision = "015_financial_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("background_jobs")}
    with op.batch_alter_table("background_jobs") as batch_op:
        if "attempt_count" not in columns:
            batch_op.add_column(
                sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
            )
        if "max_attempts" not in columns:
            batch_op.add_column(
                sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3")
            )
        if "available_at" not in columns:
            batch_op.add_column(sa.Column("available_at", sa.DateTime(timezone=True)))
        if "lease_owner" not in columns:
            batch_op.add_column(sa.Column("lease_owner", sa.String(64)))
        if "lease_expires_at" not in columns:
            batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        if "idempotency_key" not in columns:
            batch_op.add_column(sa.Column("idempotency_key", sa.String(64)))

    inspector = inspect(bind)
    checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("background_jobs")
    }
    uniques = {
        constraint["name"] for constraint in inspector.get_unique_constraints("background_jobs")
    }
    indexes = {index["name"] for index in inspector.get_indexes("background_jobs")}
    with op.batch_alter_table("background_jobs") as batch_op:
        if "ck_background_jobs_attempt_nonnegative" not in checks:
            batch_op.create_check_constraint(
                "ck_background_jobs_attempt_nonnegative", "attempt_count >= 0"
            )
        if "ck_background_jobs_max_attempts_positive" not in checks:
            batch_op.create_check_constraint(
                "ck_background_jobs_max_attempts_positive", "max_attempts > 0"
            )
        if "uq_background_jobs_idempotency_key" not in uniques:
            batch_op.create_unique_constraint(
                "uq_background_jobs_idempotency_key", ["idempotency_key"]
            )
        if "ix_background_jobs_due" not in indexes:
            batch_op.create_index("ix_background_jobs_due", ["status", "available_at"])


def downgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch_op:
        batch_op.drop_index("ix_background_jobs_due")
        batch_op.drop_constraint("uq_background_jobs_idempotency_key", type_="unique")
        batch_op.drop_constraint("ck_background_jobs_max_attempts_positive", type_="check")
        batch_op.drop_constraint("ck_background_jobs_attempt_nonnegative", type_="check")
        for column in (
            "idempotency_key",
            "lease_expires_at",
            "lease_owner",
            "available_at",
            "max_attempts",
            "attempt_count",
        ):
            batch_op.drop_column(column)
