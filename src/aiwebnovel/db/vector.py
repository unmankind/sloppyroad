"""Vector storage abstraction for story bible embeddings.

Provides a Protocol-based interface with two implementations:
- SQLiteVecStore: sqlite-vec based, for local development (768-dim)
- PGVectorStore: pgvector based, stub for production deployment
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class VectorEntry:
    """A single vector entry for storage."""

    id: str  # bible entry ID as string
    text: str  # the content to embed
    embedding: list[float]  # 768-dim vector
    metadata: dict = field(default_factory=dict)  # novel_id, entry_type, etc.


@dataclass
class SearchResult:
    """A single search result from a vector query."""

    id: str
    text: str
    score: float  # higher = more similar
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class VectorStore(Protocol):
    """Protocol for vector storage backends."""

    async def initialize(self) -> None: ...

    async def validate(self) -> bool: ...

    async def add(self, entries: list[VectorEntry]) -> None: ...

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 20,
        filters: dict | None = None,
    ) -> list[SearchResult]: ...

    async def delete(self, ids: list[str]) -> None: ...

    async def count(self) -> int: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _floats_to_bytes(floats: list[float]) -> bytes:
    """Pack a list of floats into a bytes buffer for sqlite-vec."""
    return struct.pack(f"{len(floats)}f", *floats)


# ---------------------------------------------------------------------------
# SQLiteVecStore
# ---------------------------------------------------------------------------


class SQLiteVecStore:
    """sqlite-vec based vector store for local development.

    Uses sqlite-vec extension with float vectors of configurable dimension.
    The vec0 virtual table handles similarity search; a companion table
    stores metadata (novel_id, entry_type, chapter, importance, etc.).
    """

    def __init__(self, db_path: str, dimensions: int = 768) -> None:
        self.db_path = db_path
        self.dimensions = dimensions

    async def _get_connection(self) -> aiosqlite.Connection:
        """Open a connection with sqlite-vec extension loaded."""
        conn = await aiosqlite.connect(self.db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
        # Load sqlite-vec extension
        await conn.enable_load_extension(True)
        try:
            import sqlite_vec

            # sqlite_vec provides the loadable_path() helper
            ext_path = sqlite_vec.loadable_path()
            await conn.load_extension(ext_path)
        except (ImportError, Exception) as exc:
            # Fallback: try loading by common name
            try:
                await conn.load_extension("vec0")
            except Exception:
                logger.error("sqlite_vec_load_failed", error=str(exc))
                raise
        return conn

    async def validate(self) -> bool:
        """Verify sqlite-vec extension loads and basic operations work."""
        try:
            conn = await self._get_connection()
            await conn.close()
            logger.info("vector_store_validated", db_path=self.db_path)
            return True
        except Exception as exc:
            logger.error("vector_store_validation_failed", error=str(exc))
            return False

    async def initialize(self) -> None:
        """Create vec0 virtual table and metadata table if they don't exist."""
        conn = await self._get_connection()
        try:
            # Vector table for similarity search
            await conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_entries USING vec0(
                    entry_id TEXT PRIMARY KEY,
                    embedding float[{self.dimensions}]
                )
                """
            )
            # Metadata companion table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vec_metadata (
                    entry_id TEXT PRIMARY KEY,
                    text_content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            await conn.commit()
        finally:
            await conn.close()

    async def add(self, entries: list[VectorEntry]) -> None:
        """Insert entries into vec0 table and metadata table. Degrades gracefully."""
        if not entries:
            return

        try:
            conn = await self._get_connection()
            try:
                for entry in entries:
                    emb_bytes = _floats_to_bytes(entry.embedding)
                    await conn.execute(
                        "INSERT OR REPLACE INTO vec_entries(entry_id, embedding) VALUES (?, ?)",
                        (entry.id, emb_bytes),
                    )
                    await conn.execute(
                        "INSERT OR REPLACE INTO vec_metadata"
                        "(entry_id, text_content, metadata_json) VALUES (?, ?, ?)",
                        (entry.id, entry.text, json.dumps(entry.metadata)),
                    )
                await conn.commit()
                logger.debug("vector_entries_added", count=len(entries))
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning(
                "vector_store_degraded", operation="add",
                error=str(exc), entry_count=len(entries),
            )

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 20,
        filters: dict | None = None,
    ) -> list[SearchResult]:
        """Search using KNN via sqlite-vec, then post-filter on metadata.

        Since sqlite-vec uses L2 distance (lower = closer), we convert to a
        similarity score: score = 1 / (1 + distance). Returns [] on failure.
        """
        if not query_embedding:
            return []

        try:
            conn = await self._get_connection()
            try:
                query_bytes = _floats_to_bytes(query_embedding)

                # Fetch more than top_k to allow for post-filtering
                fetch_limit = top_k * 5 if filters else top_k

                cursor = await conn.execute(
                    """
                    SELECT entry_id, distance
                    FROM vec_entries
                    WHERE embedding MATCH ?
                    ORDER BY distance
                    LIMIT ?
                    """,
                    (query_bytes, fetch_limit),
                )
                rows = await cursor.fetchall()

                if not rows:
                    return []

                results: list[SearchResult] = []
                for entry_id, distance in rows:
                    # Fetch metadata
                    meta_cursor = await conn.execute(
                        "SELECT text_content, metadata_json FROM vec_metadata WHERE entry_id = ?",
                        (entry_id,),
                    )
                    meta_row = await meta_cursor.fetchone()
                    if meta_row is None:
                        continue

                    text_content, metadata_json = meta_row
                    metadata = json.loads(metadata_json)

                    # Apply filters
                    if filters:
                        skip = False
                        for key, value in filters.items():
                            if metadata.get(key) != value:
                                skip = True
                                break
                        if skip:
                            continue

                    score = 1.0 / (1.0 + distance)
                    results.append(
                        SearchResult(
                            id=entry_id,
                            text=text_content,
                            score=score,
                            metadata=metadata,
                        )
                    )

                    if len(results) >= top_k:
                        break

                return results
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning(
                "vector_store_degraded", operation="search",
                error=str(exc), top_k=top_k,
            )
            return []

    async def delete(self, ids: list[str]) -> None:
        """Remove entries from both tables. Degrades gracefully."""
        if not ids:
            return

        try:
            conn = await self._get_connection()
            try:
                placeholders = ",".join("?" for _ in ids)
                await conn.execute(
                    f"DELETE FROM vec_entries WHERE entry_id IN ({placeholders})",
                    ids,
                )
                await conn.execute(
                    f"DELETE FROM vec_metadata WHERE entry_id IN ({placeholders})",
                    ids,
                )
                await conn.commit()
                logger.debug("vector_entries_deleted", count=len(ids))
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning(
                "vector_store_degraded", operation="delete",
                error=str(exc), id_count=len(ids),
            )

    async def count(self) -> int:
        """Return total number of entries. Returns 0 on failure."""
        try:
            conn = await self._get_connection()
            try:
                cursor = await conn.execute("SELECT COUNT(*) FROM vec_metadata")
                row = await cursor.fetchone()
                return row[0] if row else 0
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning(
                "vector_store_degraded", operation="count",
                error=str(exc),
            )
            return 0


# ---------------------------------------------------------------------------
# PGVectorStore
# ---------------------------------------------------------------------------


def _sqlalchemy_url_to_dsn(url: str) -> str:
    """Convert SQLAlchemy async URL to plain DSN for asyncpg."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


class PGVectorStore:
    """pgvector based vector store for production PostgreSQL.

    Uses asyncpg connection pool with pgvector extension for
    768-dimensional vector similarity search via L2 distance.
    """

    def __init__(self, dsn: str, dimensions: int = 768) -> None:
        self.dsn = dsn
        self.dimensions = dimensions
        self._pool: Any = None  # asyncpg.Pool, typed as Any to avoid import at module level

    async def initialize(self) -> None:
        """Create connection pool and vector table."""
        import asyncpg
        from pgvector.asyncpg import register_vector

        async def _init_conn(conn: Any) -> None:
            await register_vector(conn)

        self._pool = await asyncpg.create_pool(
            self.dsn, min_size=1, max_size=3, init=_init_conn,
        )

        async with self._pool.acquire() as conn:
            await conn.execute(
                "CREATE EXTENSION IF NOT EXISTS vector"
            )
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS vec_store_entries (
                    entry_id TEXT PRIMARY KEY,
                    text_content TEXT NOT NULL,
                    embedding vector({self.dimensions}),
                    metadata_json JSONB NOT NULL DEFAULT '{{}}'
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_vec_store_embedding_hnsw
                ON vec_store_entries
                USING hnsw (embedding vector_l2_ops)
                WITH (m = 16, ef_construction = 64)
            """)

        logger.info(
            "pgvector_store_initialized",
            dimensions=self.dimensions,
        )

    async def validate(self) -> bool:
        """Verify connection pool works."""
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as exc:
            logger.error("pgvector_validation_failed", error=str(exc))
            return False

    async def add(self, entries: list[VectorEntry]) -> None:
        """Insert or upsert entries. Degrades gracefully on failure."""
        if not entries or self._pool is None:
            return

        try:
            import numpy as np

            async with self._pool.acquire() as conn:
                for entry in entries:
                    embedding = np.array(entry.embedding, dtype=np.float32)
                    await conn.execute(
                        """
                        INSERT INTO vec_store_entries
                            (entry_id, text_content, embedding, metadata_json)
                        VALUES ($1, $2, $3, $4::jsonb)
                        ON CONFLICT (entry_id) DO UPDATE SET
                            text_content = EXCLUDED.text_content,
                            embedding = EXCLUDED.embedding,
                            metadata_json = EXCLUDED.metadata_json
                        """,
                        entry.id,
                        entry.text,
                        embedding,
                        json.dumps(entry.metadata),
                    )
            logger.debug("pgvector_entries_added", count=len(entries))
        except Exception as exc:
            logger.warning(
                "vector_store_degraded", operation="add",
                error=str(exc), entry_count=len(entries),
            )

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 20,
        filters: dict | None = None,
    ) -> list[SearchResult]:
        """KNN search via L2 distance with post-filtering. Returns [] on failure."""
        if not query_embedding or self._pool is None:
            return []

        try:
            import numpy as np

            fetch_limit = top_k * 5 if filters else top_k
            query_vec = np.array(query_embedding, dtype=np.float32)

            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT entry_id, text_content, metadata_json,
                           embedding <-> $1 AS distance
                    FROM vec_store_entries
                    ORDER BY embedding <-> $1
                    LIMIT $2
                    """,
                    query_vec,
                    fetch_limit,
                )

            results: list[SearchResult] = []
            for row in rows:
                metadata = (
                    json.loads(row["metadata_json"])
                    if isinstance(row["metadata_json"], str)
                    else dict(row["metadata_json"])
                )

                if filters:
                    skip = False
                    for key, value in filters.items():
                        if metadata.get(key) != value:
                            skip = True
                            break
                    if skip:
                        continue

                score = 1.0 / (1.0 + float(row["distance"]))
                results.append(SearchResult(
                    id=row["entry_id"],
                    text=row["text_content"],
                    score=score,
                    metadata=metadata,
                ))

                if len(results) >= top_k:
                    break

            return results
        except Exception as exc:
            logger.warning(
                "vector_store_degraded", operation="search",
                error=str(exc), top_k=top_k,
            )
            return []

    async def delete(self, ids: list[str]) -> None:
        """Remove entries by ID. Degrades gracefully on failure."""
        if not ids or self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM vec_store_entries WHERE entry_id = ANY($1)",
                    ids,
                )
            logger.debug("pgvector_entries_deleted", count=len(ids))
        except Exception as exc:
            logger.warning(
                "vector_store_degraded", operation="delete",
                error=str(exc), id_count=len(ids),
            )

    async def count(self) -> int:
        """Return total entries. Returns 0 on failure."""
        if self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM vec_store_entries"
                )
        except Exception as exc:
            logger.warning(
                "vector_store_degraded", operation="count",
                error=str(exc),
            )
            return 0

    async def close(self) -> None:
        """Close the asyncpg connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.debug("pgvector_pool_closed")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


async def create_vector_store(
    settings: Any,
) -> SQLiteVecStore | PGVectorStore | None:
    """Auto-select and initialize the appropriate vector store backend.

    Returns None if initialization fails (graceful degradation).
    """
    db_url: str = settings.database_url

    if db_url.startswith("sqlite"):
        store = SQLiteVecStore(
            settings.vector_db_path, settings.embedding_dimensions,
        )
    elif "postgresql" in db_url or "postgres" in db_url:
        dsn = _sqlalchemy_url_to_dsn(db_url)
        store = PGVectorStore(dsn, settings.embedding_dimensions)
    else:
        logger.warning("vector_store_unsupported_db", database_url=db_url)
        return None

    try:
        await store.initialize()
        if await store.validate():
            logger.info(
                "vector_store_ready",
                backend=type(store).__name__,
            )
            return store
        logger.warning(
            "vector_store_validation_failed",
            backend=type(store).__name__,
        )
        return None
    except Exception as exc:
        logger.warning(
            "vector_store_init_failed",
            backend=type(store).__name__,
            error=str(exc),
        )
        return None
