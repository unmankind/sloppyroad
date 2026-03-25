"""Tests for VectorStore abstraction — SQLiteVecStore and PGVectorStore."""

from __future__ import annotations

import pytest

from aiwebnovel.db.vector import (
    PGVectorStore,
    SQLiteVecStore,
    VectorEntry,
    create_vector_store,
)

# ---------------------------------------------------------------------------
# Try to detect sqlite-vec availability
# ---------------------------------------------------------------------------

_SQLITE_VEC_AVAILABLE = True
try:
    import sqlite3

    import sqlite_vec

    _db = sqlite3.connect(":memory:")
    _db.enable_load_extension(True)
    sqlite_vec.load(_db)
    _db.close()
except Exception:
    _SQLITE_VEC_AVAILABLE = False

skip_no_sqlite_vec = pytest.mark.skipif(
    not _SQLITE_VEC_AVAILABLE,
    reason="sqlite-vec extension not available",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    entry_id: str,
    text: str,
    embedding: list[float] | None = None,
    novel_id: int = 1,
    entry_type: str = "character_fact",
    chapter: int = 1,
    importance: int = 3,
) -> VectorEntry:
    if embedding is None:
        # Create a simple deterministic 768-dim vector
        base = float(int(entry_id) if entry_id.isdigit() else hash(entry_id) % 100)
        embedding = [base * 0.01 + i * 0.001 for i in range(768)]
    return VectorEntry(
        id=entry_id,
        text=text,
        embedding=embedding,
        metadata={
            "novel_id": novel_id,
            "entry_type": entry_type,
            "chapter": chapter,
            "importance": importance,
            "entity_ids": [],
        },
    )


# ---------------------------------------------------------------------------
# Tests — SQLiteVecStore
# ---------------------------------------------------------------------------


@skip_no_sqlite_vec
class TestSQLiteVecStore:
    """Tests for the sqlite-vec based vector store."""

    @pytest.fixture()
    async def store(self, tmp_path):
        db_path = str(tmp_path / "test_vec.db")
        s = SQLiteVecStore(db_path=db_path, dimensions=768)
        await s.initialize()
        return s

    async def test_initialize_creates_tables(self, store):
        """initialize() should create the vec0 virtual table and metadata table."""
        count = await store.count()
        assert count == 0

    async def test_add_entries(self, store):
        """add() should insert entries and increase count."""
        entries = [
            _make_entry("1", "Kai is a fire mage"),
            _make_entry("2", "Sera is an ice scholar"),
        ]
        await store.add(entries)
        assert await store.count() == 2

    async def test_search_returns_results(self, store):
        """search() should return results sorted by relevance."""
        entries = [
            _make_entry("1", "Kai is a fire mage"),
            _make_entry("2", "Sera is an ice scholar"),
            _make_entry("3", "The forest is dark and ancient"),
        ]
        await store.add(entries)

        # Query with embedding similar to entry "1"
        query_embedding = _make_entry("1", "").embedding
        results = await store.search(query_embedding, top_k=3)

        assert len(results) > 0
        # The most similar result should be entry "1" (identical embedding)
        assert results[0].id == "1"

    async def test_search_respects_top_k(self, store):
        """search() should return at most top_k results."""
        entries = [_make_entry(str(i), f"Entry {i}") for i in range(10)]
        await store.add(entries)

        results = await store.search(entries[0].embedding, top_k=3)
        assert len(results) <= 3

    async def test_search_with_novel_id_filter(self, store):
        """search() with novel_id filter should only return matching entries."""
        entries = [
            _make_entry("1", "From novel 1", novel_id=1),
            _make_entry("2", "From novel 2", novel_id=2),
            _make_entry("3", "Also novel 1", novel_id=1),
        ]
        await store.add(entries)

        query_emb = entries[0].embedding
        results = await store.search(query_emb, top_k=10, filters={"novel_id": 1})

        ids = {r.id for r in results}
        assert "2" not in ids
        assert len(results) <= 2  # only novel_id=1 entries

    async def test_search_with_entry_type_filter(self, store):
        """search() with entry_type filter should only return matching entries."""
        entries = [
            _make_entry("1", "A fact", entry_type="character_fact"),
            _make_entry("2", "A relation", entry_type="relationship"),
            _make_entry("3", "Another fact", entry_type="character_fact"),
        ]
        await store.add(entries)

        query_emb = entries[0].embedding
        results = await store.search(
            query_emb, top_k=10, filters={"entry_type": "character_fact"}
        )

        for r in results:
            assert r.metadata["entry_type"] == "character_fact"

    async def test_delete_removes_entries(self, store):
        """delete() should remove entries from both tables."""
        entries = [
            _make_entry("1", "Entry one"),
            _make_entry("2", "Entry two"),
            _make_entry("3", "Entry three"),
        ]
        await store.add(entries)
        assert await store.count() == 3

        await store.delete(["1", "2"])
        assert await store.count() == 1

    async def test_count_empty_store(self, store):
        """count() on empty store should return 0."""
        assert await store.count() == 0

    async def test_search_empty_store(self, store):
        """search() on empty store should return empty list."""
        query = [0.0] * 768
        results = await store.search(query, top_k=5)
        assert results == []

    async def test_search_score_is_positive(self, store):
        """search results should have a positive score (similarity metric)."""
        entries = [_make_entry("1", "Test entry")]
        await store.add(entries)

        results = await store.search(entries[0].embedding, top_k=1)
        assert len(results) == 1
        assert results[0].score >= 0.0


# ---------------------------------------------------------------------------
# Tests — PGVectorStore
# ---------------------------------------------------------------------------


class TestPGVectorStore:
    """PGVectorStore requires a real PostgreSQL+pgvector connection.

    These tests verify construction and method existence without a live DB.
    """

    def test_constructor(self):
        store = PGVectorStore("postgresql://localhost/test", dimensions=768)
        assert store.dsn == "postgresql://localhost/test"
        assert store.dimensions == 768
        assert store._pool is None

    async def test_validate_returns_false_without_pool(self):
        store = PGVectorStore("postgresql://localhost/test")
        assert await store.validate() is False

    async def test_add_noop_without_pool(self):
        store = PGVectorStore("postgresql://localhost/test")
        # Should not raise — graceful when pool is None
        await store.add([])

    async def test_search_empty_without_pool(self):
        store = PGVectorStore("postgresql://localhost/test")
        results = await store.search([0.1] * 768, top_k=5)
        assert results == []

    async def test_count_zero_without_pool(self):
        store = PGVectorStore("postgresql://localhost/test")
        assert await store.count() == 0


class TestCreateVectorStore:
    """Test the factory function."""

    async def test_sqlite_backend(self, tmp_path):
        """Factory creates SQLiteVecStore for sqlite URLs."""
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.database_url = "sqlite+aiosqlite:///test.db"
        settings.vector_db_path = str(tmp_path / "vec.db")
        settings.embedding_dimensions = 768

        store = await create_vector_store(settings)
        if _SQLITE_VEC_AVAILABLE:
            assert isinstance(store, SQLiteVecStore)
        # If sqlite-vec not available, returns None (graceful)

    async def test_unsupported_backend(self):
        """Factory returns None for unsupported DB URLs."""
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.database_url = "mysql://localhost/test"

        store = await create_vector_store(settings)
        assert store is None

    async def test_postgres_without_server(self):
        """Factory returns None when PG server is unavailable."""
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://localhost/noexist"
        settings.embedding_dimensions = 768

        store = await create_vector_store(settings)
        assert store is None  # Connection fails gracefully
