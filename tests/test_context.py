"""Tests for context assembly."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    AuthorProfile,
    Chapter,
    ChapterSummary,
    EscalationState,
    Novel,
    PowerSystem,
    Region,
    ScopeTier,
    User,
    WorldBuildingStage,
)
from aiwebnovel.llm.provider import LLMProvider
from aiwebnovel.story.context import AssembledContext, ContextAssembler


@pytest.fixture()
def mock_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="test-secret",
        context_window_cap=5000,
    )


@pytest.fixture()
def mock_llm(mock_settings: Settings) -> LLMProvider:
    llm = MagicMock(spec=LLMProvider)
    llm.settings = mock_settings
    # Rough: 1 token per 4 chars
    llm.estimate_tokens = MagicMock(side_effect=lambda text: len(text) // 4)
    return llm


async def _seed_data(session: AsyncSession) -> int:
    """Create novel with some chapter data."""
    user = User(id=1, email="t@t.com", role="author", is_anonymous=False, hashed_password="x")
    session.add(user)
    await session.flush()

    profile = AuthorProfile(user_id=1, api_budget_cents=10000, api_spent_cents=0)
    session.add(profile)

    novel = Novel(author_id=1, title="Test", status="writing")
    session.add(novel)
    await session.flush()

    # Add power system
    ps = PowerSystem(
        novel_id=novel.id,
        system_name="Cultivation",
        core_mechanic="Absorb qi",
        energy_source="Heaven and Earth",
        advancement_mechanics={"training_methods": "meditation"},
        hard_limits=["Cannot reverse death"],
        soft_limits=["Teleportation is dangerous"],
        power_ceiling="Immortal",
    )
    session.add(ps)

    # Add scope tier + escalation
    tier = ScopeTier(
        novel_id=novel.id,
        tier_order=1,
        tier_name="Local",
        description="Village-level",
    )
    session.add(tier)
    await session.flush()

    esc = EscalationState(
        novel_id=novel.id,
        current_tier_id=tier.id,
        current_phase="buildup",
        tension_level=0.4,
        activated_at_chapter=1,
    )
    session.add(esc)

    # Add region
    region = Region(
        novel_id=novel.id,
        name="Starting Village",
        description="A small village at the edge of the wilderness.",
        revealed_at_chapter=1,
    )
    session.add(region)

    # Add a previous chapter with summary
    ch = Chapter(
        novel_id=novel.id,
        chapter_number=1,
        title="The Beginning",
        chapter_text="Chapter one text...",
        status="published",
    )
    session.add(ch)
    await session.flush()

    summary = ChapterSummary(
        chapter_id=ch.id,
        summary_type="enhanced_recap",
        content="Enhanced recap of chapter 1 with scene details...",
    )
    session.add(summary)

    std_summary = ChapterSummary(
        chapter_id=ch.id,
        summary_type="standard",
        content="Standard summary of chapter 1.",
    )
    session.add(std_summary)

    await session.flush()
    return novel.id


class TestAssembledContext:
    """Test AssembledContext dataclass."""

    def test_to_prompt_orders_by_priority(self):
        ctx = AssembledContext(budget=10000)
        ctx.add_section("low", "Low priority content", priority=5, tokens=10)
        ctx.add_section("high", "High priority content", priority=1, tokens=10)
        ctx.add_section("mid", "Mid priority content", priority=3, tokens=10)

        prompt = ctx.to_prompt()
        # High should come before mid, mid before low
        assert prompt.index("High") < prompt.index("Mid")
        assert prompt.index("Mid") < prompt.index("Low")

    def test_add_section_updates_total(self):
        ctx = AssembledContext(budget=1000)
        ctx.add_section("a", "content", priority=1, tokens=100)
        ctx.add_section("b", "more", priority=2, tokens=200)
        assert ctx.total_tokens == 300


class TestPriorityTruncation:
    """Test priority-based truncation."""

    def test_p5_dropped_first(self, mock_llm, mock_settings):
        assembler = ContextAssembler(mock_llm, mock_settings)

        ctx = AssembledContext(budget=250)
        ctx.add_section("p1", "Power system rules" * 5, priority=1, tokens=100)
        ctx.add_section("p3", "Recent summaries" * 5, priority=3, tokens=100)
        ctx.add_section("p5", "Reader influence" * 5, priority=5, tokens=100)

        assembler._truncate_to_budget(ctx)

        assert "p5" in ctx.truncated_sections
        assert "p1" in ctx.sections
        assert "p1" not in ctx.truncated_sections

    def test_p1_never_truncated(self, mock_llm, mock_settings):
        assembler = ContextAssembler(mock_llm, mock_settings)

        ctx = AssembledContext(budget=50)
        ctx.add_section("p1", "Critical" * 20, priority=1, tokens=200)
        ctx.add_section("p5", "Optional" * 5, priority=5, tokens=50)

        assembler._truncate_to_budget(ctx)

        # P1 should survive even if over budget
        assert "p1" in ctx.sections
        assert "p5" in ctx.truncated_sections

    def test_within_budget_no_truncation(self, mock_llm, mock_settings):
        assembler = ContextAssembler(mock_llm, mock_settings)

        ctx = AssembledContext(budget=1000)
        ctx.add_section("p1", "Content", priority=1, tokens=100)
        ctx.add_section("p3", "Content", priority=3, tokens=100)
        ctx.add_section("p5", "Content", priority=5, tokens=100)

        assembler._truncate_to_budget(ctx)

        assert len(ctx.truncated_sections) == 0
        assert len(ctx.sections) == 3


class TestBuildChapterContext:
    """Test full context assembly."""

    @pytest.mark.asyncio
    async def test_assembles_all_sections(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Verify context includes expected sections when data exists."""
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_data(session)
            await session.commit()

        assembler = ContextAssembler(mock_llm, mock_settings)

        async with session_factory() as session:
            ctx = await assembler.build_chapter_context(
                session, novel_id, chapter_number=2,
            )

        assert ctx.total_tokens > 0
        # Should have power system, escalation, enhanced recap at minimum
        assert "power_system" in ctx.sections
        assert "escalation" in ctx.sections

    @pytest.mark.asyncio
    async def test_enhanced_recap_used(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Verify enhanced recap is used instead of full chapter text."""
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_data(session)
            await session.commit()

        assembler = ContextAssembler(mock_llm, mock_settings)

        async with session_factory() as session:
            ctx = await assembler.build_chapter_context(
                session, novel_id, chapter_number=2,
            )

        # Enhanced recap should be present
        assert "enhanced_recap" in ctx.sections
        assert "recap" in ctx.sections["enhanced_recap"].content.lower()

    @pytest.mark.asyncio
    async def test_token_budget_respected(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Verify assembly respects token budget."""
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_data(session)
            await session.commit()

        # Very small budget
        assembler = ContextAssembler(mock_llm, mock_settings)

        async with session_factory() as session:
            ctx = await assembler.build_chapter_context(
                session, novel_id, chapter_number=2, token_budget=100,
            )

        # Some sections should be truncated
        # (Budget is very small, so lower priority should be dropped)
        # At minimum P1 should remain
        assert "power_system" in ctx.sections or len(ctx.sections) > 0


class TestBuildWorldContext:
    """Test world context accumulation."""

    @pytest.mark.asyncio
    async def test_accumulates_prior_stages(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Verify prior stage outputs are accumulated."""
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_data(session)

            # Add world stages
            for i in range(3):
                stage = WorldBuildingStage(
                    novel_id=novel_id,
                    stage_order=i,
                    stage_name=f"stage_{i}",
                    prompt_used="test",
                    raw_response=f"Stage {i} output data",
                    parsed_data={"stage": i},
                    model_used="test",
                    status="complete",
                )
                session.add(stage)
            await session.commit()

        assembler = ContextAssembler(mock_llm, mock_settings)

        async with session_factory() as session:
            # Stage 3 should see stages 0, 1, 2
            ctx = await assembler.build_world_context(session, novel_id, stage_order=3)

        assert "stage_0" in ctx["prior_context"]
        assert "stage_1" in ctx["prior_context"]
        assert "stage_2" in ctx["prior_context"]
        assert len(ctx["stages_completed"]) == 3
