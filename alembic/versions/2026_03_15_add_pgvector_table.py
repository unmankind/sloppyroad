"""Add pgvector vec_store_entries table for story bible embeddings.

Revision ID: a1b2c3d4e5f6
Revises: 8fcaebd46945
Create Date: 2026-03-15
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "8fcaebd46945"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (defensive — also in Docker init script)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE IF NOT EXISTS vec_store_entries (
            entry_id TEXT PRIMARY KEY,
            text_content TEXT NOT NULL,
            embedding vector(768),
            metadata_json JSONB NOT NULL DEFAULT '{}'
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_vec_store_embedding
        ON vec_store_entries
        USING ivfflat (embedding vector_l2_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vec_store_entries")
