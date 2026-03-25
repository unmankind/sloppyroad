"""Tests for the Chekhov gun system."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.chekhov.detector import ChekhovDetector
from aiwebnovel.chekhov.injector import ChekhovInjector
from aiwebnovel.chekhov.tracker import ChekhovTracker
from aiwebnovel.db.models import (
    AuthorProfile,
    ChekhovGun,
    Novel,
    StoryBibleEntry,
    User,
)


async def _seed(session: AsyncSession) -> int:
    user = User(id=1, email="t@t.com", role="author", is_anonymous=False, hashed_password="x")
    session.add(user)
    await session.flush()
    profile = AuthorProfile(user_id=1, api_budget_cents=10000, api_spent_cents=0)
    session.add(profile)
    novel = Novel(author_id=1, title="Test", status="writing")
    session.add(novel)
    await session.flush()
    return novel.id


class TestChekhovDetector:
    """Test gun detection from bible entries."""

    @pytest.mark.asyncio
    async def test_detects_guns_from_foreshadowing(self, db_engine):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)

            # Add foreshadowing bible entries
            entry1 = StoryBibleEntry(
                novel_id=novel_id,
                entry_type="foreshadowing",
                content="A mysterious sword was mentioned in the background",
                source_chapter=1,
                importance=3,
            )
            entry2 = StoryBibleEntry(
                novel_id=novel_id,
                entry_type="mystery",
                content="Strange lights appear at midnight",
                source_chapter=2,
                importance=4,
            )
            entry3 = StoryBibleEntry(
                novel_id=novel_id,
                entry_type="character_fact",
                content="Hero has blue eyes",
                source_chapter=1,
                importance=2,
            )
            session.add_all([entry1, entry2, entry3])
            await session.flush()

            detector = ChekhovDetector()
            guns = await detector.detect_guns(session, novel_id)

            assert len(guns) == 2  # Only foreshadowing and mystery
            gun_types = {g.gun_type for g in guns}
            assert "foreshadowing" in gun_types
            assert "mystery" in gun_types
            await session.commit()

    @pytest.mark.asyncio
    async def test_does_not_duplicate_existing_guns(self, db_engine):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)

            entry = StoryBibleEntry(
                novel_id=novel_id,
                entry_type="foreshadowing",
                content="Sword on the wall",
                source_chapter=1,
                importance=3,
            )
            session.add(entry)
            await session.flush()

            # Create existing gun for this entry
            gun = ChekhovGun(
                novel_id=novel_id,
                description="Sword on the wall",
                introduced_at_chapter=1,
                gun_type="foreshadowing",
                status="loaded",
                pressure_score=0.0,
                bible_entry_id=entry.id,
            )
            session.add(gun)
            await session.flush()

            detector = ChekhovDetector()
            new_guns = await detector.detect_guns(session, novel_id)

            assert len(new_guns) == 0
            await session.commit()


class TestChekhovTracker:
    """Test pressure scoring."""

    @pytest.mark.asyncio
    async def test_pressure_increases_each_chapter(self, db_engine):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)

            gun = ChekhovGun(
                novel_id=novel_id,
                description="The mysterious door",
                introduced_at_chapter=1,
                gun_type="mystery",
                status="loaded",
                pressure_score=0.0,
                last_touched_chapter=1,
            )
            session.add(gun)
            await session.flush()

            tracker = ChekhovTracker()

            # Chapter 3: 2 chapters since touch
            await tracker.update_pressure(session, novel_id, 3)
            assert gun.pressure_score == pytest.approx(0.2, abs=0.01)

            # Chapter 6: 5 chapters since touch
            gun.last_touched_chapter = 1  # reset
            await tracker.update_pressure(session, novel_id, 6)
            assert gun.pressure_score == pytest.approx(0.5, abs=0.01)
            await session.commit()

    @pytest.mark.asyncio
    async def test_pressure_capped_at_1(self, db_engine):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)

            gun = ChekhovGun(
                novel_id=novel_id,
                description="Ancient prophecy",
                introduced_at_chapter=1,
                gun_type="foreshadowing",
                status="loaded",
                pressure_score=0.0,
                last_touched_chapter=1,
            )
            session.add(gun)
            await session.flush()

            tracker = ChekhovTracker()

            # 20 chapters later - well past window
            await tracker.update_pressure(session, novel_id, 21)
            assert gun.pressure_score == 1.0
            await session.commit()

    @pytest.mark.asyncio
    async def test_interactions_update_status(self, db_engine):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)

            gun = ChekhovGun(
                novel_id=novel_id,
                description="The locked chest",
                introduced_at_chapter=1,
                gun_type="mystery",
                status="loaded",
                pressure_score=0.5,
                last_touched_chapter=1,
                chapters_since_touch=5,
            )
            session.add(gun)
            await session.flush()

            tracker = ChekhovTracker()
            interactions = [
                {
                    "gun_description": "The locked chest",
                    "interaction_type": "resolved",
                    "details": "Hero opened it with the key",
                },
            ]
            await tracker.process_interactions(session, novel_id, interactions)

            assert gun.status == "resolved"
            await session.commit()


class TestChekhovInjector:
    """Test directive generation."""

    @pytest.mark.asyncio
    async def test_generates_directives_for_high_pressure(self, db_engine):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)

            gun_high = ChekhovGun(
                novel_id=novel_id,
                description="The sealed letter",
                introduced_at_chapter=1,
                gun_type="foreshadowing",
                status="loaded",
                pressure_score=0.8,
                chapters_since_touch=8,
            )
            gun_low = ChekhovGun(
                novel_id=novel_id,
                description="Background detail",
                introduced_at_chapter=2,
                gun_type="foreshadowing",
                status="loaded",
                pressure_score=0.3,
                chapters_since_touch=3,
            )
            session.add_all([gun_high, gun_low])
            await session.flush()

            injector = ChekhovInjector()
            directives = await injector.get_directives(session, novel_id)

            # Only high-pressure gun should get a directive
            assert len(directives) == 1
            assert "sealed letter" in directives[0]
            await session.commit()

    @pytest.mark.asyncio
    async def test_critical_directive_wording(self, db_engine):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)

            gun = ChekhovGun(
                novel_id=novel_id,
                description="The dark prophecy",
                introduced_at_chapter=1,
                gun_type="foreshadowing",
                status="loaded",
                pressure_score=0.95,  # Critical
                chapters_since_touch=10,
            )
            session.add(gun)
            await session.flush()

            injector = ChekhovInjector()
            directives = await injector.get_directives(session, novel_id)

            assert len(directives) == 1
            assert "CRITICAL" in directives[0]
            assert "MUST" in directives[0]
            await session.commit()

    @pytest.mark.asyncio
    async def test_no_directives_for_low_pressure(self, db_engine):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)

            gun = ChekhovGun(
                novel_id=novel_id,
                description="Minor detail",
                introduced_at_chapter=1,
                gun_type="foreshadowing",
                status="loaded",
                pressure_score=0.2,
                chapters_since_touch=2,
            )
            session.add(gun)
            await session.flush()

            injector = ChekhovInjector()
            directives = await injector.get_directives(session, novel_id)

            assert len(directives) == 0
            await session.commit()
