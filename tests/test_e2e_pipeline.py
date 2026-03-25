"""End-to-end integration tests for the world + chapter generation pipeline.

Exercises the full generation pipeline with mocked LLM calls but real
sub-components (context assembler, analyzer, validator, extractor).
Uses an in-memory SQLite database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    AuthorProfile,
    Base,
    Chapter,
    ChapterDraft,
    ChapterSummary,
    GenerationJob,
    Novel,
    User,
    WorldBuildingStage,
)
from aiwebnovel.llm.parsers import (
    ActiveConflict,
    AdvancementMechanics,
    AntagonistEntry,
    AntagonistsResponse,
    CosmicLaw,
    CosmologyResponse,
    CurrentStateResponse,
    Discipline,
    EarnedPowerEval,
    EnergyType,
    FactionEntry,
    FundamentalForce,
    GeographyResponse,
    HistoricalEra,
    HistoricalEventEntry,
    HistoryResponse,
    KeyEvent,
    KeyFigure,
    Motivation,
    NarrativeAnalysisResult,
    Personality,
    PlaneOfExistence,
    PoliticalEntity,
    PowerEvent,
    PowerRank,
    PowerSystemResponse,
    ProtagonistResponse,
    RealityTier,
    RegionEntry,
    StartingPower,
    SupportingCastResponse,
    SupportingCharacterEntry,
    SystemAnalysisResult,
)
from aiwebnovel.llm.provider import LLMProvider, LLMResponse
from aiwebnovel.story.pipeline import StoryPipeline

# ═══════════════════════════════════════════════════════════════════════════
# Mock LLM response builders
# ═══════════════════════════════════════════════════════════════════════════


def _cosmology_json() -> str:
    return CosmologyResponse(
        fundamental_forces=[
            FundamentalForce(
                name="Qi", description="Life energy",
                mortal_interaction="Channel through meridians",
                extreme_concentration_effect="Ascension",
            ),
            FundamentalForce(
                name="Void", description="Entropy force",
                mortal_interaction="Erodes the weak",
                extreme_concentration_effect="Annihilation",
            ),
        ],
        planes_of_existence=[
            PlaneOfExistence(
                name="Mortal Realm",
                description="Physical world",
                accessibility_requirements="None",
                native_inhabitants="Humans",
            ),
            PlaneOfExistence(
                name="Spirit Realm",
                description="Ethereal plane",
                accessibility_requirements="Rank 5+",
                native_inhabitants="Spirits",
            ),
            PlaneOfExistence(
                name="Void Between",
                description="Gap between realms",
                accessibility_requirements="Forbidden art",
                native_inhabitants="Void beasts",
            ),
        ],
        cosmic_laws=[
            CosmicLaw(description="Energy cannot be created, only transformed"),
            CosmicLaw(description="Higher planes compress lower ones"),
            CosmicLaw(description="All power demands sacrifice"),
        ],
        energy_types=[
            EnergyType(
                name="Qi", source="Heaven and Earth",
                properties="Versatile",
                fundamental_force="Qi",
                interactions="Enhances body and spirit",
            ),
            EnergyType(
                name="Void Essence", source="The Void",
                properties="Corrosive",
                fundamental_force="Void",
                interactions="Corrodes other energies",
            ),
        ],
        reality_tiers=[
            RealityTier(
                tier_name=f"Tier {i}",
                description=f"Level {i}",
                power_ceiling_description=f"Cap {i}",
                beings=f"Beings {i}",
                qualitative_change=f"Shift {i}",
            )
            for i in range(1, 6)
        ],
    ).model_dump_json()


def _power_system_json() -> str:
    return PowerSystemResponse(
        system_name="Qi Cultivation",
        core_mechanic="Absorb ambient Qi and refine through meridians",
        energy_source="Heaven and Earth Qi",
        ranks=[
            PowerRank(
                rank_name=f"Rank {i}",
                rank_order=i,
                description=f"Rank {i} desc",
                typical_capabilities=f"cap {i}",
                advancement_requirements=f"req {i}",
                advancement_bottleneck=f"bottleneck {i}",
                population_ratio=f"1 in {10**i}",
                qualitative_shift=f"shift {i}",
            )
            for i in range(1, 8)
        ],
        disciplines=[
            Discipline(
                name="Body Refinement",
                philosophy="Strengthen the vessel",
                source_energy="Qi",
            ),
            Discipline(
                name="Spirit Arts",
                philosophy="Commune with spirits",
                source_energy="Qi",
            ),
            Discipline(
                name="Void Walking",
                philosophy="Harness entropy",
                source_energy="Void Essence",
            ),
        ],
        advancement_mechanics=AdvancementMechanics(
            training_methods="Meditation and combat",
            breakthrough_triggers="Life-death situations",
            failure_modes="Qi deviation",
            regression_conditions="Meridian damage",
        ),
        hard_limits=["Cannot skip ranks", "One breakthrough per month"],
        soft_limits=["Dual cultivation is dangerous"],
        power_ceiling="Rank 10: merge with the Dao",
    ).model_dump_json()


def _geography_json() -> str:
    return GeographyResponse(
        regions=[
            RegionEntry(
                name="Azure Peaks",
                description="Mountain range of sect territories",
                climate="Temperate",
            ),
            RegionEntry(
                name="Crimson Desert",
                description="Harsh wasteland",
                climate="Arid",
            ),
            RegionEntry(
                name="Jade Valley",
                description="Fertile lowlands",
                climate="Subtropical",
            ),
        ],
        factions=[
            FactionEntry(
                name="Azure Cloud Sect",
                description="Dominant cultivation sect",
            ),
            FactionEntry(
                name="Crimson Exiles",
                description="Outcasts practicing forbidden arts",
            ),
        ],
        political_entities=[
            PoliticalEntity(
                name="Azure Empire",
                government_type="Sect confederacy",
                description="Alliance of sects",
            ),
        ],
    ).model_dump_json()


def _history_json() -> str:
    return HistoryResponse(
        eras=[
            HistoricalEra(
                era_name="Age of Foundation",
                duration="1000 years",
                description="First cultivators discovered Qi",
            ),
            HistoricalEra(
                era_name="Void Incursion",
                duration="100 years",
                description="Void beasts invaded the mortal realm",
            ),
            HistoricalEra(
                era_name="Current Era",
                duration="500 years",
                description="Recovery and expansion",
            ),
        ],
        events=[
            HistoricalEventEntry(
                name="First Awakening",
                era="Age of Foundation",
                description="Discovery of meridian system",
            ),
            HistoricalEventEntry(
                name="Great Seal",
                era="Void Incursion",
                description="Sealing of the Void Between",
            ),
            HistoricalEventEntry(
                name="Sect War",
                era="Current Era",
                description="Conflict between major sects",
            ),
        ],
        key_figures=[
            KeyFigure(
                name="Ancestor Qi",
                era="Age of Foundation",
                role="First Cultivator",
                legacy="Founded cultivation",
            ),
            KeyFigure(
                name="Void Emperor",
                era="Void Incursion",
                role="Void champion",
                legacy="Nearly destroyed the world",
            ),
        ],
    ).model_dump_json()


def _current_state_json() -> str:
    return CurrentStateResponse(
        active_conflicts=[
            ActiveConflict(
                name="Sect Dispute",
                parties=["Azure Cloud", "Crimson Exiles"],
                description="Border skirmishes",
                stakes="Territory control",
            ),
        ],
        political_landscape="Tense peace with undercurrents of rebellion",
        power_balance="Azure Cloud dominates but faces internal fractures",
    ).model_dump_json()


def _protagonist_json() -> str:
    return ProtagonistResponse(
        name="Wei Lin",
        age=17,
        background="Orphan from Jade Valley with latent cultivation talent",
        personality=Personality(
            core_traits=["determined", "curious"],
            flaws=["reckless", "distrustful"],
            strengths=["adaptable", "perceptive"],
            fears=["abandonment"],
            desires=["strength to protect loved ones"],
        ),
        starting_power=StartingPower(
            current_rank="Rank 1",
            discipline="Body Refinement",
        ),
        disadvantage="Damaged meridians limit Qi absorption",
        unusual_trait="Can sense Void energy",
        hidden_connection="Parents were Void researchers",
        motivation=Motivation(
            surface_motivation="Survive",
            deep_motivation="Uncover the truth",
        ),
        initial_circumstances="Lowest-tier disciple at Azure Cloud Sect",
        arc_trajectory="From outcast to bridge between worlds",
    ).model_dump_json()


def _antagonists_json() -> str:
    return AntagonistsResponse(
        antagonists=[
            AntagonistEntry(
                name="Elder Zhao",
                role="Corrupt sect elder",
                power_level="Rank 7",
                motivation="Maintain power",
            ),
            AntagonistEntry(
                name="The Hollow One",
                role="Void entity",
                power_level="Beyond ranking",
                motivation="Break the Great Seal",
            ),
        ],
    ).model_dump_json()


def _supporting_cast_json() -> str:
    return SupportingCastResponse(
        characters=[
            SupportingCharacterEntry(
                name="Mei Hua",
                role="Fellow disciple",
                connection_to_protagonist="Training partner",
            ),
            SupportingCharacterEntry(
                name="Master Chen",
                role="Mentor",
                connection_to_protagonist="Instructor",
            ),
            SupportingCharacterEntry(
                name="Li Feng",
                role="Rival",
                connection_to_protagonist="Competitive rival",
            ),
        ],
    ).model_dump_json()


WORLD_STAGE_BUILDERS = {
    "world_cosmology": _cosmology_json,
    "world_power_system": _power_system_json,
    "world_geography": _geography_json,
    "world_history": _history_json,
    "world_current_state": _current_state_json,
    "world_protagonist": _protagonist_json,
    "world_antagonists": _antagonists_json,
    "world_supporting_cast": _supporting_cast_json,
}

CHAPTER_TEXT = (
    "Wei Lin stood at the edge of the training grounds, watching the senior "
    "disciples practice their forms. Each movement sent ripples of Qi through "
    "the air, visible only to those with the sensitivity to perceive them.\n\n"
    '"You\'re not supposed to be here," Mei Hua said behind him.\n\n'
    '"I know," Wei Lin said. "I\'m just watching."\n\n'
    "She stepped beside him. Elder Zhao stood at the far end of the grounds, "
    "demonstrating a technique that seemed to pull darkness from the shadows. "
    "Nobody else seemed to notice the wrongness of it.\n\n"
    "Later that evening, in the quiet of the library, Wei Lin found an ancient "
    'scroll mentioning the Void Incursion. One passage remained clear: "Those '
    'who sense the Void carry its mark, and its mark carries a price."\n\n'
    "Master Chen found him asleep among the scrolls at dawn. "
    '"You push too hard, young one," the old man said gently.\n\n'
    '"What if patience isn\'t enough?" Wei Lin asked.\n\n'
    "The training bell rang across the valley. Another day. Another chance to "
    "grow stronger."
)


def _narrative_analysis_json() -> str:
    return NarrativeAnalysisResult(
        key_events=[
            KeyEvent(
                description="Wei Lin observes Elder Zhao's suspicious technique",
                emotional_beat="suspicion",
                characters_involved=["Wei Lin", "Elder Zhao"],
                narrative_importance="moderate",
            ),
            KeyEvent(
                description="Discovery of Void Incursion scroll",
                emotional_beat="revelation",
                characters_involved=["Wei Lin"],
                narrative_importance="major",
            ),
            KeyEvent(
                description="Master Chen offers support",
                emotional_beat="warmth",
                characters_involved=["Wei Lin", "Master Chen"],
                narrative_importance="moderate",
            ),
        ],
        overall_emotional_arc="Curiosity building to foreboding with warm anchor",
        tension_level=0.4,
        tension_phase="buildup",
        new_foreshadowing_seeds=[],
        foreshadowing_references=[],
        bible_entries_to_extract=[],
    ).model_dump_json()


def _system_analysis_json(*, earned_power_approved: bool = True) -> str:
    """Build system analysis. Set earned_power_approved=False for rejection."""
    evals = []
    power_events = []
    if not earned_power_approved:
        power_events = [
            PowerEvent(
                character_name="Wei Lin",
                event_type="rank_up",
                description="Sudden breakthrough to Rank 2",
                struggle_context="Brief meditation",
                foundation="Minimal training",
                narrative_buildup_chapters=[],
                new_rank="Rank 2",
            ),
        ]
        evals = [
            EarnedPowerEval(
                character_name="Wei Lin",
                event_description="Sudden breakthrough to Rank 2",
                struggle_score=0.05,
                struggle_reasoning="No real struggle",
                foundation_score=0.05,
                foundation_reasoning="Minimal foundation",
                cost_score=0.05,
                cost_reasoning="No sacrifice depicted",
                buildup_score=0.05,
                buildup_reasoning="No prior buildup",
                total_score=0.2,
                approved=False,
                reasoning="Power advancement lacks earned progression",
            ),
        ]
    return SystemAnalysisResult(
        power_events=power_events,
        earned_power_evaluations=evals,
        ability_usages=[],
        consistency_issues=[],
        chekhov_interactions=[],
        has_critical_violations=not earned_power_approved,
    ).model_dump_json()


# ═══════════════════════════════════════════════════════════════════════════
# DB helpers
# ═══════════════════════════════════════════════════════════════════════════


async def _create_novel(
    session: AsyncSession,
    *,
    api_budget_cents: int = 100_000,
    api_spent_cents: int = 0,
) -> tuple[int, int]:
    """Create User + AuthorProfile + Novel. Returns (novel_id, user_id)."""
    user = User(
        email="e2e@test.com",
        role="author",
        is_anonymous=False,
        hashed_password="hashed",
    )
    session.add(user)
    await session.flush()

    profile = AuthorProfile(
        user_id=user.id,
        api_budget_cents=api_budget_cents,
        api_spent_cents=api_spent_cents,
    )
    session.add(profile)

    novel = Novel(
        author_id=user.id,
        title="E2E Test Novel",
        status="writing",
    )
    session.add(novel)
    await session.flush()
    return novel.id, user.id


def _make_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=100,
        completion_tokens=200,
        cost_cents=0.01,
        duration_ms=100,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def e2e_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="e2e-test-secret",
        litellm_default_model="test-model",
        context_window_cap=200_000,
    )


@pytest.fixture()
async def e2e_engine(e2e_settings):
    engine = create_async_engine(e2e_settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
def e2e_session_factory(e2e_engine):
    return async_sessionmaker(e2e_engine, expire_on_commit=False)


@pytest.fixture()
def e2e_llm(e2e_settings, e2e_session_factory) -> LLMProvider:
    return LLMProvider(e2e_settings, e2e_session_factory)


@pytest.fixture()
def e2e_pipeline(e2e_llm, e2e_session_factory, e2e_settings) -> StoryPipeline:
    return StoryPipeline(e2e_llm, e2e_session_factory, e2e_settings)


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestWorldGenerationE2E:
    """Create novel -> generate_world() -> verify 8 stages in DB."""

    @pytest.mark.asyncio
    async def test_all_8_stages_populate_db(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(session)
            await session.commit()

        async def mock_generate(**kwargs):
            purpose = kwargs.get("purpose", "general")
            builder = WORLD_STAGE_BUILDERS.get(purpose)
            if builder:
                return _make_response(builder())
            return _make_response("{}")

        with patch.object(e2e_llm, "generate", side_effect=mock_generate):
            result = await e2e_pipeline.generate_world(novel_id, user_id=user_id)

        assert result.success
        expected = [
            "cosmology", "power_system", "geography", "history",
            "current_state", "protagonist", "antagonists", "supporting_cast",
        ]
        assert result.stages_completed == expected

        # Verify DB
        async with e2e_session_factory() as session:
            stmt = (
                select(WorldBuildingStage)
                .where(WorldBuildingStage.novel_id == novel_id)
                .order_by(WorldBuildingStage.stage_order)
            )
            rows = (await session.execute(stmt)).scalars().all()

        assert len(rows) == 8
        for i, stage_name in enumerate(expected):
            assert rows[i].stage_name == stage_name
            assert rows[i].stage_order == i
            assert rows[i].status == "complete"
            assert rows[i].parsed_data

        # Spot-check parsed data
        assert len(rows[0].parsed_data["fundamental_forces"]) == 2
        assert rows[5].parsed_data["name"] == "Wei Lin"

    @pytest.mark.asyncio
    async def test_generation_job_completed(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(session)
            await session.commit()

        async def mock_generate(**kwargs):
            builder = WORLD_STAGE_BUILDERS.get(kwargs.get("purpose", ""))
            return _make_response(builder() if builder else "{}")

        with patch.object(e2e_llm, "generate", side_effect=mock_generate):
            await e2e_pipeline.generate_world(novel_id, user_id=user_id)

        async with e2e_session_factory() as session:
            job = (await session.execute(
                select(GenerationJob).where(
                    GenerationJob.novel_id == novel_id,
                    GenerationJob.job_type == "world_generation",
                )
            )).scalar_one()

        assert job.status == "completed"
        assert job.completed_at is not None

    @pytest.mark.asyncio
    async def test_world_context_accumulates_across_stages(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        """Later stages can read prior stage data from DB."""
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(session)
            await session.commit()

        ctx_calls: list[int] = []
        original_build = e2e_pipeline.context_assembler.build_world_context

        async def tracking_build(session, nid, stage_order):
            ctx_calls.append(stage_order)
            return await original_build(session, nid, stage_order)

        async def mock_generate(**kwargs):
            builder = WORLD_STAGE_BUILDERS.get(kwargs.get("purpose", ""))
            return _make_response(builder() if builder else "{}")

        with patch.object(e2e_llm, "generate", side_effect=mock_generate):
            with patch.object(
                e2e_pipeline.context_assembler, "build_world_context",
                side_effect=tracking_build,
            ):
                result = await e2e_pipeline.generate_world(novel_id, user_id=user_id)

        assert result.success
        # Wave-based execution: build_world_context is called once per wave
        # with the min stage_order: wave 1 (0), wave 2 (3), wave 3 (5)
        assert ctx_calls == [0, 3, 5]


class TestChapterGenerationE2E:
    """Novel -> generate chapter -> verify chapter + analysis in DB."""

    def _chapter_mock_generate(self, **kwargs):
        """Dispatch mock based on purpose."""
        purpose = kwargs.get("purpose", "general")
        if purpose == "chapter_generation":
            return _make_response(CHAPTER_TEXT)
        elif purpose == "narrative_analysis":
            return _make_response(_narrative_analysis_json())
        elif purpose == "system_analysis":
            return _make_response(_system_analysis_json())
        return _make_response("{}")

    @pytest.mark.asyncio
    async def test_chapter_saved_with_content_and_summary(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(session)
            await session.commit()

        async def mock_gen(**kwargs):
            return self._chapter_mock_generate(**kwargs)

        with patch.object(e2e_llm, "generate", side_effect=mock_gen):
            result = await e2e_pipeline.generate_chapter(novel_id, 1, user_id=user_id)

        assert result.success
        assert result.chapter_id is not None
        assert len(result.chapter_text.split()) > 50

        async with e2e_session_factory() as session:
            # Chapter record
            chapter = (await session.execute(
                select(Chapter).where(Chapter.id == result.chapter_id)
            )).scalar_one()
            assert chapter.novel_id == novel_id
            assert chapter.chapter_number == 1
            assert chapter.word_count > 0
            assert chapter.status == "published"

            # Draft record
            draft = (await session.execute(
                select(ChapterDraft).where(
                    ChapterDraft.novel_id == novel_id,
                    ChapterDraft.chapter_number == 1,
                )
            )).scalar_one()
            assert draft.draft_number == 1
            assert draft.word_count > 0

            # Summary record
            summary = (await session.execute(
                select(ChapterSummary).where(
                    ChapterSummary.chapter_id == result.chapter_id,
                )
            )).scalar_one()
            assert summary.summary_type == "standard"
            assert len(summary.content) > 0

    @pytest.mark.asyncio
    async def test_consolidated_analysis_results(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        """Verify both narrative and system analysis complete successfully."""
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(session)
            await session.commit()

        async def mock_gen(**kwargs):
            return self._chapter_mock_generate(**kwargs)

        with patch.object(e2e_llm, "generate", side_effect=mock_gen):
            result = await e2e_pipeline.generate_chapter(novel_id, 1, user_id=user_id)

        assert result.success
        assert result.analysis is not None
        assert result.analysis.narrative_success
        assert result.analysis.system_success

        # Narrative content
        narr = result.analysis.narrative
        assert narr is not None
        assert len(narr.key_events) == 3
        assert narr.tension_level == pytest.approx(0.4)
        assert narr.tension_phase == "buildup"

        # System content
        sys = result.analysis.system
        assert sys is not None
        assert sys.has_critical_violations is False

    @pytest.mark.asyncio
    async def test_generation_job_tracked(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(session)
            await session.commit()

        async def mock_gen(**kwargs):
            return self._chapter_mock_generate(**kwargs)

        with patch.object(e2e_llm, "generate", side_effect=mock_gen):
            await e2e_pipeline.generate_chapter(novel_id, 1, user_id=user_id)

        async with e2e_session_factory() as session:
            job = (await session.execute(
                select(GenerationJob).where(
                    GenerationJob.novel_id == novel_id,
                    GenerationJob.job_type == "chapter_generation",
                )
            )).scalar_one()

        assert job.status == "completed"
        assert job.chapter_number == 1

    @pytest.mark.asyncio
    async def test_validation_passes_clean_chapter(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        """Chapter with no power events passes validation on first draft."""
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(session)
            await session.commit()

        async def mock_gen(**kwargs):
            return self._chapter_mock_generate(**kwargs)

        with patch.object(e2e_llm, "generate", side_effect=mock_gen):
            result = await e2e_pipeline.generate_chapter(novel_id, 1, user_id=user_id)

        assert result.success
        assert result.draft_number == 1
        assert not result.flagged_for_review
        assert result.validation is not None
        assert result.validation.passed


class TestBudgetEnforcementE2E:
    """Set budget low -> attempt generation -> verify rejection."""

    @pytest.mark.asyncio
    async def test_exhausted_budget_rejects_chapter(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(
                session, api_budget_cents=500, api_spent_cents=500,
            )
            await session.commit()

        with patch.object(e2e_llm, "generate", new_callable=AsyncMock) as mock_gen:
            result = await e2e_pipeline.generate_chapter(novel_id, 1, user_id=user_id)

        assert not result.success
        assert result.error is not None
        assert "budget" in result.error.lower()
        mock_gen.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_over_budget_rejects_chapter(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(
                session, api_budget_cents=100, api_spent_cents=200,
            )
            await session.commit()

        with patch.object(e2e_llm, "generate", new_callable=AsyncMock) as mock_gen:
            result = await e2e_pipeline.generate_chapter(novel_id, 1, user_id=user_id)

        assert not result.success
        assert "budget" in (result.error or "").lower()
        mock_gen.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_budget_failure_creates_failed_job(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(
                session, api_budget_cents=500, api_spent_cents=500,
            )
            await session.commit()

        with patch.object(e2e_llm, "generate", new_callable=AsyncMock):
            await e2e_pipeline.generate_chapter(novel_id, 1, user_id=user_id)

        async with e2e_session_factory() as session:
            job = (await session.execute(
                select(GenerationJob).where(
                    GenerationJob.novel_id == novel_id,
                )
            )).scalar_one()

        assert job.status == "failed"
        assert "budget" in (job.error_message or "").lower()


class TestEarnedPowerValidationE2E:
    """Mock unearned power -> verify rejection + auto-retry."""

    @pytest.mark.asyncio
    async def test_low_power_score_triggers_retry(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(session)
            await session.commit()

        call_count = {"chapter": 0, "system": 0}

        async def mock_gen(**kwargs):
            purpose = kwargs.get("purpose", "general")
            if purpose == "chapter_generation":
                call_count["chapter"] += 1
                return _make_response(CHAPTER_TEXT)
            elif purpose == "narrative_analysis":
                return _make_response(_narrative_analysis_json())
            elif purpose == "system_analysis":
                call_count["system"] += 1
                if call_count["system"] == 1:
                    return _make_response(_system_analysis_json(earned_power_approved=False))
                return _make_response(_system_analysis_json(earned_power_approved=True))
            return _make_response("{}")

        with patch.object(e2e_llm, "generate", side_effect=mock_gen):
            result = await e2e_pipeline.generate_chapter(novel_id, 1, user_id=user_id)

        assert result.success
        assert result.draft_number == 2
        assert not result.flagged_for_review
        assert call_count["chapter"] == 2
        assert call_count["system"] == 2

    @pytest.mark.asyncio
    async def test_persistent_failure_flags_for_review(
        self, e2e_pipeline, e2e_session_factory, e2e_llm,
    ):
        """Both drafts fail earned power -> flagged for author review."""
        async with e2e_session_factory() as session:
            novel_id, user_id = await _create_novel(session)
            await session.commit()

        async def mock_gen(**kwargs):
            purpose = kwargs.get("purpose", "general")
            if purpose == "chapter_generation":
                return _make_response(CHAPTER_TEXT)
            elif purpose == "narrative_analysis":
                return _make_response(_narrative_analysis_json())
            elif purpose == "system_analysis":
                # Always fail
                return _make_response(_system_analysis_json(earned_power_approved=False))
            return _make_response("{}")

        with patch.object(e2e_llm, "generate", side_effect=mock_gen):
            result = await e2e_pipeline.generate_chapter(novel_id, 1, user_id=user_id)

        assert result.success  # chapter still saved
        assert result.flagged_for_review
        assert result.draft_number == 2
        assert result.validation is not None
        assert not result.validation.passed
        assert any(i.issue_type == "earned_power" for i in result.validation.issues)

        # Verify DB state
        async with e2e_session_factory() as session:
            # Chapter status is "review"
            chapter = (await session.execute(
                select(Chapter).where(
                    Chapter.novel_id == novel_id,
                    Chapter.chapter_number == 1,
                )
            )).scalar_one()
            assert chapter.status == "review"

            # Both drafts exist
            drafts = (await session.execute(
                select(ChapterDraft)
                .where(
                    ChapterDraft.novel_id == novel_id,
                    ChapterDraft.chapter_number == 1,
                )
                .order_by(ChapterDraft.draft_number)
            )).scalars().all()
            assert len(drafts) == 2
            assert drafts[0].status == "rejected"
            assert drafts[1].status == "flagged"
