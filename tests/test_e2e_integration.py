"""End-to-end integration tests: world + chapter generation pipeline.

These tests exercise the full pipeline paths with *mocked* LLM responses
(no real API calls), but **real** database writes and pipeline orchestration.
Every layer — pipeline, context assembly, analysis, validation, extraction,
budget enforcement, worker task wrappers, autonomous tick, and regeneration —
is exercised against a real in-memory SQLite database.

Test scenarios:
1. World generation (8-stage pipeline) → verify DB populated
2. Arc plan → approve → generate chapter → verify chapter saved
3. Reader-triggered generation within approved arc
4. Regeneration with author guidance
5. Earned power rejection → auto-retry → flag for review
6. Budget enforcement (reject when over budget)
7. Autonomous mode tick (generates chapter on schedule)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArcPlan,
    AuthorProfile,
    Base,
    Chapter,
    ChapterDraft,
    ChapterPlan,
    Character,
    ForeshadowingSeed,
    GenerationJob,
    Novel,
    NovelSettings,
    StoryBibleEntry,
    TensionTracker,
    User,
    WorldBuildingStage,
)
from aiwebnovel.llm.provider import LLMProvider, LLMResponse
from aiwebnovel.story.pipeline import StoryPipeline
from aiwebnovel.story.planner import StoryPlanner
from aiwebnovel.worker.tasks import (
    autonomous_tick_task,
    generate_chapter_task,
    generate_world_task,
)

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def e2e_settings() -> Settings:
    """Settings tuned for E2E tests."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="e2e-test-secret",
        debug=True,
        log_level="WARNING",
        image_enabled=False,
        litellm_default_model="test-model",
        litellm_fallback_model="test-fallback",
        litellm_eval_model="test-eval",
    )


@pytest.fixture()
async def e2e_engine(e2e_settings):
    """Async in-memory SQLite engine with all tables created."""
    engine = create_async_engine(
        e2e_settings.database_url,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def session_factory(e2e_engine) -> async_sessionmaker[AsyncSession]:
    """Async session factory bound to the in-memory engine."""
    return async_sessionmaker(
        e2e_engine, class_=AsyncSession, expire_on_commit=False,
    )


@pytest.fixture()
async def seed_data(session_factory) -> dict[str, Any]:
    """Create author user, profile, novel, and settings — the minimum data
    every pipeline path needs.
    """
    async with session_factory() as session:
        user = User(
            email="author@test.com",
            username="testauthor",
            display_name="Test Author",
            role="author",
            is_anonymous=False,
            hashed_password="fake-hashed",
        )
        session.add(user)
        await session.flush()

        profile = AuthorProfile(
            user_id=user.id,
            api_budget_cents=10000,
            api_spent_cents=0,
            image_budget_cents=1000,
            image_spent_cents=0,
        )
        session.add(profile)
        await session.flush()

        novel = Novel(
            author_id=user.id,
            title="The Spiral Ascendant",
            genre="progression_fantasy",
            status="skeleton_pending",
        )
        session.add(novel)
        await session.flush()

        ns = NovelSettings(novel_id=novel.id)
        session.add(ns)
        await session.commit()

        return {
            "user_id": user.id,
            "profile_id": profile.id,
            "novel_id": novel.id,
        }


@pytest.fixture()
def mock_redis():
    """Fake Redis that supports set/delete/publish."""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    redis.publish = AsyncMock()
    return redis


# ═══════════════════════════════════════════════════════════════════════════
# Fake LLM response helpers
# ═══════════════════════════════════════════════════════════════════════════


def _llm_response(content: str, model: str = "test-model") -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        prompt_tokens=100,
        completion_tokens=200,
        cost_cents=0.5,
        duration_ms=100,
    )


def _cosmology_json() -> str:
    return json.dumps({
        "fundamental_forces": [
            {"name": "Aetheric Resonance", "description": "The vibration of reality itself",
             "mortal_interaction": "Cultivators attune to it",
             "extreme_concentration_effect": "Reality warps"},
            {"name": "Void Entropy", "description": "The dissolution force",
             "mortal_interaction": "Causes decay", "extreme_concentration_effect": "Annihilation"},
        ],
        "planes_of_existence": [
            {"name": "Material Realm", "description": "Where mortals live",
             "accessibility_requirements": "Born here", "native_inhabitants": "Humans, beasts"},
            {"name": "Spirit Realm", "description": "Echoes of consciousness",
             "accessibility_requirements": "Rank 5+", "native_inhabitants": "Spirits"},
            {"name": "Void", "description": "Between planes",
             "accessibility_requirements": "Rank 8+", "native_inhabitants": "Void entities"},
        ],
        "cosmic_laws": [
            {"description": "Energy cannot be created, only transformed"},
            {"description": "Higher beings cannot directly interfere below"},
            {"description": "Advancement requires sacrifice proportional to gain"},
        ],
        "energy_types": [
            {"name": "Qi", "source": "World's breath",
             "properties": "Strengthens body and spirit",
             "fundamental_force": "Aetheric Resonance",
             "interactions": "Can combine with Void energy"},
            {"name": "Void Essence", "source": "Space between",
             "properties": "Dissolves and reshapes",
             "fundamental_force": "Void Entropy",
             "interactions": "Counters pure Qi"},
        ],
        "reality_tiers": [
            {"tier_name": "Mortal", "description": "Base reality",
             "power_ceiling_description": "Human limits",
             "beings": "Humans", "qualitative_change": "None"},
            {"tier_name": "Awakened", "description": "First touch",
             "power_ceiling_description": "Enhanced",
             "beings": "Cultivators",
             "qualitative_change": "Qi perception"},
            {"tier_name": "Foundation", "description": "Stable core",
             "power_ceiling_description": "City-level",
             "beings": "Established cultivators",
             "qualitative_change": "Core formation"},
            {"tier_name": "Transcendent",
             "description": "Beyond mortal",
             "power_ceiling_description": "Nation-level",
             "beings": "Masters",
             "qualitative_change": "Domain formation"},
            {"tier_name": "Sovereign",
             "description": "Reality shapers",
             "power_ceiling_description": "Continental",
             "beings": "Legends",
             "qualitative_change": "Law comprehension"},
        ],
    })


def _power_system_json() -> str:
    return json.dumps({
        "system_name": "Spiral Cultivation",
        "core_mechanic": "Practitioners draw energy in spiral patterns through meridians",
        "energy_source": "Ambient Qi from ley lines",
        "ranks": [
            {"rank_name": f"Rank {i}", "rank_order": i,
             "description": f"Rank {i} desc", "typical_capabilities": f"Cap {i}",
             "advancement_requirements": f"Req {i}", "advancement_bottleneck": f"Bottleneck {i}",
             "population_ratio": f"1 in {10**i}", "qualitative_shift": f"Shift {i}"}
            for i in range(1, 8)
        ],
        "disciplines": [
            {"name": "Body Refinement", "philosophy": "Forge the flesh",
             "source_energy": "Qi", "strengths": "Durability",
             "weaknesses": "Slow", "typical_practitioners": "Warriors"},
            {"name": "Soul Weaving", "philosophy": "Shape the spirit",
             "source_energy": "Qi", "strengths": "Perception",
             "weaknesses": "Fragile body", "typical_practitioners": "Scholars"},
            {"name": "Void Walking", "philosophy": "Embrace nothing",
             "source_energy": "Void Essence", "strengths": "Spatial",
             "weaknesses": "Unstable", "typical_practitioners": "Hermits"},
        ],
        "advancement_mechanics": {
            "training_methods": "Meditation, combat, comprehension",
            "breakthrough_triggers": "Accumulation + insight",
            "failure_modes": "Qi deviation, meridian collapse",
            "regression_conditions": "Core damage, backlash",
        },
        "hard_limits": ["Cannot skip ranks", "Must have a formed core to reach Rank 4"],
        "soft_limits": ["Cross-discipline cultivation is discouraged"],
        "power_ceiling": "Sovereign rank: can reshape continental geography",
    })


def _generic_stage_json(stage_name: str) -> str:
    """Return minimal valid JSON for non-cosmology/power world stages."""
    if stage_name == "geography":
        return json.dumps({
            "regions": [
                {"name": "Jade Basin", "description": "Fertile valley with dense Qi"},
                {"name": "Iron Wastes", "description": "Barren desert drained of energy"},
                {"name": "Spirit Peaks", "description": "Mountain range above clouds"},
            ],
            "factions": [
                {"name": "Azure Sect", "description": "Orthodox cultivators"},
                {"name": "Shadow Court", "description": "Underground power brokers"},
            ],
            "political_entities": [
                {"name": "Jade Kingdom",
                 "government_type": "Monarchy",
                 "description": "Oldest realm"},
            ],
        })
    if stage_name == "history":
        return json.dumps({
            "eras": [
                {"era_name": "Age of Formation", "duration": "10,000 years",
                 "description": "When cultivation first emerged"},
                {"era_name": "War of Spirals", "duration": "500 years",
                 "description": "Disciplines fought for dominance"},
                {"era_name": "Current Era", "duration": "200 years",
                 "description": "Uneasy peace after the Pact"},
            ],
            "events": [
                {"name": "The First Spiral", "era": "Age of Formation",
                 "description": "Discovery of spiral cultivation"},
                {"name": "Void Incursion", "era": "War of Spirals",
                 "description": "Entities breached the barrier"},
                {"name": "The Pact of Tides", "era": "Current Era",
                 "description": "Major factions agreed to non-aggression"},
            ],
            "key_figures": [
                {"name": "Sage Lianyu", "era": "Age of Formation",
                 "role": "First Sovereign", "legacy": "Created the spiral method"},
                {"name": "Void Empress Xue", "era": "War of Spirals",
                 "role": "Conqueror", "legacy": "Sealed the breach"},
            ],
        })
    if stage_name == "current_state":
        return json.dumps({
            "active_conflicts": [
                {"name": "Sect Cold War", "parties": ["Azure Sect", "Shadow Court"],
                 "description": "Covert operations escalating", "stakes": "Control of ley lines"},
            ],
            "political_landscape": "Fragile peace between three major powers",
            "power_balance": "Azure Sect dominant but weakening",
        })
    if stage_name == "protagonist":
        return json.dumps({
            "name": "Lin Feng",
            "age": 17,
            "background": "Orphan from the Iron Wastes with a damaged meridian system",
            "personality": {
                "core_traits": ["determined", "curious"],
                "flaws": ["reckless", "distrustful"],
                "strengths": ["adaptable", "perceptive"],
                "fears": ["abandonment", "powerlessness"],
                "desires": ["strength", "belonging"],
            },
            "starting_power": {"current_rank": "Rank 1", "discipline": "Body Refinement"},
            "disadvantage": "Damaged meridians limit Qi flow",
            "unusual_trait": "Can perceive Void energy despite having no affinity",
            "hidden_connection": "Parent was a Sovereign who fell",
            "motivation": {
                "surface_motivation": "Survive and grow stronger",
                "deep_motivation": "Discover the truth about family",
            },
            "initial_circumstances": "Enters Azure Sect outer disciples",
            "arc_trajectory": "From nobody to someone who matters",
        })
    if stage_name == "antagonists":
        return json.dumps({
            "antagonists": [
                {"name": "Elder Shen", "role": "Corrupt authority",
                 "power_level": "Rank 5", "motivation": "Maintain control"},
                {"name": "The Hollow King", "role": "Arc villain",
                 "power_level": "Rank 7", "motivation": "Open the Void gate"},
            ],
        })
    # supporting_cast
    return json.dumps({
        "characters": [
            {"name": "Wei Mei", "role": "Mentor figure",
             "connection_to_protagonist": "Sect elder who sees potential"},
            {"name": "Zhu Ling", "role": "Rival/friend",
             "connection_to_protagonist": "Fellow disciple"},
            {"name": "Old Bones", "role": "Comic relief / info broker",
             "connection_to_protagonist": "Marketplace contact"},
        ],
    })


def _narrative_analysis_json(*, tension: float = 0.6) -> str:
    return json.dumps({
        "key_events": [
            {"description": "Lin Feng discovers the spiral chamber",
             "emotional_beat": "wonder", "characters_involved": ["Lin Feng"],
             "narrative_importance": "major"},
        ],
        "overall_emotional_arc": "From trepidation to determination",
        "tension_level": tension,
        "tension_phase": "buildup",
        "new_foreshadowing_seeds": [
            {"description": "A crack in the chamber ceiling glows faintly",
             "seed_type": "mystery", "target_scope_tier": 2, "subtlety": "subtle"},
        ],
        "foreshadowing_references": [],
        "bible_entries_to_extract": [
            {"entry_type": "location_detail",
             "content": "The spiral chamber is beneath the outer courtyard",
             "entity_types": ["location"], "entity_names": ["Spiral Chamber"],
             "is_public_knowledge": False},
        ],
        "cliffhanger_description": "The chamber begins to hum",
    })


def _system_analysis_json(*, approved: bool = True, score: float = 0.8) -> str:
    """Build system analysis JSON. If approved=False, score should be < 0.5."""
    return json.dumps({
        "power_events": [],
        "earned_power_evaluations": [],
        "ability_usages": [],
        "consistency_issues": [],
        "chekhov_interactions": [],
        "has_critical_violations": not approved,
    })


def _chapter_plan_result_json(chapter_number: int = 1) -> str:
    """Valid ChapterPlanResult JSON for auto-chapter-planning calls."""
    return json.dumps({
        "title": f"Chapter {chapter_number}",
        "scenes": [
            {"description": "Opening scene", "beats": ["Intro"], "emotional_trajectory": "rising"},
        ],
        "target_tension": 0.5,
    })


def _system_analysis_with_rejection_json() -> str:
    """System analysis with an earned power rejection (score 0.3 < 0.5)."""
    return json.dumps({
        "power_events": [
            {"character_name": "Lin Feng", "event_type": "rank_up",
             "description": "Lin Feng suddenly reaches Rank 3",
             "struggle_context": "No real struggle shown",
             "sacrifice_or_cost": None, "foundation": "Minimal",
             "narrative_buildup_chapters": [], "new_rank": "Rank 3"},
        ],
        "earned_power_evaluations": [
            {"character_name": "Lin Feng",
             "event_description": "Jumped from Rank 1 to Rank 3 in one chapter",
             "struggle_score": 0.05, "struggle_reasoning": "No struggle shown",
             "foundation_score": 0.05, "foundation_reasoning": "No foundation laid",
             "cost_score": 0.10, "cost_reasoning": "Minor cost",
             "buildup_score": 0.10, "buildup_reasoning": "Minimal buildup",
             "total_score": 0.30, "approved": False,
             "reasoning": "Power gain is completely unearned"},
        ],
        "ability_usages": [],
        "consistency_issues": [],
        "chekhov_interactions": [],
        "has_critical_violations": True,
    })


def _arc_plan_json(start: int = 1, end: int = 5) -> str:
    return json.dumps({
        "title": "The Outer Disciple Trials",
        "description": "Lin Feng proves himself in the sect entrance trials",
        "target_chapter_start": start,
        "target_chapter_end": end,
        "key_events": [
            {"event_order": 1, "description": "Trial begins",
             "chapter_target": start, "characters_involved": ["Lin Feng"]},
        ],
        "character_arcs": [
            {"character_name": "Lin Feng", "arc_goal": "Pass the trial",
             "starting_state": "Nervous outer disciple",
             "ending_state": "Confident inner candidate"},
        ],
        "themes": [
            {"theme": "Perseverance", "how_explored": "Through escalating challenges"},
        ],
    })


# ═══════════════════════════════════════════════════════════════════════════
# Mock LLM builder
# ═══════════════════════════════════════════════════════════════════════════


def _build_mock_llm(
    session_factory: async_sessionmaker,
    settings: Settings,
    *,
    generate_side_effects: list[LLMResponse] | None = None,
) -> LLMProvider:
    """Build an LLMProvider with a mocked generate method.

    Uses the real BudgetChecker (which hits the DB), but mocks LLM calls.
    """
    llm = LLMProvider(settings, session_factory)

    if generate_side_effects is not None:
        llm.generate = AsyncMock(side_effect=generate_side_effects)
    else:
        llm.generate = AsyncMock(return_value=_llm_response("mock"))

    return llm


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 1: World generation (8-stage pipeline)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_world_generation(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Create novel → generate world (8-stage pipeline) → verify world data populates."""
    novel_id = seed_data["novel_id"]
    user_id = seed_data["user_id"]

    # Build 8 LLM responses for world stages + 1 for synopsis
    stage_responses = [
        _llm_response(_cosmology_json()),
        _llm_response(_power_system_json()),
        _llm_response(_generic_stage_json("geography")),
        _llm_response(_generic_stage_json("history")),
        _llm_response(_generic_stage_json("current_state")),
        _llm_response(_generic_stage_json("protagonist")),
        _llm_response(_generic_stage_json("antagonists")),
        _llm_response(_generic_stage_json("supporting_cast")),
        _llm_response("A young orphan discovers spiral cultivation."),  # synopsis
    ]

    llm = _build_mock_llm(session_factory, e2e_settings, generate_side_effects=stage_responses)
    pipeline = StoryPipeline(llm, session_factory, e2e_settings, mock_redis)

    # Run world generation
    result = await pipeline.generate_world(novel_id, user_id, tag_overrides=[])

    # Verify success
    assert result.success is True
    assert len(result.stages_completed) == 8
    assert "cosmology" in result.stages_completed
    assert "supporting_cast" in result.stages_completed

    # Verify DB state
    async with session_factory() as session:
        # All 8 world building stages should be stored
        stages = (await session.execute(
            select(WorldBuildingStage)
            .where(WorldBuildingStage.novel_id == novel_id)
            .order_by(WorldBuildingStage.stage_order)
        )).scalars().all()
        assert len(stages) == 8
        assert all(s.status == "complete" for s in stages)
        assert stages[0].stage_name == "cosmology"
        assert stages[7].stage_name == "supporting_cast"

        # Parsed data should be populated
        cosmo_data = stages[0].parsed_data
        assert "fundamental_forces" in cosmo_data
        assert len(cosmo_data["fundamental_forces"]) == 2

        ps_data = stages[1].parsed_data
        assert ps_data["system_name"] == "Spiral Cultivation"

        # Generation job should be complete
        jobs = (await session.execute(
            select(GenerationJob)
            .where(GenerationJob.novel_id == novel_id)
        )).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].status == "completed"
        assert jobs[0].job_type == "world_generation"

    # LLM was called 8 times for world stages + 1 for synopsis
    assert llm.generate.call_count == 9

    # Characters should be seeded from world data
    async with session_factory() as session:
        chars = (await session.execute(
            select(Character)
            .where(Character.novel_id == novel_id)
            .order_by(Character.id)
        )).scalars().all()

        assert len(chars) == 6  # 1 protagonist + 2 antagonists + 3 supporting

        protagonist = [c for c in chars if c.role == "protagonist"]
        assert len(protagonist) == 1
        assert protagonist[0].name == "Lin Feng"

        antagonists = [c for c in chars if c.role == "antagonist"]
        assert len(antagonists) == 2
        assert {a.name for a in antagonists} == {"Elder Shen", "The Hollow King"}

        supporting = [c for c in chars if c.role == "supporting"]
        assert len(supporting) == 3
        assert {s.name for s in supporting} == {"Wei Mei", "Zhu Ling", "Old Bones"}


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 2: Arc plan → approve → generate chapter
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_arc_plan_approve_generate_chapter(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Plan arc → approve → generate chapter → verify SSE-compatible + chapter saved."""
    novel_id = seed_data["novel_id"]
    user_id = seed_data["user_id"]

    # 1. Plan an arc
    arc_llm = _build_mock_llm(
        session_factory, e2e_settings,
        generate_side_effects=[_llm_response(_arc_plan_json())],
    )
    planner = StoryPlanner(arc_llm, e2e_settings)

    async with session_factory() as session:
        arc = await planner.plan_next_arc(session, novel_id, user_id)
        await session.commit()

    assert arc.status == "proposed"
    assert arc.title == "The Outer Disciple Trials"
    arc_id = arc.id

    # 2. Approve the arc (creates chapter plans)
    async with session_factory() as session:
        plans = await planner.approve_arc(session, arc_id)
        await session.commit()

    assert len(plans) == 5  # chapters 1-5
    assert plans[0].chapter_number == 1

    # 3. Generate chapter 1
    # The pipeline calls: plan_chapter (auto-detail) → generate → analyze
    # (narrative + system concurrently). Provide responses in that order.
    chapter_responses = [
        # Auto chapter planning (fill in scene_outline for stub plan)
        _llm_response(_chapter_plan_result_json(1)),
        # Chapter generation
        _llm_response("Lin Feng stood at the gates of the Azure Sect. " * 50),
        # Narrative analysis (may be consumed first in concurrent gather)
        _llm_response(_narrative_analysis_json()),
        # System analysis
        _llm_response(_system_analysis_json()),
    ]
    chapter_llm = _build_mock_llm(
        session_factory, e2e_settings,
        generate_side_effects=chapter_responses,
    )
    pipeline = StoryPipeline(chapter_llm, session_factory, e2e_settings, mock_redis)
    chapter_result = await pipeline.generate_chapter(novel_id, 1, user_id)

    # Verify chapter result
    assert chapter_result.success is True
    assert chapter_result.chapter_id is not None
    assert chapter_result.flagged_for_review is False
    assert "Lin Feng" in chapter_result.chapter_text

    # Verify DB state
    async with session_factory() as session:
        chapter = (await session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id, Chapter.chapter_number == 1)
        )).scalar_one()
        assert chapter.status == "published"
        assert chapter.word_count > 0

        # Draft should exist
        drafts = (await session.execute(
            select(ChapterDraft).where(ChapterDraft.novel_id == novel_id)
        )).scalars().all()
        assert len(drafts) >= 1

        # Tension tracker should be populated from narrative analysis
        tension = (await session.execute(
            select(TensionTracker).where(TensionTracker.novel_id == novel_id)
        )).scalar_one_or_none()
        assert tension is not None
        assert tension.tension_level == pytest.approx(0.6, abs=0.01)

        # Foreshadowing seed should be extracted
        seeds = (await session.execute(
            select(ForeshadowingSeed).where(ForeshadowingSeed.novel_id == novel_id)
        )).scalars().all()
        assert len(seeds) >= 1
        assert seeds[0].seed_type == "mystery"

        # Story bible entry should be extracted
        bible = (await session.execute(
            select(StoryBibleEntry).where(StoryBibleEntry.novel_id == novel_id)
        )).scalars().all()
        assert len(bible) >= 1

        # Generation jobs: 1 for chapter
        chapter_jobs = (await session.execute(
            select(GenerationJob)
            .where(
                GenerationJob.novel_id == novel_id,
                GenerationJob.job_type == "chapter_generation",
            )
        )).scalars().all()
        assert len(chapter_jobs) == 1
        assert chapter_jobs[0].status == "completed"


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 3: Reader-triggered generation within approved arc
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_reader_triggered_generation(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Reader triggers generation via the worker task wrapper."""
    novel_id = seed_data["novel_id"]
    user_id = seed_data["user_id"]

    # Pre-populate an approved arc + chapter plan
    async with session_factory() as session:
        arc = ArcPlan(
            novel_id=novel_id, arc_number=1,
            title="Trial Arc", description="Trials begin",
            target_chapter_start=1, target_chapter_end=3,
            planned_chapters=3, status="approved",
            key_events=[], character_arcs=[], themes=[],
        )
        session.add(arc)
        await session.flush()

        plan = ChapterPlan(
            arc_plan_id=arc.id, novel_id=novel_id,
            chapter_number=1, title="The First Trial",
            status="planned",
        )
        session.add(plan)
        await session.commit()

    # Build worker task context
    # Pipeline calls: plan_chapter (auto-detail) → generate → analyze (narrative + system)
    chapter_responses = [
        _llm_response(_chapter_plan_result_json(1)),
        _llm_response("The trial grounds trembled as Lin Feng stepped forward. " * 50),
        _llm_response(_narrative_analysis_json()),
        _llm_response(_system_analysis_json()),
    ]
    llm = _build_mock_llm(session_factory, e2e_settings, generate_side_effects=chapter_responses)
    pipeline = StoryPipeline(llm, session_factory, e2e_settings, mock_redis)

    ctx = {
        "settings": e2e_settings,
        "session_factory": session_factory,
        "llm": llm,
        "redis": mock_redis,
        "pipeline": pipeline,
    }

    # Call the worker task directly (simulating reader trigger)
    result = await generate_chapter_task(
        ctx,
        novel_id=novel_id,
        chapter_number=1,
        user_id=user_id,
        job_id="reader-gen-1",
    )

    assert result["success"] is True
    assert result["chapter_id"] is not None
    assert result["chapter_text_length"] > 0

    # Redis lock was acquired and released
    mock_redis.set.assert_called()
    mock_redis.delete.assert_called()


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 4: Regeneration with author guidance
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_regeneration_with_guidance(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Author requests regeneration with guidance → new draft created."""
    novel_id = seed_data["novel_id"]
    user_id = seed_data["user_id"]

    # Set up: create initial chapter + draft
    async with session_factory() as session:
        chapter = Chapter(
            novel_id=novel_id, chapter_number=1,
            title="Chapter 1", chapter_text="Original text.",
            word_count=2, status="published",
        )
        session.add(chapter)

        draft = ChapterDraft(
            novel_id=novel_id, chapter_number=1,
            draft_number=1, chapter_text="Original text.",
            word_count=2, model_used="test-model", status="published",
        )
        session.add(draft)

        plan = ChapterPlan(
            novel_id=novel_id, chapter_number=1,
            title="Chapter 1", status="planned",
        )
        session.add(plan)
        await session.commit()

    # LLM responses for regeneration (generate only, no analysis in regenerate_chapter)
    regen_responses = [
        _llm_response(
            "Lin Feng gripped the sword tighter, remembering his mentor's words. " * 50
        ),
    ]
    llm = _build_mock_llm(session_factory, e2e_settings, generate_side_effects=regen_responses)
    pipeline = StoryPipeline(llm, session_factory, e2e_settings, mock_redis)

    result = await pipeline.regenerate_chapter(
        novel_id, 1,
        guidance="Make the scene more emotionally intense. Show Lin Feng's internal conflict.",
        user_id=user_id,
    )

    assert result.success is True
    assert result.draft_number == 2  # Should be draft 2
    assert "mentor" in result.chapter_text

    # Verify DB: now has 2 drafts
    async with session_factory() as session:
        drafts = (await session.execute(
            select(ChapterDraft)
            .where(
                ChapterDraft.novel_id == novel_id,
                ChapterDraft.chapter_number == 1,
            )
            .order_by(ChapterDraft.draft_number)
        )).scalars().all()
        assert len(drafts) == 2
        assert drafts[0].draft_number == 1
        assert drafts[1].draft_number == 2

    # LLM generate was called once (regeneration goes through ChapterGenerator
    # which builds the prompt internally and appends guidance to the user field)
    assert llm.generate.call_count == 1
    # The guidance was passed through — verify via the generate call's 'user' kwarg
    call_args = llm.generate.call_args
    user_prompt = call_args.kwargs.get("user", "")
    assert "REVISION GUIDANCE" in user_prompt
    assert "internal conflict" in user_prompt


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 5: Earned power rejection → auto-retry → flag for review
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_earned_power_rejection_and_flag(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Chapter with unearned power → rejected → auto-retry → still fails → flagged."""
    novel_id = seed_data["novel_id"]
    user_id = seed_data["user_id"]

    # Set up arc plan + chapter plan (pre-populated to avoid arc auto-planning)
    async with session_factory() as session:
        arc = ArcPlan(
            novel_id=novel_id, arc_number=1,
            title="Power Arc", description="Power events",
            target_chapter_start=1, target_chapter_end=5,
            planned_chapters=5, status="approved",
            key_events=[], character_arcs=[], themes=[],
        )
        session.add(arc)
        await session.flush()

        plan = ChapterPlan(
            arc_plan_id=arc.id, novel_id=novel_id,
            chapter_number=1,
            title="The Sudden Power", status="planned",
        )
        session.add(plan)
        await session.commit()

    # LLM responses:
    # 0. Auto chapter planning (fill in scene_outline for stub plan)
    # 1. First generation (draft 1)
    # 2. Narrative analysis (draft 1) — passes
    # 3. System analysis (draft 1) — FAILS earned power check
    # 4. Retry generation (draft 2)
    # 5. Narrative analysis (draft 2) — passes
    # 6. System analysis (draft 2) — STILL fails
    responses = [
        # Auto chapter planning
        _llm_response(_chapter_plan_result_json(1)),
        # Draft 1
        _llm_response("Lin Feng suddenly became a Rank 3 cultivator. " * 50),
        _llm_response(_narrative_analysis_json()),
        _llm_response(_system_analysis_with_rejection_json()),
        # Draft 2 (retry)
        _llm_response("Despite his efforts, Lin Feng's power surged uncontrollably. " * 50),
        _llm_response(_narrative_analysis_json()),
        _llm_response(_system_analysis_with_rejection_json()),
    ]

    llm = _build_mock_llm(session_factory, e2e_settings, generate_side_effects=responses)
    pipeline = StoryPipeline(llm, session_factory, e2e_settings, mock_redis)
    result = await pipeline.generate_chapter(novel_id, 1, user_id)

    # Chapter was created but flagged
    assert result.success is True  # Chapter still gets saved
    assert result.flagged_for_review is True
    assert result.draft_number == 2
    assert result.validation is not None
    assert result.validation.passed is False

    # Verify DB state
    async with session_factory() as session:
        chapter = (await session.execute(
            select(Chapter)
            .where(Chapter.novel_id == novel_id, Chapter.chapter_number == 1)
        )).scalar_one()
        assert chapter.status == "review"  # Flagged for review

        # Should have 2 drafts
        drafts = (await session.execute(
            select(ChapterDraft)
            .where(ChapterDraft.novel_id == novel_id)
            .order_by(ChapterDraft.draft_number)
        )).scalars().all()
        assert len(drafts) == 2
        assert drafts[0].status == "rejected"
        assert drafts[1].status == "flagged"

    # LLM called 7 times: plan, gen, narr, sys, gen-retry, narr, sys
    assert llm.generate.call_count == 7


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 6: Budget enforcement
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_budget_enforcement(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Chapter generation rejected when budget is exhausted."""
    novel_id = seed_data["novel_id"]
    user_id = seed_data["user_id"]

    # Exhaust the author's budget
    async with session_factory() as session:
        profile = (await session.execute(
            select(AuthorProfile)
            .where(AuthorProfile.user_id == user_id)
        )).scalar_one()
        profile.api_spent_cents = profile.api_budget_cents  # fully spent
        await session.commit()

    # Try to generate — pipeline catches BudgetExceededError internally
    llm = _build_mock_llm(session_factory, e2e_settings)
    pipeline = StoryPipeline(llm, session_factory, e2e_settings, mock_redis)

    result = await pipeline.generate_chapter(novel_id, 1, user_id)

    # Pipeline does NOT re-raise BudgetExceededError; it sets result.error
    assert result.success is False
    assert "budget" in result.error.lower()

    # Verify the generation job was created and marked as failed
    async with session_factory() as session:
        jobs = (await session.execute(
            select(GenerationJob)
            .where(GenerationJob.novel_id == novel_id)
        )).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].status == "failed"
        assert "budget" in jobs[0].error_message.lower()

    # LLM.generate was never called (budget check happens first in pipeline)
    llm.generate.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 7: Autonomous mode tick
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_autonomous_tick(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Autonomous mode tick → generates chapter for eligible novel."""
    novel_id = seed_data["novel_id"]

    # Enable autonomous mode on the novel
    async with session_factory() as session:
        novel = (await session.execute(
            select(Novel).where(Novel.id == novel_id)
        )).scalar_one()
        novel.status = "writing"

        ns = (await session.execute(
            select(NovelSettings).where(NovelSettings.novel_id == novel_id)
        )).scalar_one()
        ns.autonomous_generation_enabled = True
        ns.autonomous_cadence_hours = 1
        ns.last_autonomous_generation_at = None  # Never run before
        await session.commit()

    # Build mock LLM and pipeline for autonomous tick
    chapter_responses = [
        _llm_response("The dawn broke over the cultivation grounds. " * 50),
        _llm_response(_narrative_analysis_json()),
        _llm_response(_system_analysis_json()),
    ]
    llm = _build_mock_llm(session_factory, e2e_settings, generate_side_effects=chapter_responses)
    pipeline = StoryPipeline(llm, session_factory, e2e_settings, mock_redis)

    ctx = {
        "settings": e2e_settings,
        "session_factory": session_factory,
        "llm": llm,
        "redis": mock_redis,
        "pipeline": pipeline,
    }

    result = await autonomous_tick_task(ctx)

    assert result["checked"] == 1
    assert result["enqueued"] == 1
    assert result["skipped"] == 0

    # The autonomous tick enqueues a chapter generation task but does NOT
    # execute it inline — verify the enqueue happened and timestamp updated.
    mock_redis.enqueue_job.assert_called_once()
    call_kwargs = mock_redis.enqueue_job.call_args
    assert call_kwargs[0][0] == "generate_chapter_task"

    # Autonomous timestamp was updated
    async with session_factory() as session:
        ns = (await session.execute(
            select(NovelSettings).where(NovelSettings.novel_id == novel_id)
        )).scalar_one()
        assert ns.last_autonomous_generation_at is not None


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 7b: Autonomous tick skips when cadence not met
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_autonomous_tick_skips_cadence(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Autonomous tick skips novel when cadence hasn't elapsed."""
    novel_id = seed_data["novel_id"]

    # Enable autonomous but set last generation to very recently
    async with session_factory() as session:
        novel = (await session.execute(
            select(Novel).where(Novel.id == novel_id)
        )).scalar_one()
        novel.status = "writing"

        ns = (await session.execute(
            select(NovelSettings).where(NovelSettings.novel_id == novel_id)
        )).scalar_one()
        ns.autonomous_generation_enabled = True
        ns.autonomous_cadence_hours = 24
        # Use naive datetime for SQLite compatibility
        ns.last_autonomous_generation_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()

    llm = _build_mock_llm(session_factory, e2e_settings)
    pipeline = StoryPipeline(llm, session_factory, e2e_settings, mock_redis)

    ctx = {
        "settings": e2e_settings,
        "session_factory": session_factory,
        "llm": llm,
        "redis": mock_redis,
        "pipeline": pipeline,
    }

    result = await autonomous_tick_task(ctx)

    assert result["checked"] == 1
    assert result["skipped"] == 1
    assert result["enqueued"] == 0

    # LLM was never called
    llm.generate.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO: World generation worker task wrapper
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_world_generation_worker_task(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Exercise generate_world_task worker wrapper end-to-end."""
    novel_id = seed_data["novel_id"]
    user_id = seed_data["user_id"]

    stage_responses = [
        _llm_response(_cosmology_json()),
        _llm_response(_power_system_json()),
        _llm_response(_generic_stage_json("geography")),
        _llm_response(_generic_stage_json("history")),
        _llm_response(_generic_stage_json("current_state")),
        _llm_response(_generic_stage_json("protagonist")),
        _llm_response(_generic_stage_json("antagonists")),
        _llm_response(_generic_stage_json("supporting_cast")),
        _llm_response("A young orphan discovers spiral cultivation."),  # synopsis
    ]

    llm = _build_mock_llm(session_factory, e2e_settings, generate_side_effects=stage_responses)
    pipeline = StoryPipeline(llm, session_factory, e2e_settings, mock_redis)

    ctx = {
        "settings": e2e_settings,
        "session_factory": session_factory,
        "llm": llm,
        "redis": mock_redis,
        "pipeline": pipeline,
    }

    result = await generate_world_task(ctx, novel_id=novel_id, user_id=user_id)

    assert result["success"] is True
    assert len(result["stages_completed"]) == 8

    # Progress was reported
    mock_redis.publish.assert_called()


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO: Concurrent lock rejection
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_concurrent_generation_lock(
    e2e_settings, session_factory, seed_data, mock_redis,
):
    """Second generation attempt is rejected when lock is held."""
    novel_id = seed_data["novel_id"]
    user_id = seed_data["user_id"]

    # Redis returns False for lock (already held)
    mock_redis.set = AsyncMock(return_value=False)

    llm = _build_mock_llm(session_factory, e2e_settings)
    pipeline = StoryPipeline(llm, session_factory, e2e_settings, mock_redis)
    result = await pipeline.generate_chapter(novel_id, 1, user_id)

    assert result.success is False
    assert "already in progress" in result.error

    # LLM was never called
    llm.generate.assert_not_called()
