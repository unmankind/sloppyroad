"""Tests for StoryBibleExtractor — bible entry extraction and supersession detection."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    Character,
    Novel,
    StoryBibleEntry,
    User,
)
from aiwebnovel.llm.parsers import BibleEntryExtract
from aiwebnovel.summarization.story_bible import StoryBibleExtractor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession) -> User:
    user = User(
        email="bible@test.com",
        hashed_password="hashed",
        role="author",
        is_anonymous=False,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_novel(session: AsyncSession, author_id: int) -> Novel:
    novel = Novel(author_id=author_id, title="Bible Test Novel")
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
        description="A young mage",
    )
    session.add(char)
    await session.flush()
    return char


def _make_bible_extracts() -> list[BibleEntryExtract]:
    return [
        BibleEntryExtract(
            entry_type="character_fact",
            content="Kai discovered he has an affinity for fire magic.",
            entity_types=["character"],
            entity_names=["Kai"],
            is_public_knowledge=True,
            supersedes_description=None,
        ),
        BibleEntryExtract(
            entry_type="relationship",
            content="Kai and Sera formed a reluctant alliance after the cave incident.",
            entity_types=["character", "character"],
            entity_names=["Kai", "Sera"],
            is_public_knowledge=True,
            supersedes_description=None,
        ),
        BibleEntryExtract(
            entry_type="foreshadowing",
            content="The ancient seal beneath the library began to crack.",
            entity_types=["location"],
            entity_names=["Great Library"],
            is_public_knowledge=False,
            supersedes_description=None,
        ),
    ]


# ---------------------------------------------------------------------------
# Tests — extract_entries
# ---------------------------------------------------------------------------


class TestExtractEntries:
    """Test that extract_entries creates StoryBibleEntry objects from analysis data."""

    @pytest.fixture()
    async def extractor(self, test_settings):
        return StoryBibleExtractor(llm=None, settings=test_settings)

    @pytest.fixture()
    async def novel_with_chars(self, db_session):
        user = await _create_user(db_session)
        novel = await _create_novel(db_session, user.id)
        kai = await _create_character(db_session, novel.id, "Kai")
        sera = await _create_character(db_session, novel.id, "Sera")
        await db_session.flush()
        return novel, {"Kai": kai, "Sera": sera}

    async def test_creates_entries_from_analysis(
        self, db_session, extractor, novel_with_chars
    ):
        """extract_entries should create StoryBibleEntry objects in the DB."""
        novel, chars = novel_with_chars
        extracts = _make_bible_extracts()

        entries = await extractor.extract_entries(
            session=db_session,
            novel_id=novel.id,
            chapter_number=3,
            chapter_text="Dummy chapter text.",
            analysis_entries=extracts,
        )

        assert len(entries) == 3
        for entry in entries:
            assert entry.id is not None  # persisted to DB

    async def test_entry_types_match(
        self, db_session, extractor, novel_with_chars
    ):
        """Each entry should have the correct entry_type from the extract."""
        novel, _ = novel_with_chars
        extracts = _make_bible_extracts()

        entries = await extractor.extract_entries(
            session=db_session,
            novel_id=novel.id,
            chapter_number=3,
            chapter_text="Dummy chapter text.",
            analysis_entries=extracts,
        )

        types = [e.entry_type for e in entries]
        assert "character_fact" in types
        assert "relationship" in types
        assert "foreshadowing" in types

    async def test_entry_content_preserved(
        self, db_session, extractor, novel_with_chars
    ):
        """Content text should be preserved exactly from the extract."""
        novel, _ = novel_with_chars
        extracts = _make_bible_extracts()[:1]

        entries = await extractor.extract_entries(
            session=db_session,
            novel_id=novel.id,
            chapter_number=3,
            chapter_text="Dummy chapter text.",
            analysis_entries=extracts,
        )

        assert entries[0].content == "Kai discovered he has an affinity for fire magic."

    async def test_source_chapter_set(
        self, db_session, extractor, novel_with_chars
    ):
        """source_chapter should be set to the provided chapter_number."""
        novel, _ = novel_with_chars
        extracts = _make_bible_extracts()[:1]

        entries = await extractor.extract_entries(
            session=db_session,
            novel_id=novel.id,
            chapter_number=7,
            chapter_text="Chapter text.",
            analysis_entries=extracts,
        )

        assert entries[0].source_chapter == 7
        assert entries[0].last_relevant_chapter == 7

    async def test_is_public_knowledge_set(
        self, db_session, extractor, novel_with_chars
    ):
        """is_public_knowledge should be propagated from extract."""
        novel, _ = novel_with_chars
        extracts = _make_bible_extracts()

        entries = await extractor.extract_entries(
            session=db_session,
            novel_id=novel.id,
            chapter_number=3,
            chapter_text="Dummy chapter text.",
            analysis_entries=extracts,
        )

        # First two are public, third is not
        public_entries = [e for e in entries if e.is_public_knowledge]
        private_entries = [e for e in entries if not e.is_public_knowledge]
        assert len(public_entries) == 2
        assert len(private_entries) == 1

    async def test_entries_stored_in_db(
        self, db_session, extractor, novel_with_chars
    ):
        """Entries should be queryable from the database after extraction."""
        novel, _ = novel_with_chars
        extracts = _make_bible_extracts()

        await extractor.extract_entries(
            session=db_session,
            novel_id=novel.id,
            chapter_number=3,
            chapter_text="Dummy chapter text.",
            analysis_entries=extracts,
        )
        await db_session.flush()

        result = await db_session.execute(
            select(StoryBibleEntry).where(StoryBibleEntry.novel_id == novel.id)
        )
        db_entries = result.scalars().all()
        assert len(db_entries) == 3

    async def test_importance_default(
        self, db_session, extractor, novel_with_chars
    ):
        """Importance should default to 3."""
        novel, _ = novel_with_chars
        extracts = _make_bible_extracts()[:1]

        entries = await extractor.extract_entries(
            session=db_session,
            novel_id=novel.id,
            chapter_number=3,
            chapter_text="Dummy chapter text.",
            analysis_entries=extracts,
        )

        assert entries[0].importance == 3

    async def test_empty_extracts_returns_empty(
        self, db_session, extractor, novel_with_chars
    ):
        """No extracts should produce no entries."""
        novel, _ = novel_with_chars

        entries = await extractor.extract_entries(
            session=db_session,
            novel_id=novel.id,
            chapter_number=3,
            chapter_text="Dummy chapter text.",
            analysis_entries=[],
        )

        assert entries == []


# ---------------------------------------------------------------------------
# Tests — detect_supersessions
# ---------------------------------------------------------------------------


class TestDetectSupersessions:
    """Test that detect_supersessions finds and marks superseded entries."""

    @pytest.fixture()
    async def extractor(self, test_settings):
        return StoryBibleExtractor(llm=None, settings=test_settings)

    @pytest.fixture()
    async def novel_setup(self, db_session):
        user = await _create_user(db_session)
        novel = await _create_novel(db_session, user.id)
        kai = await _create_character(db_session, novel.id, "Kai")
        await db_session.flush()
        return novel, kai

    async def test_supersession_detected(
        self, db_session, extractor, novel_setup
    ):
        """A new entry with same entity_ids + type should supersede old entry."""
        novel, kai = novel_setup

        # Create old entry
        old_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="character_fact",
            content="Kai is a novice fire mage.",
            source_chapter=1,
            entity_ids=[kai.id],
            tags=["character"],
            importance=3,
            last_relevant_chapter=1,
        )
        session = db_session
        session.add(old_entry)
        await session.flush()

        # Create new entry
        new_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="character_fact",
            content="Kai has mastered basic fire spells after intensive training.",
            source_chapter=5,
            entity_ids=[kai.id],
            tags=["character"],
            importance=3,
            last_relevant_chapter=5,
        )
        session.add(new_entry)
        await session.flush()

        pairs = await extractor.detect_supersessions(
            session=session,
            novel_id=novel.id,
            new_entries=[new_entry],
        )

        assert len(pairs) == 1
        assert pairs[0][0].id == new_entry.id
        assert pairs[0][1] == old_entry.id

    async def test_old_entry_marked_superseded(
        self, db_session, extractor, novel_setup
    ):
        """After supersession detection, old entry should have is_superseded=True."""
        novel, kai = novel_setup

        old_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="character_fact",
            content="Kai is a novice fire mage.",
            source_chapter=1,
            entity_ids=[kai.id],
            tags=["character"],
            importance=3,
            last_relevant_chapter=1,
        )
        db_session.add(old_entry)
        await db_session.flush()

        new_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="character_fact",
            content="Kai has mastered basic fire spells.",
            source_chapter=5,
            entity_ids=[kai.id],
            tags=["character"],
            importance=3,
            last_relevant_chapter=5,
        )
        db_session.add(new_entry)
        await db_session.flush()

        await extractor.detect_supersessions(
            session=db_session,
            novel_id=novel.id,
            new_entries=[new_entry],
        )

        await db_session.refresh(old_entry)
        assert old_entry.is_superseded is True
        assert old_entry.superseded_by_id == new_entry.id

    async def test_no_match_no_supersession(
        self, db_session, extractor, novel_setup
    ):
        """Entries without matching entity_ids + type should not be superseded."""
        novel, kai = novel_setup

        old_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="world_rule",
            content="Magic requires a catalyst stone.",
            source_chapter=1,
            entity_ids=[],
            tags=["world"],
            importance=4,
            last_relevant_chapter=1,
        )
        db_session.add(old_entry)
        await db_session.flush()

        new_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="character_fact",
            content="Kai has mastered basic fire spells.",
            source_chapter=5,
            entity_ids=[kai.id],
            tags=["character"],
            importance=3,
            last_relevant_chapter=5,
        )
        db_session.add(new_entry)
        await db_session.flush()

        pairs = await extractor.detect_supersessions(
            session=db_session,
            novel_id=novel.id,
            new_entries=[new_entry],
        )

        assert len(pairs) == 0

    async def test_different_type_no_supersession(
        self, db_session, extractor, novel_setup
    ):
        """Same entity_ids but different entry_type should NOT supersede."""
        novel, kai = novel_setup

        old_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="relationship",
            content="Kai is allied with the fire guild.",
            source_chapter=1,
            entity_ids=[kai.id],
            tags=["character"],
            importance=3,
            last_relevant_chapter=1,
        )
        db_session.add(old_entry)
        await db_session.flush()

        new_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="character_fact",
            content="Kai has mastered basic fire spells.",
            source_chapter=5,
            entity_ids=[kai.id],
            tags=["character"],
            importance=3,
            last_relevant_chapter=5,
        )
        db_session.add(new_entry)
        await db_session.flush()

        pairs = await extractor.detect_supersessions(
            session=db_session,
            novel_id=novel.id,
            new_entries=[new_entry],
        )

        assert len(pairs) == 0

    async def test_already_superseded_not_matched(
        self, db_session, extractor, novel_setup
    ):
        """Entries already superseded should not be matched again."""
        novel, kai = novel_setup

        old_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="character_fact",
            content="Kai is a novice.",
            source_chapter=1,
            entity_ids=[kai.id],
            tags=["character"],
            importance=3,
            is_superseded=True,
            last_relevant_chapter=1,
        )
        db_session.add(old_entry)
        await db_session.flush()

        new_entry = StoryBibleEntry(
            novel_id=novel.id,
            entry_type="character_fact",
            content="Kai is an expert.",
            source_chapter=10,
            entity_ids=[kai.id],
            tags=["character"],
            importance=3,
            last_relevant_chapter=10,
        )
        db_session.add(new_entry)
        await db_session.flush()

        pairs = await extractor.detect_supersessions(
            session=db_session,
            novel_id=novel.id,
            new_entries=[new_entry],
        )

        assert len(pairs) == 0
