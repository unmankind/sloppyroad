"""Add sex, pronouns, physical_traits columns to characters table.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters", sa.Column("sex", sa.String(20), nullable=True),
    )
    op.add_column(
        "characters", sa.Column("pronouns", sa.String(20), nullable=True),
    )
    op.add_column(
        "characters",
        sa.Column("physical_traits", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("characters", "physical_traits")
    op.drop_column("characters", "pronouns")
    op.drop_column("characters", "sex")
