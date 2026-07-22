"""014_auth_session_foundation

Revision ID: 014_auth_sessions
Revises: 013_merchant_intel
Create Date: 2026-07-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "014_auth_sessions"
down_revision = "013_merchant_intel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "auth_identities" not in tables:
        op.create_table(
            "auth_identities",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("provider_subject", sa.String(255), nullable=False),
            sa.Column("email_at_link", sa.String(255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "provider", "provider_subject", name="uq_auth_identity_provider_subject"
            ),
        )
        op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])
        op.create_index(
            "ix_auth_identities_user_provider", "auth_identities", ["user_id", "provider"]
        )

    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("csrf_token_hash", sa.String(64), nullable=False),
            sa.Column("mode", sa.String(16), nullable=False, server_default="auth"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        )
        op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
        op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])
        op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
        op.create_index("ix_auth_sessions_user_active", "auth_sessions", ["user_id", "revoked_at"])

    oauth_columns = {column["name"] for column in inspector.get_columns("oauth_states")}
    with op.batch_alter_table("oauth_states") as batch_op:
        if "browser_token_hash" not in oauth_columns:
            batch_op.add_column(sa.Column("browser_token_hash", sa.String(64), nullable=True))
        if "code_verifier_ref" not in oauth_columns:
            batch_op.add_column(sa.Column("code_verifier_ref", sa.String(500), nullable=True))
        if "nonce_ref" not in oauth_columns:
            batch_op.add_column(sa.Column("nonce_ref", sa.String(500), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "oauth_states" in inspector.get_table_names():
        oauth_columns = {column["name"] for column in inspector.get_columns("oauth_states")}
        with op.batch_alter_table("oauth_states") as batch_op:
            for name in ("nonce_ref", "code_verifier_ref", "browser_token_hash"):
                if name in oauth_columns:
                    batch_op.drop_column(name)

    tables = inspect(bind).get_table_names()
    if "auth_sessions" in tables:
        op.drop_table("auth_sessions")
    if "auth_identities" in tables:
        op.drop_table("auth_identities")
