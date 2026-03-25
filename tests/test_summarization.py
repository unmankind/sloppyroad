"""Tests for summarization system."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArcPlan,
    AuthorProfile,
    Chapter,
    ChapterSummary,
    Novel,
    User,
)
from aiwebnovel.llm.provider import LLMProvider, LLMResponse
from aiwebnovel.summarization.arc_summary import ArcSummarizer
from aiwebnovel.summarization.chapter_summary import ChapterSummarizer
from aiwebnovel.summarization.relevance import RelevanceInput, RelevanceScorer


@pytest.fixture()
def mock_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="test-secret",
    )


VALID_SUMMARY_JSON = json.dumps({
    "summary": "The hero faced a challenge and grew stronger through struggle.",
    "key_events": ["Hero trained", "Hero fought rival", "Hero lost"],
    "emotional_arc": "Determination through defeat to resolve",
    "cliffhangers": ["The master disappeared"],
})

VALID_RECAP_JSON = json.dumps({
    "final_scene_snapshot": (
        "Hero stands at the edge of the destroyed bridge,"
        " rain falling, looking across the chasm."
    ),
    "emotional_state": [
        {
            "character": "Hero",
            "state": "Determined but exhausted."
            " The fight drained them.",
            "unresolved_tension": "Whether the bridge"
            " can be rebuilt",
        },
    ],
    "active_dialogue_threads": {
        "last_exchange": "\"We have to cross.\" \"There's no way.\"",
        "conversation_topic": "Crossing the chasm",
        "what_was_left_unsaid": "Hero's secret plan",
        "promises_or_oaths": None,
    },
    "cliffhanger": {
        "description": "A light appeared on the other side",
        "question_raised": "Who is on the other side?",
        "reader_expectation": "A new ally or enemy",
        "stakes": "Survival depends on crossing",
    },
    "immediate_pending_actions": [
        {
            "character": "Hero",
            "action": "Find another way across",
            "constraint": "Must do it before dawn",
        },
    ],
    "chapter_arc_beat": {
        "what_was_accomplished": "Hero reached the bridge and fought the guardian",
        "what_remains": "Crossing the chasm and reaching the temple",
        "arc_phase_note": "Rising action, approaching mid-arc climax",
    },
})

VALID_ARC_SUMMARY_JSON = json.dumps({
    "arc_summary": "The first arc saw the hero grow from a novice to a competent fighter.",
    "key_themes": ["Growth through adversity", "Cost of power"],
    "character_growth": ["Hero gained basic combat skills", "Learned humility"],
    "promises_fulfilled": ["Master's first lesson paid off"],
    "promises_outstanding": ["The sealed letter remains unopened"],
})


@pytest.fixture()
def mock_llm(mock_settings: Settings) -> LLMProvider:
    llm = MagicMock(spec=LLMProvider)
    llm.settings = mock_settings
    llm.estimate_tokens = MagicMock(return_value=200)
    llm.budget_checker = MagicMock()
    llm.budget_checker.check_llm_budget = AsyncMock()
    return llm


async def _seed(session: AsyncSession) -> tuple[int, int]:
    """Returns (novel_id, chapter_id)."""
    user = User(id=1, email="t@t.com", role="author", is_anonymous=False, hashed_password="x")
    session.add(user)
    await session.flush()
    profile = AuthorProfile(user_id=1, api_budget_cents=10000, api_spent_cents=0)
    session.add(profile)
    novel = Novel(author_id=1, title="Test", status="writing")
    session.add(novel)
    await session.flush()
    ch = Chapter(
        novel_id=novel.id, chapter_number=1, title="Ch 1",
        chapter_text="Long chapter text here...", status="published",
    )
    session.add(ch)
    await session.flush()
    return novel.id, ch.id


class TestStandardSummary:
    """Test standard summary generation."""

    @pytest.mark.asyncio
    async def test_generates_summary(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id, chapter_id = await _seed(session)
            await session.commit()

        mock_llm.generate = AsyncMock(return_value=LLMResponse(
            content=VALID_SUMMARY_JSON, model="test",
            prompt_tokens=100, completion_tokens=100, cost_cents=0.01, duration_ms=100,
        ))

        summarizer = ChapterSummarizer(mock_llm, mock_settings)

        async with session_factory() as session:
            summary = await summarizer.generate_standard_summary(
                session, novel_id, chapter_id, "Chapter text", user_id=1,
            )
            await session.commit()

        assert summary.summary_type == "standard"
        assert "hero" in summary.content.lower()
        assert summary.key_events is not None
        assert len(summary.key_events) == 3


class TestEnhancedRecap:
    """Test enhanced recap generation."""

    @pytest.mark.asyncio
    async def test_generates_recap(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id, chapter_id = await _seed(session)
            await session.commit()

        mock_llm.generate = AsyncMock(return_value=LLMResponse(
            content=VALID_RECAP_JSON, model="test",
            prompt_tokens=100, completion_tokens=100, cost_cents=0.01, duration_ms=100,
        ))

        summarizer = ChapterSummarizer(mock_llm, mock_settings)

        async with session_factory() as session:
            recap = await summarizer.generate_enhanced_recap(
                session, novel_id, chapter_id, "Chapter text", user_id=1,
            )
            await session.commit()

        assert recap.summary_type == "enhanced_recap"
        # Should contain all 6 components
        assert "Final Scene:" in recap.content
        assert "Emotional:" in recap.content
        assert "Dialogue:" in recap.content
        assert "Cliffhanger:" in recap.content
        assert "Pending:" in recap.content
        assert "Arc Beat:" in recap.content


class TestArcSummary:
    """Test arc summary generation."""

    @pytest.mark.asyncio
    async def test_aggregates_chapters(
        self, db_engine, mock_llm, mock_settings,
    ):
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            novel_id, chapter_id = await _seed(session)

            arc = ArcPlan(
                novel_id=novel_id, title="First Arc", description="d",
                target_chapter_start=1, target_chapter_end=3, status="completed",
            )
            session.add(arc)
            await session.flush()

            # Update chapter to belong to arc
            from sqlalchemy import update
            await session.execute(
                update(Chapter).where(Chapter.id == chapter_id).values(arc_plan_id=arc.id)
            )

            # Add summary
            summary = ChapterSummary(
                chapter_id=chapter_id, summary_type="standard",
                content="Chapter 1 summary text",
            )
            session.add(summary)
            await session.commit()
            arc_id = arc.id

        mock_llm.generate = AsyncMock(return_value=LLMResponse(
            content=VALID_ARC_SUMMARY_JSON, model="test",
            prompt_tokens=100, completion_tokens=100, cost_cents=0.01, duration_ms=100,
        ))

        summarizer = ArcSummarizer(mock_llm, mock_settings)

        async with session_factory() as session:
            result = await summarizer.generate_arc_summary(session, arc_id, user_id=1)

        assert "hero" in result.lower() or "novice" in result.lower()


class TestRelevanceScoring:
    """Test relevance scoring formula."""

    def test_score_formula(self):
        scorer = RelevanceScorer()
        entry = RelevanceInput(
            semantic_similarity=1.0,
            source_chapter=10,
            importance=5,
            pressure_score=1.0,
        )
        score = scorer.score(entry, current_chapter=10)

        # semantic=0.4*1.0=0.4, recency=0.25*exp(0)=0.25,
        # importance=0.2*1.0=0.2, pressure=0.15*1.0=0.15
        expected = 0.40 + 0.25 + 0.20 + 0.15
        assert score == pytest.approx(expected, abs=0.01)

    def test_recency_decay(self):
        scorer = RelevanceScorer()

        recent = RelevanceInput(
            semantic_similarity=0.5, source_chapter=9,
            importance=3, pressure_score=0.0,
        )
        old = RelevanceInput(
            semantic_similarity=0.5, source_chapter=1,
            importance=3, pressure_score=0.0,
        )

        score_recent = scorer.score(recent, current_chapter=10)
        score_old = scorer.score(old, current_chapter=10)

        assert score_recent > score_old

    def test_importance_scaling(self):
        scorer = RelevanceScorer()

        low = RelevanceInput(
            semantic_similarity=0.5, source_chapter=5,
            importance=1, pressure_score=0.0,
        )
        high = RelevanceInput(
            semantic_similarity=0.5, source_chapter=5,
            importance=5, pressure_score=0.0,
        )

        score_low = scorer.score(low, current_chapter=5)
        score_high = scorer.score(high, current_chapter=5)

        assert score_high > score_low

    def test_pressure_boost(self):
        scorer = RelevanceScorer()

        no_pressure = RelevanceInput(
            semantic_similarity=0.5, source_chapter=5,
            importance=3, pressure_score=0.0,
        )
        high_pressure = RelevanceInput(
            semantic_similarity=0.5, source_chapter=5,
            importance=3, pressure_score=1.0,
        )

        score_none = scorer.score(no_pressure, current_chapter=5)
        score_high = scorer.score(high_pressure, current_chapter=5)

        assert score_high > score_none
        # Pressure contributes 0.15 at max
        assert score_high - score_none == pytest.approx(0.15, abs=0.01)

    def test_rank_entries(self):
        scorer = RelevanceScorer()
        entries = [
            RelevanceInput(
                semantic_similarity=0.2, source_chapter=1,
                importance=1, pressure_score=0.0,
            ),
            RelevanceInput(
                semantic_similarity=0.9, source_chapter=9,
                importance=5, pressure_score=0.8,
            ),
            RelevanceInput(
                semantic_similarity=0.5, source_chapter=5,
                importance=3, pressure_score=0.3,
            ),
        ]
        ranked = scorer.rank_entries(entries, current_chapter=10)

        # Best entry should be first
        assert ranked[0][1] > ranked[1][1] > ranked[2][1]
        assert ranked[0][0].semantic_similarity == 0.9

    def test_score_bounds(self):
        """Score should always be in [0, 1]."""
        scorer = RelevanceScorer()

        # Max values
        entry = RelevanceInput(
            semantic_similarity=1.0, source_chapter=10,
            importance=5, pressure_score=1.0,
        )
        assert 0.0 <= scorer.score(entry, current_chapter=10) <= 1.0

        # Min values
        entry = RelevanceInput(
            semantic_similarity=0.0, source_chapter=0,
            importance=1, pressure_score=0.0,
        )
        assert 0.0 <= scorer.score(entry, current_chapter=100) <= 1.0
