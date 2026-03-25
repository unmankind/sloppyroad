"""Add multi-tenant BYOK tables: author_api_keys, api_key_audit_log,
email verification fields on users, update plan_type defaults.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-15
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── author_api_keys table ──────────────────────────────────────────
    op.create_table(
        "author_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("key_suffix", sa.String(10), nullable=False),
        sa.Column("is_valid", sa.Boolean(), default=True, nullable=False),
        sa.Column("validated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_author_api_key_provider"
        ),
    )

    # ── api_key_audit_log table ────────────────────────────────────────
    op.create_table(
        "api_key_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_audit_user_created",
        "api_key_audit_log",
        ["user_id", "created_at"],
    )

    # ── Email verification columns on users ────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verification_token", sa.String(64), nullable=True
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verification_token_expires_at",
            sa.DateTime(),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
    )
    # Unique index on verification token
    op.create_index(
        "idx_users_verification_token",
        "users",
        ["email_verification_token"],
        unique=True,
    )

    # ── Auto-verify ALL existing users (don't lock them out) ───────────
    op.execute(
        "UPDATE users SET email_verified = true WHERE email IS NOT NULL"
    )

    # ── Update plan_type: trial → free for existing author profiles ────
    op.execute(
        "UPDATE author_profiles SET plan_type = 'free' "
        "WHERE plan_type = 'trial'"
    )

    # ── Grandfather admin: set first author (user_id=1) to admin ───────
    # This is safe because user_id=1 is the project owner
    op.execute(
        "UPDATE author_profiles SET plan_type = 'admin' "
        "WHERE user_id = 1"
    )


def downgrade() -> None:
    # Drop verification columns
    op.drop_index("idx_users_verification_token", table_name="users")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verification_token_expires_at")
    op.drop_column("users", "email_verification_token")
    op.drop_column("users", "email_verified")

    # Drop audit log
    op.drop_index(
        "idx_audit_user_created", table_name="api_key_audit_log"
    )
    op.drop_table("api_key_audit_log")

    # Drop API keys
    op.drop_table("author_api_keys")

    # Revert plan_type changes
    op.execute(
        "UPDATE author_profiles SET plan_type = 'trial' "
        "WHERE plan_type IN ('free', 'admin')"
    )
