"""001_baseline - Full schema baseline

Revision ID: 001_baseline
Revises: 
Create Date: 2026-05-22

Captures the complete PFIS schema as of Phase 6.
All tables, indexes, and constraints are created from scratch.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- categories ---
    op.create_table(
        "categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("parent_category_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("icon", sa.String(50), nullable=True),
    )

    # --- merchants ---
    op.create_table(
        "merchants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("normalized_name", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("aliases", sa.Text(), server_default="[]"),
        sa.Column("category_default_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=True),
    )

    # --- raw_emails ---
    op.create_table(
        "raw_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("gmail_message_id", sa.String(255), unique=True, nullable=True, index=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("sender", sa.String(255), nullable=True, index=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_flag", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- gmail_accounts ---
    op.create_table(
        "gmail_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("google_account_id", sa.String(255), nullable=False),
        sa.Column("access_token_ref", sa.Text(), nullable=True),
        sa.Column("refresh_token_ref", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- transactions ---
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("transaction_type", sa.Enum("debit", "credit", "refund", name="transactiontype"), nullable=False),
        sa.Column("merchant_raw", sa.String(255), nullable=True),
        sa.Column("merchant_normalized", sa.String(255), nullable=True, index=True),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("account_last4", sa.String(4), nullable=True),
        sa.Column("reference_id", sa.String(100), nullable=True),
        sa.Column("confidence_score", sa.Float(), server_default="0.0"),
        sa.Column("reviewed_flag", sa.Boolean(), nullable=False, server_default=sa.text("0"), index=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parser_version", sa.Integer(), server_default="1"),
        sa.Column("fingerprint", sa.String(64), unique=True, nullable=True, index=True),
        sa.Column("source_email_id", sa.String(36), sa.ForeignKey("raw_emails.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_txn_user_date", "transactions", ["user_id", "transaction_date"])
    op.create_index("ix_txn_user_month_category", "transactions", ["user_id", "transaction_type", "category_id"])
    op.create_index("ix_txn_user_review", "transactions", ["user_id", "reviewed_flag"])

    # --- sync_runs ---
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emails_fetched", sa.Integer(), server_default="0"),
        sa.Column("emails_processed", sa.Integer(), server_default="0"),
        sa.Column("emails_failed", sa.Integer(), server_default="0"),
        sa.Column("errors", sa.Text(), server_default="[]"),
        sa.Column("status", sa.Enum("running", "completed", "failed", name="syncstatus"), server_default="running"),
    )

    # --- budgets ---
    op.create_table(
        "budgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("monthly_limit", sa.Float(), nullable=False),
    )

    # --- user_corrections ---
    op.create_table(
        "user_corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("transaction_id", sa.String(36), sa.ForeignKey("transactions.id"), nullable=False, index=True),
        sa.Column("field_corrected", sa.String(50), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- parse_failures ---
    op.create_table(
        "parse_failures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email_id", sa.String(36), sa.ForeignKey("raw_emails.id"), nullable=False, index=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.Integer(), server_default="1"),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved", sa.Boolean(), server_default=sa.text("0")),
    )

    # --- background_jobs ---
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("job_type", sa.String(100), nullable=False, index=True),
        sa.Column("status", sa.Enum("queued", "running", "completed", "failed", name="jobstatus"), server_default="queued"),
        sa.Column("payload_json", sa.Text(), server_default="{}"),
        sa.Column("result_json", sa.Text(), server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- oauth_states ---
    op.create_table(
        "oauth_states",
        sa.Column("state", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("flow_type", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oauth_states")
    op.drop_table("background_jobs")
    op.drop_table("parse_failures")
    op.drop_table("user_corrections")
    op.drop_table("budgets")
    op.drop_table("sync_runs")
    op.drop_index("ix_txn_user_review", table_name="transactions")
    op.drop_index("ix_txn_user_month_category", table_name="transactions")
    op.drop_index("ix_txn_user_date", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("gmail_accounts")
    op.drop_table("raw_emails")
    op.drop_table("merchants")
    op.drop_table("categories")
    op.drop_table("users")
