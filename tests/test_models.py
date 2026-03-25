"""Tests for SQLAlchemy ORM models.

Verifies table creation, relationships, cascade deletes,
unique constraints, JSON columns, and enum-like status fields.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from aiwebnovel.db.models import (
    ArcPlan,
    AuthorProfile,
    Base,
    Chapter,
    ChapterSummary,
    Character,
    CharacterPowerProfile,
    ChekhovGun,
    GenerationJob,
    Novel,
    NovelSeed,
    NovelTag,
    PowerRank,
    PowerSystem,
    User,
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


async def _make_user(session: AsyncSession, **overrides) -> User:
    defaults = {
        "email": "test@example.com",
        "username": "testauthor",
        "role": "author",
        "is_anonymous": False,
    }
    defaults.update(overrides)
    user = User(**defaults)
    session.add(user)
    await session.flush()
    return user


async def _make_novel(session: AsyncSession, author: User, **overrides) -> Novel:
    defaults = {
        "author_id": author.id,
        "title": "Test Novel",
    }
    defaults.update(overrides)
    novel = Novel(**defaults)
    session.add(novel)
    await session.flush()
    return novel


async def _make_character(
    session: AsyncSession, novel: Novel, name: str = "Hero", **overrides
) -> Character:
    defaults = {
        "novel_id": novel.id,
        "name": name,
        "role": "protagonist",
        "description": "A brave hero.",
    }
    defaults.update(overrides)
    char = Character(**defaults)
    session.add(char)
    await session.flush()
    return char


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------


class TestTableCreation:
    """All models should create their tables without errors."""

    async def test_all_tables_created(self, engine):
        """Verify that create_all succeeds and expected tables exist."""
        async with engine.begin() as conn:
            # Introspect table names
            from sqlalchemy import inspect as sa_inspect

            def get_tables(connection):
                insp = sa_inspect(connection)
                return insp.get_table_names()

            tables = await conn.run_sync(get_tables)

        expected = [
            "users", "author_profiles", "reader_profiles", "reader_bookmarks",
            "novels", "novel_settings", "novel_access", "chapters",
            "chapter_summaries", "chapter_drafts", "world_building_stages",
            "cosmology", "regions", "factions", "historical_events",
            "characters", "character_relationships", "faction_relationships",
            "power_systems", "power_ranks", "power_disciplines",
            "discipline_synergies", "abilities", "character_power_profiles",
            "character_abilities", "character_power_sources",
            "advancement_events", "arc_plans", "chapter_plans",
            "plot_threads", "scope_tiers", "escalation_state",
            "foreshadowing_seeds", "tension_tracker",
            "story_bible_entries", "bible_entry_entities",
            "context_retrieval_log", "character_knowledge",
            "character_worldviews", "narrative_voices", "chapter_pov",
            "perspective_divergences", "chekhov_guns",
            "art_assets", "art_style_guides", "art_generation_queue",
            "reader_signals", "oracle_questions", "butterfly_choices",
            "faction_alignments", "llm_usage_log", "image_usage_log",
            "generation_jobs", "notifications",
            "novel_stats", "novel_ratings", "novel_tags", "novel_seeds",
        ]
        for table_name in expected:
            assert table_name in tables, f"Missing table: {table_name}"


# ---------------------------------------------------------------------------
# Cascade deletes
# ---------------------------------------------------------------------------


class TestCascadeDeletes:
    """Deleting a novel should cascade to all child tables."""

    async def test_delete_novel_cascades_chapters(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        chapter = Chapter(
            novel_id=novel.id,
            chapter_number=1,
            chapter_text="Chapter one text.",
            model_used="test-model",
        )
        session.add(chapter)
        await session.flush()

        # Delete the novel
        await session.delete(novel)
        await session.flush()

        result = await session.execute(select(Chapter).where(Chapter.novel_id == novel.id))
        assert result.scalars().all() == []

    async def test_delete_novel_cascades_characters(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        char = await _make_character(session, novel)

        await session.delete(novel)
        await session.flush()

        result = await session.execute(select(Character).where(Character.id == char.id))
        assert result.scalar_one_or_none() is None

    async def test_delete_novel_cascades_arc_plans(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        arc = ArcPlan(novel_id=novel.id, title="Arc 1", description="First arc")
        session.add(arc)
        await session.flush()

        await session.delete(novel)
        await session.flush()

        result = await session.execute(select(ArcPlan).where(ArcPlan.novel_id == novel.id))
        assert result.scalars().all() == []

    async def test_delete_novel_cascades_chekhov_guns(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        gun = ChekhovGun(
            novel_id=novel.id,
            description="A mysterious artifact",
            introduced_at_chapter=1,
            gun_type="artifact",
        )
        session.add(gun)
        await session.flush()

        await session.delete(novel)
        await session.flush()

        result = await session.execute(select(ChekhovGun).where(ChekhovGun.novel_id == novel.id))
        assert result.scalars().all() == []

    async def test_delete_novel_cascades_seeds(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        seed = NovelSeed(
            novel_id=novel.id, seed_id="power_earned_mastery",
            seed_category="power_system", seed_text="Earned mastery",
        )
        session.add(seed)
        await session.flush()

        await session.delete(novel)
        await session.flush()

        result = await session.execute(
            select(NovelSeed).where(NovelSeed.novel_id == novel.id)
        )
        assert result.scalars().all() == []

    async def test_delete_user_cascades_novels(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)

        await session.delete(user)
        await session.flush()

        result = await session.execute(select(Novel).where(Novel.id == novel.id))
        assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Unique constraints
# ---------------------------------------------------------------------------


class TestUniqueConstraints:
    """Unique constraints should prevent duplicate entries."""

    async def test_chapter_unique_per_novel(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        ch1 = Chapter(
            novel_id=novel.id, chapter_number=1,
            chapter_text="First", model_used="m",
        )
        session.add(ch1)
        await session.flush()

        ch1_dup = Chapter(
            novel_id=novel.id, chapter_number=1,
            chapter_text="Duplicate", model_used="m",
        )
        session.add(ch1_dup)
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_summary_unique_per_chapter_type(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        ch = Chapter(
            novel_id=novel.id, chapter_number=1,
            chapter_text="Text", model_used="m",
        )
        session.add(ch)
        await session.flush()

        s1 = ChapterSummary(chapter_id=ch.id, summary_type="standard", content="Summary 1")
        session.add(s1)
        await session.flush()

        s2 = ChapterSummary(chapter_id=ch.id, summary_type="standard", content="Summary 2")
        session.add(s2)
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_power_rank_unique_per_system(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        ps = PowerSystem(
            novel_id=novel.id, system_name="Magic",
            core_mechanic="mana", energy_source="nature",
            advancement_mechanics={}, hard_limits=[], soft_limits=[],
            power_ceiling="godhood",
        )
        session.add(ps)
        await session.flush()

        r1 = PowerRank(
            power_system_id=ps.id, rank_name="Novice", rank_order=1,
            description="d", typical_capabilities="c",
            advancement_requirements="r", advancement_bottleneck="b",
            qualitative_shift="q",
        )
        session.add(r1)
        await session.flush()

        r2 = PowerRank(
            power_system_id=ps.id, rank_name="Also Novice", rank_order=1,
            description="d2", typical_capabilities="c2",
            advancement_requirements="r2", advancement_bottleneck="b2",
            qualitative_shift="q2",
        )
        session.add(r2)
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_novel_tag_unique(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        t1 = NovelTag(novel_id=novel.id, tag_name="fantasy")
        session.add(t1)
        await session.flush()

        t2 = NovelTag(novel_id=novel.id, tag_name="fantasy")
        session.add(t2)
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_novel_seed_unique(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        s1 = NovelSeed(
            novel_id=novel.id, seed_id="power_earned_mastery",
            seed_category="power_system", seed_text="Earned mastery",
        )
        session.add(s1)
        await session.flush()

        s2 = NovelSeed(
            novel_id=novel.id, seed_id="power_earned_mastery",
            seed_category="power_system", seed_text="Duplicate",
        )
        session.add(s2)
        with pytest.raises(IntegrityError):
            await session.flush()


# ---------------------------------------------------------------------------
# Relationship back_populates
# ---------------------------------------------------------------------------


class TestRelationships:
    """Verify that bidirectional relationships work correctly."""

    async def test_user_has_novels(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)

        await session.refresh(user, ["novels"])
        assert len(user.novels) == 1
        assert user.novels[0].id == novel.id

    async def test_novel_has_chapters(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        ch = Chapter(
            novel_id=novel.id, chapter_number=1,
            chapter_text="Text", model_used="m",
        )
        session.add(ch)
        await session.flush()

        await session.refresh(novel, ["chapters"])
        assert len(novel.chapters) == 1
        assert novel.chapters[0].chapter_number == 1

    async def test_chapter_has_summaries(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        ch = Chapter(
            novel_id=novel.id, chapter_number=1,
            chapter_text="Text", model_used="m",
        )
        session.add(ch)
        await session.flush()

        s = ChapterSummary(chapter_id=ch.id, summary_type="standard", content="Sum")
        session.add(s)
        await session.flush()

        await session.refresh(ch, ["summaries"])
        assert len(ch.summaries) == 1
        assert ch.summaries[0].summary_type == "standard"

    async def test_character_has_power_profile(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        char = await _make_character(session, novel)

        ps = PowerSystem(
            novel_id=novel.id, system_name="Magic",
            core_mechanic="m", energy_source="e",
            advancement_mechanics={}, hard_limits=[], soft_limits=[],
            power_ceiling="c",
        )
        session.add(ps)
        await session.flush()

        rank = PowerRank(
            power_system_id=ps.id, rank_name="Novice", rank_order=1,
            description="d", typical_capabilities="c",
            advancement_requirements="r", advancement_bottleneck="b",
            qualitative_shift="q",
        )
        session.add(rank)
        await session.flush()

        profile = CharacterPowerProfile(
            character_id=char.id, current_rank_id=rank.id,
        )
        session.add(profile)
        await session.flush()

        await session.refresh(char, ["power_profile"])
        assert char.power_profile is not None
        assert char.power_profile.current_rank_id == rank.id

    async def test_novel_has_seeds(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        seed = NovelSeed(
            novel_id=novel.id, seed_id="power_earned_mastery",
            seed_category="power_system", seed_text="Earned mastery",
            status="proposed",
        )
        session.add(seed)
        await session.flush()

        await session.refresh(novel, ["novel_seeds"])
        assert len(novel.novel_seeds) == 1
        assert novel.novel_seeds[0].seed_id == "power_earned_mastery"
        assert novel.novel_seeds[0].status == "proposed"

    async def test_author_profile_back_populates(self, session):
        user = await _make_user(session)
        profile = AuthorProfile(user_id=user.id)
        session.add(profile)
        await session.flush()

        await session.refresh(user, ["author_profile"])
        assert user.author_profile is not None
        assert user.author_profile.user_id == user.id


# ---------------------------------------------------------------------------
# JSON columns
# ---------------------------------------------------------------------------


class TestJSONColumns:
    """JSON columns should store and retrieve structured data."""

    async def test_character_personality_traits(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        traits = [{"trait": "brave", "intensity": 8}, {"trait": "stubborn", "intensity": 6}]
        char = await _make_character(session, novel, personality_traits=traits)

        await session.refresh(char)
        assert char.personality_traits == traits

    async def test_power_system_json_fields(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)

        mechanics = {"training": "meditation", "breakthroughs": "insight"}
        hard = ["cannot resurrect the dead"]
        soft = ["time manipulation is dangerous"]

        ps = PowerSystem(
            novel_id=novel.id, system_name="Qi",
            core_mechanic="cultivation", energy_source="qi",
            advancement_mechanics=mechanics,
            hard_limits=hard, soft_limits=soft,
            power_ceiling="Dao Realm",
        )
        session.add(ps)
        await session.flush()
        await session.refresh(ps)

        assert ps.advancement_mechanics == mechanics
        assert ps.hard_limits == hard
        assert ps.soft_limits == soft

    async def test_generation_job_metadata(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        meta = {"retry_reason": "timeout", "attempt": 2}
        job = GenerationJob(
            novel_id=novel.id, job_type="chapter",
            metadata_json=meta,
        )
        session.add(job)
        await session.flush()
        await session.refresh(job)
        assert job.metadata_json == meta


# ---------------------------------------------------------------------------
# Status / enum-like fields
# ---------------------------------------------------------------------------


class TestStatusFields:
    """Status fields should accept valid string values."""

    async def test_novel_status_values(self, session):
        user = await _make_user(session)
        for status in [
            "skeleton_pending", "skeleton_in_progress", "skeleton_complete",
            "writing", "writing_paused", "writing_complete", "complete",
        ]:
            novel = Novel(
                author_id=user.id,
                title=f"Novel {status}",
                status=status,
            )
            session.add(novel)
        await session.flush()

        result = await session.execute(select(Novel).where(Novel.author_id == user.id))
        novels = result.scalars().all()
        assert len(novels) == 7

    async def test_chapter_status_values(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        for i, status in enumerate(["draft", "published", "revision_needed"], 1):
            ch = Chapter(
                novel_id=novel.id, chapter_number=i,
                chapter_text=f"Ch {i}", model_used="m",
                status=status,
            )
            session.add(ch)
        await session.flush()

        result = await session.execute(
            select(Chapter).where(Chapter.novel_id == novel.id)
        )
        chapters = result.scalars().all()
        assert len(chapters) == 3

    async def test_chekhov_gun_status_values(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        for status in ["loaded", "cocked", "fired", "dud"]:
            gun = ChekhovGun(
                novel_id=novel.id,
                description=f"Gun {status}",
                introduced_at_chapter=1,
                gun_type="object",
                status=status,
            )
            session.add(gun)
        await session.flush()

        result = await session.execute(
            select(ChekhovGun).where(ChekhovGun.novel_id == novel.id)
        )
        guns = result.scalars().all()
        assert len(guns) == 4


# ---------------------------------------------------------------------------
# __repr__ smoke tests
# ---------------------------------------------------------------------------


class TestRepr:
    """Models should have meaningful __repr__ strings."""

    async def test_user_repr(self, session):
        user = await _make_user(session)
        r = repr(user)
        assert "User" in r
        assert "test@example.com" in r

    async def test_novel_repr(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        r = repr(novel)
        assert "Novel" in r
        assert "Test Novel" in r

    async def test_chapter_repr(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        ch = Chapter(
            novel_id=novel.id, chapter_number=1,
            chapter_text="T", model_used="m",
        )
        session.add(ch)
        await session.flush()
        r = repr(ch)
        assert "Chapter" in r
        assert "num=1" in r

    async def test_novel_seed_repr(self, session):
        user = await _make_user(session)
        novel = await _make_novel(session, user)
        seed = NovelSeed(
            novel_id=novel.id, seed_id="power_earned_mastery",
            seed_category="power_system", seed_text="Earned mastery",
        )
        session.add(seed)
        await session.flush()
        r = repr(seed)
        assert "NovelSeed" in r
        assert "power_earned_mastery" in r
        assert "proposed" in r
