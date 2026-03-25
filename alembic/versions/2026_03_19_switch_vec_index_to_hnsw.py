"""Switch vec_store_entries index from IVFFlat to HNSW.

IVFFlat with lists=100 requires ~10k rows for good recall.
HNSW provides consistent ~95% recall regardless of row count,
which is critical for early novels with <1000 bible entries.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-19
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_vec_store_embedding"
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_vec_store_embedding_hnsw
        ON vec_store_entries
        USING hnsw (embedding vector_l2_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_vec_store_embedding_hnsw"
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_vec_store_embedding
        ON vec_store_entries
        USING ivfflat (embedding vector_l2_ops)
        WITH (lists = 100)
    """)
