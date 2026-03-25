"""Tests for KnowledgeTracker — character knowledge tracking."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    Character,
    CharacterKnowledge,
    Novel,
    StoryBibleEntry,
    User,
)
from aiwebnovel.perspective.knowledge import KnowledgeTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession) -> User:
    user = User(
        email="knowledge@test.com",
        hashed_password="hashed",
        role="author",
        is_anonymous=False,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_novel(session: AsyncSession, author_id: int) -> Novel:
    novel = Novel(author_id=author_id, title="Knowledge Test Novel")
    session.add(novel)
    await session.flush()
    return novel


async def _create_character(
    session: AsyncSession, novel_id: int, name: str = "Kai"
) -> Character:
    char = Character(
        novel_id=novel_id,
        name=name,
        role="protagonist",
        description=f"{name} is a test character.",
    )
    session.add(char)
    await session.flush()
    return char


async def _create_bible_entry(
    session: AsyncSession,
    novel_id: int,
    content: str,
    entry_type: str = "character_fact",
) -> StoryBibleEntry:
    entry = StoryBibleEntry(
        novel_id=novel_id,
        entry_type=entry_type,
        content=content,
        source_chapter=1,
        entity_ids=[],
        tags=[entry_type],
        importance=3,
        last_relevant_chapter=1,
    )
    session.add(entry)
    await session.flush()
    return entry


# ---------------------------------------------------------------------------
# Tests — record_knowledge
# ---------------------------------------------------------------------------


class TestRecordKnowledge:
    """Test that record_knowledge creates CharacterKnowledge entries."""

    @pytest.fixture()
    def tracker(self):
        return KnowledgeTracker()

    @pytest.fixture()
    async def setup(self, db_session):
        user = await _create_user(db_session)
        novel = await _create_novel(db_session, user.id)
        kai = await _create_character(db_session, novel.id, "Kai")
        entry = await _create_bible_entry(db_session, novel.id, "A secret power exists.")
        await db_session.flush()
        return kai, entry

    async def test_creates_knowledge_entry(self, db_session, tracker, setup):
        """record_knowledge should create a CharacterKnowledge row."""
        kai, entry = setup

        knowledge = await tracker.record_knowledge(
            session=db_session,
            character_id=kai.id,
            bible_entry_id=entry.id,
            chapter_number=3,
            source="witnessed",
        )

        assert knowledge.id is not None
        assert knowledge.character_id == kai.id
        assert knowledge.bible_entry_id == entry.id
        assert knowledge.learned_at_chapter == 3
        assert knowledge.source == "witnessed"

    async def test_knowledge_stored_in_db(self, db_session, tracker, setup):
        """Knowledge should be queryable from the database."""
        kai, entry = setup

        await tracker.record_knowledge(
            session=db_session,
            character_id=kai.id,
            bible_entry_id=entry.id,
            chapter_number=3,
            source="witnessed",
        )
        await db_session.flush()

        result = await db_session.execute(
            select(CharacterKnowledge).where(
                CharacterKnowledge.character_id == kai.id
            )
        )
        records = result.scalars().all()
        assert len(records) == 1

    async def test_default_source_witnessed(self, db_session, tracker, setup):
        """Default source should be 'witnessed'."""
        kai, entry = setup

        knowledge = await tracker.record_knowledge(
            session=db_session,
            character_id=kai.id,
            bible_entry_id=entry.id,
            chapter_number=1,
        )

        assert knowledge.source == "witnessed"

    async def test_misconception_stored(self, db_session, tracker, setup):
        """Misconception field should be stored when provided."""
        kai, entry = setup

        knowledge = await tracker.record_knowledge(
            session=db_session,
            character_id=kai.id,
            bible_entry_id=entry.id,
            chapter_number=5,
            source="told",
            misconception="Kai believes the power comes from the gods, not the earth.",
        )

        assert knowledge.misconception == (
            "Kai believes the power comes from the gods,"
            " not the earth."
        )

    async def test_different_sources(self, db_session, tracker):
        """Different source types should be accepted."""
        user = await _create_user(db_session)
        novel = await _create_novel(db_session, user.id)
        kai = await _create_character(db_session, novel.id, "Kai")

        sources = ["witnessed", "told", "deduced", "assumed"]
        for i, source in enumerate(sources):
            entry = await _create_bible_entry(
                db_session, novel.id, f"Fact {i}"
            )
            knowledge = await tracker.record_knowledge(
                session=db_session,
                character_id=kai.id,
                bible_entry_id=entry.id,
                chapter_number=i + 1,
                source=source,
            )
            assert knowledge.source == source

    async def test_duplicate_knowledge_updates(self, db_session, tracker, setup):
        """Recording knowledge for same char + entry should update, not duplicate."""
        kai, entry = setup

        await tracker.record_knowledge(
            session=db_session,
            character_id=kai.id,
            bible_entry_id=entry.id,
            chapter_number=3,
            source="witnessed",
        )
        await db_session.flush()

        await tracker.record_knowledge(
            session=db_session,
            character_id=kai.id,
            bible_entry_id=entry.id,
            chapter_number=5,
            source="told",
        )
        await db_session.flush()

        # Should be the same record, updated
        result = await db_session.execute(
            select(CharacterKnowledge).where(
                CharacterKnowledge.character_id == kai.id,
                CharacterKnowledge.bible_entry_id == entry.id,
            )
        )
        records = result.scalars().all()
        assert len(records) == 1
        # Should reflect the latest source
        assert records[0].source == "told"


# ---------------------------------------------------------------------------
# Tests — character_knows
# ---------------------------------------------------------------------------


class TestCharacterKnows:
    """Test character_knows boolean check."""

    @pytest.fixture()
    def tracker(self):
        return KnowledgeTracker()

    @pytest.fixture()
    async def setup(self, db_session):
        user = await _create_user(db_session)
        novel = await _create_novel(db_session, user.id)
        kai = await _create_character(db_session, novel.id, "Kai")
        entry_known = await _create_bible_entry(db_session, novel.id, "Known fact")
        entry_unknown = await _create_bible_entry(db_session, novel.id, "Unknown fact")
        await db_session.flush()
        return kai, entry_known, entry_unknown

    async def test_knows_returns_true(self, db_session, tracker, setup):
        """character_knows returns True for recorded knowledge."""
        kai, entry_known, _ = setup

        await tracker.record_knowledge(
            session=db_session,
            character_id=kai.id,
            bible_entry_id=entry_known.id,
            chapter_number=1,
        )
        await db_session.flush()

        assert await tracker.character_knows(db_session, kai.id, entry_known.id) is True

    async def test_knows_returns_false(self, db_session, tracker, setup):
        """character_knows returns False for unrecorded knowledge."""
        kai, _, entry_unknown = setup

        assert await tracker.character_knows(db_session, kai.id, entry_unknown.id) is False


# ---------------------------------------------------------------------------
# Tests — get_character_knowledge
# ---------------------------------------------------------------------------


class TestGetCharacterKnowledge:
    """Test querying character knowledge with optional type filter."""

    @pytest.fixture()
    def tracker(self):
        return KnowledgeTracker()

    async def test_returns_all_knowledge(self, db_session, tracker):
        """get_character_knowledge without filter returns all entries."""
        user = await _create_user(db_session)
        novel = await _create_novel(db_session, user.id)
        kai = await _create_character(db_session, novel.id, "Kai")

        e1 = await _create_bible_entry(
            db_session, novel.id, "Fact 1", entry_type="character_fact"
        )
        e2 = await _create_bible_entry(
            db_session, novel.id, "Relationship 1", entry_type="relationship"
        )

        await tracker.record_knowledge(db_session, kai.id, e1.id, 1)
        await tracker.record_knowledge(db_session, kai.id, e2.id, 2)
        await db_session.flush()

        knowledge = await tracker.get_character_knowledge(db_session, kai.id)
        assert len(knowledge) == 2

    async def test_filters_by_entry_type(self, db_session, tracker):
        """get_character_knowledge with type filter returns only matching entries."""
        user = await _create_user(db_session)
        novel = await _create_novel(db_session, user.id)
        kai = await _create_character(db_session, novel.id, "Kai")

        e1 = await _create_bible_entry(
            db_session, novel.id, "Fact 1", entry_type="character_fact"
        )
        e2 = await _create_bible_entry(
            db_session, novel.id, "Relationship 1", entry_type="relationship"
        )
        e3 = await _create_bible_entry(
            db_session, novel.id, "Fact 2", entry_type="character_fact"
        )

        await tracker.record_knowledge(db_session, kai.id, e1.id, 1)
        await tracker.record_knowledge(db_session, kai.id, e2.id, 2)
        await tracker.record_knowledge(db_session, kai.id, e3.id, 3)
        await db_session.flush()

        facts = await tracker.get_character_knowledge(
            db_session, kai.id, entry_type="character_fact"
        )
        assert len(facts) == 2

        rels = await tracker.get_character_knowledge(
            db_session, kai.id, entry_type="relationship"
        )
        assert len(rels) == 1

    async def test_empty_for_unknown_character(self, db_session, tracker):
        """get_character_knowledge for non-existent character returns empty list."""
        knowledge = await tracker.get_character_knowledge(db_session, 9999)
        assert knowledge == []
