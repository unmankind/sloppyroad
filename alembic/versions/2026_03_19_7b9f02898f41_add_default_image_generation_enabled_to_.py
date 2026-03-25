"""Sync ORM drift + arc continuity fields.

- Add default_image_generation_enabled to author_profiles
- Add missing FK constraint on characters.faction_id -> factions.id
- Fix users.email_verification_token index (unique index -> partial + constraint)
- Add arc_summary and arc_promises_outstanding to arc_plans

Revision ID: 7b9f02898f41
Revises: e5f6a7b8c9d0
Create Date: 2026-03-19
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7b9f02898f41"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Missing column on author_profiles (idempotent — production already has it)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='author_profiles' "
        "AND column_name='default_image_generation_enabled'"
    ))
    if not result.fetchone():
        op.add_column(
            "author_profiles",
            sa.Column(
                "default_image_generation_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )

    # 2. Missing FK on characters.faction_id
    op.create_foreign_key(
        "fk_characters_faction_id",
        "characters",
        "factions",
        ["faction_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Fix users verification token index: unique -> non-unique partial + unique constraint
    op.drop_index("idx_users_verification_token", table_name="users")
    op.create_index(
        "idx_users_verification_token",
        "users",
        ["email_verification_token"],
        unique=False,
        postgresql_where=sa.text("email_verification_token IS NOT NULL"),
    )
    op.create_unique_constraint(
        "uq_users_email_verification_token",
        "users",
        ["email_verification_token"],
    )

    # 4. Arc continuity fields
    op.add_column(
        "arc_plans",
        sa.Column("arc_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "arc_plans",
        sa.Column("arc_promises_outstanding", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("arc_plans", "arc_promises_outstanding")
    op.drop_column("arc_plans", "arc_summary")
    op.drop_constraint("uq_users_email_verification_token", "users", type_="unique")
    op.drop_index(
        "idx_users_verification_token",
        table_name="users",
        postgresql_where=sa.text("email_verification_token IS NOT NULL"),
    )
    op.create_index(
        "idx_users_verification_token",
        "users",
        ["email_verification_token"],
        unique=True,
    )
    op.drop_constraint("fk_characters_faction_id", "characters", type_="foreignkey")
    op.drop_column("author_profiles", "default_image_generation_enabled")
