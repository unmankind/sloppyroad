"""Tests for database query helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from aiwebnovel.db.models import (
    ArcPlan,
    Base,
    Chapter,
    Character,
    CharacterWorldview,
    ChekhovGun,
    EscalationState,
    ForeshadowingSeed,
    NarrativeVoice,
    Novel,
    PlotThread,
    Region,
    ScopeTier,
    TensionTracker,
    User,
)
from aiwebnovel.db.queries import (
    get_active_chekhov_guns,
    get_active_foreshadowing,
    get_active_plot_threads,
    get_chapter_context,
    get_chapters_paginated,
    get_character_full,
    get_current_arc,
    get_escalation_state,
    get_novel_with_status,
    get_recent_tension,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture()
async def session(engine) -> AsyncSession:
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


async def _seed(session: AsyncSession) -> dict:
    """Create a basic user + novel + character for most tests."""
    user = User(email="q@example.com", username="q", role="author", is_anonymous=False)
    session.add(user)
    await session.flush()

    novel = Novel(author_id=user.id, title="Query Test Novel")
    session.add(novel)
    await session.flush()

    char = Character(
        novel_id=novel.id, name="Hero", role="protagonist",
        description="Brave.", introduced_at_chapter=1,
    )
    session.add(char)
    await session.flush()

    return {"user": user, "novel": novel, "character": char}


# ---------------------------------------------------------------------------
# Novel queries
# ---------------------------------------------------------------------------


class TestNovelQueries:
    async def test_get_novel_with_status(self, session):
        data = await _seed(session)
        novel = await get_novel_with_status(session, data["novel"].id)
        assert novel is not None
        assert novel.title == "Query Test Novel"

    async def test_get_novel_not_found(self, session):
        result = await get_novel_with_status(session, 9999)
        assert result is None


# ---------------------------------------------------------------------------
# Chapter context
# ---------------------------------------------------------------------------


class TestChapterContext:
    async def test_returns_revealed_regions(self, session):
        data = await _seed(session)
        novel = data["novel"]

        r1 = Region(novel_id=novel.id, name="Village", description="Small",
                     revealed_at_chapter=None)
        r2 = Region(novel_id=novel.id, name="Forest", description="Dark",
                     revealed_at_chapter=3)
        r3 = Region(novel_id=novel.id, name="Hidden City", description="Secret",
                     revealed_at_chapter=10)
        session.add_all([r1, r2, r3])
        await session.flush()

        ctx = await get_chapter_context(session, novel.id, chapter_number=5)

        region_names = {r.name for r in ctx["revealed_regions"]}
        assert "Village" in region_names  # always visible
        assert "Forest" in region_names   # revealed at ch3, visible at ch5
        assert "Hidden City" not in region_names  # revealed at ch10

    async def test_returns_active_characters(self, session):
        data = await _seed(session)
        novel = data["novel"]

        dead = Character(
            novel_id=novel.id, name="Fallen", role="ally",
            description="d", introduced_at_chapter=1, is_alive=False,
        )
        future = Character(
            novel_id=novel.id, name="Future", role="neutral",
            description="d", introduced_at_chapter=99,
        )
        session.add_all([dead, future])
        await session.flush()

        ctx = await get_chapter_context(session, novel.id, chapter_number=5)
        names = {c.name for c in ctx["active_characters"]}
        assert "Hero" in names
        assert "Fallen" not in names  # dead
        assert "Future" not in names  # not yet introduced

    async def test_empty_novel_context(self, session):
        data = await _seed(session)
        ctx = await get_chapter_context(session, data["novel"].id, chapter_number=1)
        assert ctx["power_system"] is None
        assert ctx["current_escalation"] is None
        assert ctx["recent_chapters"] == []


# ---------------------------------------------------------------------------
# Character queries
# ---------------------------------------------------------------------------


class TestCharacterQueries:
    async def test_get_character_full(self, session):
        data = await _seed(session)
        char = data["character"]

        # Add worldview and voice
        wv = CharacterWorldview(character_id=char.id, emotional_baseline="curious")
        nv = NarrativeVoice(character_id=char.id, vocabulary_level="educated")
        session.add_all([wv, nv])
        await session.flush()

        loaded = await get_character_full(session, char.id)
        assert loaded is not None
        assert loaded.name == "Hero"
        assert loaded.worldview is not None
        assert loaded.narrative_voice is not None

    async def test_get_character_not_found(self, session):
        result = await get_character_full(session, 9999)
        assert result is None


# ---------------------------------------------------------------------------
# Foreshadowing & Chekhov
# ---------------------------------------------------------------------------


class TestForeshadowingQueries:
    async def test_active_foreshadowing(self, session):
        data = await _seed(session)
        novel = data["novel"]

        planted = ForeshadowingSeed(
            novel_id=novel.id, description="Mysterious rune",
            planted_at_chapter=1, seed_type="mystery", status="planted",
        )
        fulfilled = ForeshadowingSeed(
            novel_id=novel.id, description="Old prophecy",
            planted_at_chapter=2, seed_type="prophecy", status="fulfilled",
        )
        session.add_all([planted, fulfilled])
        await session.flush()

        seeds = await get_active_foreshadowing(session, novel.id)
        assert len(seeds) == 1
        assert seeds[0].description == "Mysterious rune"


class TestChekhovQueries:
    async def test_active_chekhov_guns(self, session):
        data = await _seed(session)
        novel = data["novel"]

        active = ChekhovGun(
            novel_id=novel.id, description="Sword on the wall",
            introduced_at_chapter=1, gun_type="object",
            status="loaded", pressure_score=0.8,
        )
        fired = ChekhovGun(
            novel_id=novel.id, description="Resolved gun",
            introduced_at_chapter=2, gun_type="mystery",
            status="fired", pressure_score=0.0,
        )
        session.add_all([active, fired])
        await session.flush()

        guns = await get_active_chekhov_guns(session, novel.id)
        assert len(guns) == 1
        assert guns[0].description == "Sword on the wall"


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


class TestEscalationQueries:
    async def test_get_escalation_state_empty(self, session):
        data = await _seed(session)
        result = await get_escalation_state(session, data["novel"].id)
        assert result["state"] is None
        assert result["scope_tier"] is None

    async def test_get_escalation_state_with_data(self, session):
        data = await _seed(session)
        novel = data["novel"]

        tier = ScopeTier(
            novel_id=novel.id, tier_order=1,
            tier_name="Village", description="Local scope",
        )
        session.add(tier)
        await session.flush()

        es = EscalationState(
            novel_id=novel.id, current_tier_id=tier.id,
            current_phase="setup", activated_at_chapter=1,
        )
        session.add(es)
        await session.flush()

        result = await get_escalation_state(session, novel.id)
        assert result["state"] is not None
        assert result["state"].current_phase == "setup"
        assert result["scope_tier"] is not None


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


class TestPlanningQueries:
    async def test_get_current_arc_none(self, session):
        data = await _seed(session)
        arc = await get_current_arc(session, data["novel"].id)
        assert arc is None

    async def test_get_current_arc(self, session):
        data = await _seed(session)
        novel = data["novel"]

        arc = ArcPlan(
            novel_id=novel.id, title="Arc 1", description="desc",
            status="in_progress",
        )
        session.add(arc)
        await session.flush()

        result = await get_current_arc(session, novel.id)
        assert result is not None
        assert result.title == "Arc 1"

    async def test_get_active_plot_threads(self, session):
        data = await _seed(session)
        novel = data["novel"]

        active = PlotThread(
            novel_id=novel.id, name="Main Quest", description="d",
            introduced_at_chapter=1, status="active", priority=1,
        )
        resolved = PlotThread(
            novel_id=novel.id, name="Side Quest", description="d",
            introduced_at_chapter=2, status="resolved", priority=5,
        )
        session.add_all([active, resolved])
        await session.flush()

        threads = await get_active_plot_threads(session, novel.id)
        assert len(threads) == 1
        assert threads[0].name == "Main Quest"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    async def test_chapters_paginated(self, session):
        data = await _seed(session)
        novel = data["novel"]

        for i in range(1, 26):
            ch = Chapter(
                novel_id=novel.id, chapter_number=i,
                chapter_text=f"Chapter {i}", model_used="m",
            )
            session.add(ch)
        await session.flush()

        page1 = await get_chapters_paginated(session, novel.id, page=1, page_size=10)
        assert page1["total"] == 25
        assert len(page1["items"]) == 10
        assert page1["page"] == 1

        page3 = await get_chapters_paginated(session, novel.id, page=3, page_size=10)
        assert len(page3["items"]) == 5

    async def test_empty_pagination(self, session):
        data = await _seed(session)
        result = await get_chapters_paginated(session, data["novel"].id)
        assert result["total"] == 0
        assert result["items"] == []


# ---------------------------------------------------------------------------
# Tension
# ---------------------------------------------------------------------------


class TestTensionQueries:
    async def test_get_recent_tension(self, session):
        data = await _seed(session)
        novel = data["novel"]

        for i in range(1, 8):
            t = TensionTracker(
                novel_id=novel.id, chapter_number=i,
                tension_level=i * 0.1,
            )
            session.add(t)
        await session.flush()

        recent = await get_recent_tension(session, novel.id, limit=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0].chapter_number == 7

    async def test_empty_tension(self, session):
        data = await _seed(session)
        result = await get_recent_tension(session, data["novel"].id)
        assert len(result) == 0
