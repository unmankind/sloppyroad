"""Add feedback column to art_generation_queue for image regeneration.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-16
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "art_generation_queue",
        sa.Column("feedback", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("art_generation_queue", "feedback")
