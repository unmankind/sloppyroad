"""Tests for arc and chapter planning."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArcPlan,
    AuthorProfile,
    ChapterPlan,
    ChekhovGun,
    EscalationState,
    Novel,
    PlotThread,
    ScopeTier,
    User,
)
from aiwebnovel.llm.provider import LLMProvider, LLMResponse
from aiwebnovel.story.planner import StoryPlanner


@pytest.fixture()
def mock_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="test-secret",
    )


VALID_ARC_JSON = json.dumps({
    "title": "The First Trial",
    "description": "Hero faces their first real challenge.",
    "target_chapter_start": 1,
    "target_chapter_end": 6,
    "key_events": [
        {
            "event_order": 1,
            "description": "Challenge begins",
            "chapter_target": 1,
            "characters_involved": ["Hero"],
        },
        {
            "event_order": 2,
            "description": "Climax",
            "chapter_target": 5,
            "characters_involved": ["Hero", "Villain"],
        },
    ],
    "character_arcs": [
        {
            "character_name": "Hero",
            "arc_goal": "Survive",
            "starting_state": "Weak",
            "ending_state": "Stronger",
        },
    ],
    "themes": [
        {"theme": "Perseverance", "how_explored": "Through repeated failure and recovery"},
    ],
})

VALID_CHAPTER_PLAN_JSON = json.dumps({
    "title": "The Challenge Begins",
    "scenes": [
        {
            "description": "Opening scene",
            "beats": ["arrive", "observe"],
            "emotional_trajectory": "curious to tense",
        },
        {
            "description": "Confrontation",
            "beats": ["fight", "retreat"],
            "emotional_trajectory": "tense to fearful",
        },
        {
            "description": "Aftermath",
            "beats": ["reflect", "plan"],
            "emotional_trajectory": "fearful to determined",
        },
    ],
    "target_tension": 0.6,
})

VALID_THREAD_JSON = json.dumps({
    "threads": [
        {
            "name": "Missing artifact",
            "description": "The orb was lost",
            "thread_type": "mystery",
            "related_characters": ["Hero"],
        },
    ],
})


@pytest.fixture()
def mock_llm(mock_settings: Settings) -> LLMProvider:
    llm = MagicMock(spec=LLMProvider)
    llm.settings = mock_settings
    llm.estimate_tokens = MagicMock(return_value=100)
    llm.budget_checker = MagicMock()
    llm.budget_checker.check_llm_budget = AsyncMock()
    return llm


async def _seed(session: AsyncSession) -> int:
    user = User(id=1, email="t@t.com", role="author", is_anonymous=False, hashed_password="x")
    session.add(user)
    await session.flush()
    profile = AuthorProfile(user_id=1, api_budget_cents=10000, api_spent_cents=0)
    session.add(profile)
    novel = Novel(author_id=1, title="Test", status="writing")
    session.add(novel)
    await session.flush()
    tier = ScopeTier(novel_id=novel.id, tier_order=1, tier_name="Local", description="d")
    session.add(tier)
    await session.flush()
    esc = EscalationState(
        novel_id=novel.id, current_tier_id=tier.id, current_phase="buildup",
        tension_level=0.5, activated_at_chapter=1,
    )
    session.add(esc)
    await session.flush()
    return novel.id


class TestPlanNextArc:
    """Test arc planning."""

    @pytest.mark.asyncio
    async def test_creates_proposed_arc(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            await session.commit()

        mock_llm.generate = AsyncMock(return_value=LLMResponse(
            content=VALID_ARC_JSON, model="test",
            prompt_tokens=100, completion_tokens=100, cost_cents=0.01, duration_ms=100,
        ))

        planner = StoryPlanner(mock_llm, mock_settings)

        async with session_factory() as session:
            arc = await planner.plan_next_arc(session, novel_id, user_id=1)
            await session.commit()

        assert arc.title == "The First Trial"
        assert arc.status == "proposed"
        assert arc.arc_number == 1

    @pytest.mark.asyncio
    async def test_final_arc_includes_resolution_targets(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            # Add a thread and gun to resolve
            thread = PlotThread(
                novel_id=novel_id, name="Main thread", description="d",
                introduced_at_chapter=1, status="active",
            )
            session.add(thread)
            gun = ChekhovGun(
                novel_id=novel_id, description="The mysterious sword",
                introduced_at_chapter=1, gun_type="mystery", status="loaded",
                pressure_score=0.8,
            )
            session.add(gun)
            await session.commit()

        mock_llm.generate = AsyncMock(return_value=LLMResponse(
            content=VALID_ARC_JSON, model="test",
            prompt_tokens=100, completion_tokens=100, cost_cents=0.01, duration_ms=100,
        ))

        planner = StoryPlanner(mock_llm, mock_settings)

        async with session_factory() as session:
            arc = await planner.plan_final_arc(session, novel_id, user_id=1)
            await session.commit()

        assert arc.is_final_arc
        assert arc.resolution_targets is not None
        assert len(arc.resolution_targets) >= 2


class TestApproveArc:
    """Test arc approval and chapter decomposition."""

    @pytest.mark.asyncio
    async def test_decomposes_into_chapter_plans(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            arc = ArcPlan(
                novel_id=novel_id, title="Test Arc", description="d",
                target_chapter_start=1, target_chapter_end=6,
                status="proposed",
                key_events=[{
                    "event_order": 1,
                    "description": "test",
                    "chapter_target": 3,
                    "characters_involved": [],
                }],
            )
            session.add(arc)
            await session.commit()
            arc_id = arc.id

        planner = StoryPlanner(mock_llm, mock_settings)

        async with session_factory() as session:
            plans = await planner.approve_arc(session, arc_id)
            await session.commit()

        assert len(plans) == 6  # Chapters 1-6
        assert all(p.status == "planned" for p in plans)

        # Verify arc status changed
        async with session_factory() as session:
            stmt = select(ArcPlan).where(ArcPlan.id == arc_id)
            result = await session.execute(stmt)
            arc = result.scalar_one()
            assert arc.status == "approved"


class TestBridgeChapter:
    """Test bridge chapter creation."""

    @pytest.mark.asyncio
    async def test_creates_bridge(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            await session.commit()

        planner = StoryPlanner(mock_llm, mock_settings)

        async with session_factory() as session:
            plan = await planner.create_bridge_chapter(session, novel_id, chapter_number=1)
            await session.commit()

        assert plan.is_bridge
        assert plan.arc_plan_id is None

    @pytest.mark.asyncio
    async def test_max_3_consecutive_bridges(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            # Add 3 bridge chapter plans
            for i in range(1, 4):
                plan = ChapterPlan(
                    novel_id=novel_id, chapter_number=i,
                    is_bridge=True, status="planned",
                )
                session.add(plan)
            await session.commit()

        planner = StoryPlanner(mock_llm, mock_settings)

        async with session_factory() as session:
            with pytest.raises(ValueError, match="Maximum 3"):
                await planner.create_bridge_chapter(session, novel_id, chapter_number=4)


class TestPlanChapter:
    """Test individual chapter planning."""

    @pytest.mark.asyncio
    async def test_creates_chapter_plan(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            arc = ArcPlan(
                novel_id=novel_id, title="Arc", description="d",
                target_chapter_start=1, target_chapter_end=5,
                status="in_progress",
            )
            session.add(arc)
            await session.commit()

        mock_llm.generate = AsyncMock(return_value=LLMResponse(
            content=VALID_CHAPTER_PLAN_JSON, model="test",
            prompt_tokens=100, completion_tokens=100, cost_cents=0.01, duration_ms=100,
        ))

        planner = StoryPlanner(mock_llm, mock_settings)

        async with session_factory() as session:
            plan = await planner.plan_chapter(session, novel_id, 1, user_id=1)
            await session.commit()

        assert plan.title == "The Challenge Begins"
        assert plan.scene_outline is not None
        assert len(plan.scene_outline) == 3
        assert plan.target_tension == 0.6


class TestExtractPlotThreads:
    """Test plot thread extraction."""

    @pytest.mark.asyncio
    async def test_extracts_new_threads(
        self, db_engine, mock_llm, mock_settings,
    ):
        from aiwebnovel.llm.parsers import KeyEvent, NarrativeAnalysisResult
        from aiwebnovel.story.analyzer import AnalysisResult

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            await session.commit()

        mock_llm.generate = AsyncMock(return_value=LLMResponse(
            content=VALID_THREAD_JSON, model="test",
            prompt_tokens=100, completion_tokens=100, cost_cents=0.01, duration_ms=100,
        ))

        planner = StoryPlanner(mock_llm, mock_settings)

        analysis = AnalysisResult(
            narrative=NarrativeAnalysisResult(
                key_events=[KeyEvent(
                    description="Orb vanished",
                    emotional_beat="shock",
                    characters_involved=["Hero"],
                    narrative_importance="major",
                )],
                overall_emotional_arc="Shock to determination",
                tension_level=0.6,
                tension_phase="confrontation",
            ),
            narrative_success=True,
        )

        async with session_factory() as session:
            threads = await planner.extract_plot_threads(
                session, novel_id, 1, analysis, user_id=1,
            )
            await session.commit()

        assert len(threads) == 1
        assert threads[0].name == "Missing artifact"
