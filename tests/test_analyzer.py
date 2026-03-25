"""Tests for the consolidated post-chapter analyzer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    AuthorProfile,
    EscalationState,
    Novel,
    PowerSystem,
    ScopeTier,
    User,
)
from aiwebnovel.llm.parsers import NarrativeAnalysisResult, SystemAnalysisResult
from aiwebnovel.llm.provider import LLMProvider, LLMResponse
from aiwebnovel.story.analyzer import AnalysisResult, ChapterAnalyzer


@pytest.fixture()
def mock_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="test-secret",
    )


VALID_NARRATIVE_JSON = (
    '{"key_events":[{"description":"Hero fights","emotional_beat":"tense",'
    '"characters_involved":["Hero"],"narrative_importance":"major"}],'
    '"overall_emotional_arc":"Rising tension","tension_level":0.7,'
    '"tension_phase":"confrontation","new_foreshadowing_seeds":[],'
    '"foreshadowing_references":[],"bible_entries_to_extract":[],'
    '"cliffhanger_description":"Hero fell"}'
)

VALID_SYSTEM_JSON = (
    '{"power_events":[],"earned_power_evaluations":[],'
    '"ability_usages":[],"consistency_issues":[],'
    '"chekhov_interactions":[],"has_critical_violations":false}'
)


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
    ps = PowerSystem(
        novel_id=novel.id, system_name="Magic", core_mechanic="Mana",
        energy_source="World", advancement_mechanics={}, hard_limits=[],
        soft_limits=[], power_ceiling="God",
    )
    session.add(ps)
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


class TestAnalysisConcurrency:
    """Test that both analysis calls run concurrently."""

    @pytest.mark.asyncio
    async def test_both_calls_run_concurrently(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            await session.commit()

        analyzer = ChapterAnalyzer(mock_llm, mock_settings)

        # Mock the private analysis methods
        narrative_called = False
        system_called = False

        async def mock_narrative(*args, **kwargs):
            nonlocal narrative_called
            narrative_called = True
            return NarrativeAnalysisResult.model_validate_json(VALID_NARRATIVE_JSON)

        async def mock_system(*args, **kwargs):
            nonlocal system_called
            system_called = True
            return SystemAnalysisResult.model_validate_json(VALID_SYSTEM_JSON)

        analyzer._run_narrative_analysis = mock_narrative
        analyzer._run_system_analysis = mock_system

        async with session_factory() as session:
            result = await analyzer.analyze(session, novel_id, 1, "Test chapter text", user_id=1)

        assert narrative_called
        assert system_called
        assert result.narrative_success
        assert result.system_success

    @pytest.mark.asyncio
    async def test_bundles_both_results(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            await session.commit()

        analyzer = ChapterAnalyzer(mock_llm, mock_settings)

        async def mock_narrative(*args, **kwargs):
            return NarrativeAnalysisResult.model_validate_json(VALID_NARRATIVE_JSON)

        async def mock_system(*args, **kwargs):
            return SystemAnalysisResult.model_validate_json(VALID_SYSTEM_JSON)

        analyzer._run_narrative_analysis = mock_narrative
        analyzer._run_system_analysis = mock_system

        async with session_factory() as session:
            result = await analyzer.analyze(session, novel_id, 1, "text", user_id=1)

        assert isinstance(result, AnalysisResult)
        assert result.narrative is not None
        assert result.system is not None
        assert result.success


class TestAnalysisFallback:
    """Test fallback on parse failure."""

    @pytest.mark.asyncio
    async def test_partial_result_on_narrative_failure(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            await session.commit()

        analyzer = ChapterAnalyzer(mock_llm, mock_settings)

        async def fail_narrative(*args, **kwargs):
            raise ValueError("Parse failed")

        async def mock_system(*args, **kwargs):
            return SystemAnalysisResult.model_validate_json(VALID_SYSTEM_JSON)

        analyzer._run_narrative_analysis = fail_narrative
        analyzer._run_system_analysis = mock_system

        async with session_factory() as session:
            result = await analyzer.analyze(session, novel_id, 1, "text", user_id=1)

        assert not result.narrative_success
        assert result.system_success
        assert result.narrative_error is not None
        assert result.partial

    @pytest.mark.asyncio
    async def test_partial_result_on_system_failure(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            await session.commit()

        analyzer = ChapterAnalyzer(mock_llm, mock_settings)

        async def mock_narrative(*args, **kwargs):
            return NarrativeAnalysisResult.model_validate_json(VALID_NARRATIVE_JSON)

        async def fail_system(*args, **kwargs):
            raise ValueError("System parse failed")

        analyzer._run_narrative_analysis = mock_narrative
        analyzer._run_system_analysis = fail_system

        async with session_factory() as session:
            result = await analyzer.analyze(session, novel_id, 1, "text", user_id=1)

        assert result.narrative_success
        assert not result.system_success
        assert result.system_error is not None
        assert result.partial


class TestAnalysisRetry:
    """Test retry on parse failure in individual analysis methods."""

    @pytest.mark.asyncio
    async def test_narrative_retries_once(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Verify narrative analysis retries once on parse failure."""
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id = await _seed(session)
            await session.commit()

        call_count = 0

        async def mock_generate(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call returns invalid JSON
                return LLMResponse(
                    content='{"invalid": true}',
                    model="test",
                    prompt_tokens=100,
                    completion_tokens=50,
                    cost_cents=0.01,
                    duration_ms=100,
                )
            # Second call returns valid JSON
            return LLMResponse(
                content=VALID_NARRATIVE_JSON,
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
                cost_cents=0.01,
                duration_ms=100,
            )

        mock_llm.generate = mock_generate

        analyzer = ChapterAnalyzer(mock_llm, mock_settings)

        context = {
            "chapter_number": "1",
            "novel_title": "Test",
            "chapter_plan_summary": "Plan",
            "current_tier_name": "Local",
            "tier_order": "1",
            "current_phase": "buildup",
            "target_tension_range": "0.5",
            "planted_seeds": "None",
            "chapter_text": "Test text",
        }

        result = await analyzer._run_narrative_analysis(context, novel_id, 1)

        assert result is not None
        assert call_count == 2  # Retried once
