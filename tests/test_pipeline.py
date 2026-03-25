"""Tests for the story pipeline orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    AuthorProfile,
    ChapterImage,
    Character,
    Novel,
    NovelSeed,
    User,
)
from aiwebnovel.llm.provider import BudgetExceededError, LLMProvider, LLMResponse
from aiwebnovel.story.analyzer import AnalysisResult
from aiwebnovel.story.pipeline import StoryPipeline
from aiwebnovel.story.validator import ValidationResult


@pytest.fixture()
def mock_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="test-secret",
        litellm_default_model="test-model",
        context_window_cap=10000,
    )


@pytest.fixture()
def mock_llm_response() -> LLMResponse:
    return LLMResponse(
        content='{"test": "data"}',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_cents=0.01,
        duration_ms=500,
    )


@pytest.fixture()
def mock_llm(mock_settings: Settings, mock_llm_response: LLMResponse) -> LLMProvider:
    llm = MagicMock(spec=LLMProvider)
    llm.settings = mock_settings
    llm.estimate_tokens = MagicMock(return_value=100)
    llm.generate = AsyncMock(return_value=mock_llm_response)
    llm.generate_stream = AsyncMock()
    llm.budget_checker = MagicMock()
    llm.budget_checker.check_llm_budget = AsyncMock()
    return llm


@pytest.fixture()
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    return redis


async def _seed_novel(session: AsyncSession) -> int:
    """Create minimal novel + author for testing."""
    user = User(
        id=1,
        email="test@test.com",
        role="author",
        is_anonymous=False,
        hashed_password="hashed",
    )
    session.add(user)
    await session.flush()

    profile = AuthorProfile(
        user_id=user.id,
        api_budget_cents=10000,
        api_spent_cents=0,
    )
    session.add(profile)

    novel = Novel(
        author_id=user.id,
        title="Test Novel",
        status="writing",
    )
    session.add(novel)
    await session.flush()
    return novel.id


def _make_mock_waves():
    """Build mock WORLD_WAVES with no-parser templates for testing.

    Returns (original_waves, patched_waves) where patched_waves mirrors the
    real 3-wave structure but uses MagicMock templates with response_parser=None.
    """
    from aiwebnovel.story import world_generator as wg_mod

    original_waves = wg_mod.WORLD_WAVES

    # Reconstruct mock waves preserving the real wave grouping
    patched_waves = []
    for wave in original_waves:
        patched_wave = [
            (name, MagicMock(
                response_parser=None,
                temperature=0.7,
                max_tokens=4000,
                render=MagicMock(return_value=("system", "user")),
            ), order)
            for name, _, order in wave
        ]
        patched_waves.append(patched_wave)

    return original_waves, patched_waves


def _world_gen_patches():
    """Context-manager-compatible patches for WorldGenerator dependencies.

    Returns a dict of patch objects that should be started/stopped or used
    in a ``with`` block.
    """
    return {
        "anti_rep": patch(
            "aiwebnovel.story.world_generator.build_anti_repetition_directives",
            new_callable=AsyncMock,
            return_value="",
        ),
        "char_ids": patch(
            "aiwebnovel.story.names.generate_character_identities_with_db",
            new_callable=AsyncMock,
            return_value={"protagonist": [], "antagonist": [], "supporting": []},
        ),
        "fmt_ids": patch(
            "aiwebnovel.story.names.format_identities_for_prompt",
            return_value="",
        ),
    }


class TestGenerateWorld:
    """Test world generation pipeline."""

    @pytest.mark.asyncio
    async def test_8_stages_called_in_order(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Verify all 8 world stages are called in order with accumulated context."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from aiwebnovel.story import world_generator as wg_mod

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        # Seed data
        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        # Just return generic JSON; pipeline will parse via response_format
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                content='{}',
                model="test-model",
                prompt_tokens=100,
                completion_tokens=50,
                cost_cents=0.01,
                duration_ms=500,
            )
        )

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings)
        original_waves, patched_waves = _make_mock_waves()
        extra = _world_gen_patches()

        wg_mod.WORLD_WAVES = patched_waves
        try:
            with (
                patch.object(
                    pipeline.context_assembler,
                    'build_world_context',
                    new_callable=AsyncMock,
                    return_value={"prior_context": "", "stages_completed": []},
                ),
                patch.object(
                    pipeline._title_generator,
                    'generate_title_and_synopsis',
                    new_callable=AsyncMock,
                ),
                patch.object(
                    pipeline._character_seeder,
                    'seed_characters_from_world',
                    new_callable=AsyncMock,
                ),
                extra["anti_rep"],
                extra["char_ids"],
                extra["fmt_ids"],
            ):
                result = await pipeline.generate_world(novel_id, user_id=1)

                assert result.success
                assert len(result.stages_completed) == 8
                assert mock_llm.generate.call_count == 8
        finally:
            wg_mod.WORLD_WAVES = original_waves

    @pytest.mark.asyncio
    async def test_world_context_accumulates(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Verify each wave accumulates context from prior waves."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from aiwebnovel.story import world_generator as wg_mod

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        # Track build_world_context calls (one per wave with the min stage_order)
        ctx_calls = []

        async def track_ctx(session, novel_id, stage_order):
            ctx_calls.append(stage_order)
            return {"prior_context": f"context up to {stage_order}", "stages_completed": []}

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings)
        original_waves, patched_waves = _make_mock_waves()
        extra = _world_gen_patches()

        wg_mod.WORLD_WAVES = patched_waves
        try:
            with (
                patch.object(
                    pipeline.context_assembler,
                    'build_world_context',
                    side_effect=track_ctx,
                ),
                patch.object(
                    pipeline._title_generator,
                    'generate_title_and_synopsis',
                    new_callable=AsyncMock,
                ),
                patch.object(
                    pipeline._character_seeder,
                    'seed_characters_from_world',
                    new_callable=AsyncMock,
                ),
                extra["anti_rep"],
                extra["char_ids"],
                extra["fmt_ids"],
            ):
                await pipeline.generate_world(novel_id, user_id=1)

            # build_world_context is called once per wave with the
            # minimum stage_order in that wave: 0, 3, 5
            assert ctx_calls == [0, 3, 5]
        finally:
            wg_mod.WORLD_WAVES = original_waves


class TestConfirmedSeeds:
    """Test that generate_world() uses confirmed NovelSeed rows from DB."""

    @pytest.mark.asyncio
    async def test_uses_confirmed_seeds_from_db(
        self, db_engine, mock_llm, mock_settings,
    ):
        """When confirmed NovelSeed rows exist, they replace select_seeds()."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from aiwebnovel.story import world_generator as wg_mod

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            # Insert confirmed seeds
            session.add(NovelSeed(
                novel_id=novel_id,
                seed_id="protag_elderly",
                seed_category="protagonist_archetype",
                seed_text="The protagonist is over 60 years old.",
                status="confirmed",
            ))
            session.add(NovelSeed(
                novel_id=novel_id,
                seed_id="protag_child",
                seed_category="protagonist_archetype",
                seed_text="The protagonist is 8-12 years old.",
                status="confirmed",
            ))
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings)
        original_waves, patched_waves = _make_mock_waves()
        extra = _world_gen_patches()

        wg_mod.WORLD_WAVES = patched_waves
        try:
            with (
                patch.object(
                    pipeline.context_assembler,
                    'build_world_context',
                    new_callable=AsyncMock,
                    return_value={"prior_context": "", "stages_completed": []},
                ),
                patch(
                    "aiwebnovel.story.world_generator.select_seeds",
                ) as mock_select,
                patch.object(
                    pipeline._title_generator,
                    'generate_title_and_synopsis',
                    new_callable=AsyncMock,
                ),
                patch.object(
                    pipeline._character_seeder,
                    'seed_characters_from_world',
                    new_callable=AsyncMock,
                ),
                extra["anti_rep"],
                extra["char_ids"],
                extra["fmt_ids"],
            ):
                result = await pipeline.generate_world(
                    novel_id, user_id=1,
                )

            assert result.success
            # select_seeds should NOT have been called
            mock_select.assert_not_called()
        finally:
            wg_mod.WORLD_WAVES = original_waves

    @pytest.mark.asyncio
    async def test_falls_back_to_select_seeds_when_no_confirmed(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Legacy novels with no NovelSeed rows fall back to select_seeds()."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from aiwebnovel.story import world_generator as wg_mod

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings)
        original_waves, patched_waves = _make_mock_waves()
        extra = _world_gen_patches()

        from aiwebnovel.story.seeds import DiversitySeed
        fallback_seed = DiversitySeed(
            id="fallback_seed",
            category="test",
            text="Fallback text",
        )

        wg_mod.WORLD_WAVES = patched_waves
        try:
            with (
                patch.object(
                    pipeline.context_assembler,
                    'build_world_context',
                    new_callable=AsyncMock,
                    return_value={"prior_context": "", "stages_completed": []},
                ),
                patch(
                    "aiwebnovel.story.world_generator.select_seeds",
                    return_value=[fallback_seed],
                ) as mock_select,
                patch.object(
                    pipeline._title_generator,
                    'generate_title_and_synopsis',
                    new_callable=AsyncMock,
                ),
                patch.object(
                    pipeline._character_seeder,
                    'seed_characters_from_world',
                    new_callable=AsyncMock,
                ),
                extra["anti_rep"],
                extra["char_ids"],
                extra["fmt_ids"],
            ):
                result = await pipeline.generate_world(
                    novel_id, user_id=1,
                )

            assert result.success
            mock_select.assert_called_once()
        finally:
            wg_mod.WORLD_WAVES = original_waves

    @pytest.mark.asyncio
    async def test_ignores_proposed_and_rejected_seeds(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Only confirmed seeds are used; proposed/rejected are ignored."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from aiwebnovel.story import world_generator as wg_mod

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            session.add(NovelSeed(
                novel_id=novel_id,
                seed_id="protag_elderly",
                seed_category="protagonist_archetype",
                seed_text="Elderly protagonist",
                status="proposed",
            ))
            session.add(NovelSeed(
                novel_id=novel_id,
                seed_id="protag_child",
                seed_category="protagonist_archetype",
                seed_text="Child protagonist",
                status="rejected",
            ))
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings)
        original_waves, patched_waves = _make_mock_waves()
        extra = _world_gen_patches()

        from aiwebnovel.story.seeds import DiversitySeed
        fallback_seed = DiversitySeed(id="fb", category="test", text="Fallback")

        wg_mod.WORLD_WAVES = patched_waves
        try:
            with (
                patch.object(
                    pipeline.context_assembler,
                    'build_world_context',
                    new_callable=AsyncMock,
                    return_value={"prior_context": "", "stages_completed": []},
                ),
                patch(
                    "aiwebnovel.story.world_generator.select_seeds",
                    return_value=[fallback_seed],
                ) as mock_select,
                patch.object(
                    pipeline._title_generator,
                    'generate_title_and_synopsis',
                    new_callable=AsyncMock,
                ),
                patch.object(
                    pipeline._character_seeder,
                    'seed_characters_from_world',
                    new_callable=AsyncMock,
                ),
                extra["anti_rep"],
                extra["char_ids"],
                extra["fmt_ids"],
            ):
                result = await pipeline.generate_world(
                    novel_id, user_id=1,
                )

            assert result.success
            # No confirmed seeds -> falls back to select_seeds
            mock_select.assert_called_once()
        finally:
            wg_mod.WORLD_WAVES = original_waves

    @pytest.mark.asyncio
    async def test_reconstructs_seed_not_in_bank(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Seeds removed from SEED_BANK are reconstructed from stored fields."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from aiwebnovel.story import world_generator as wg_mod

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            session.add(NovelSeed(
                novel_id=novel_id,
                seed_id="deleted_seed_xyz",
                seed_category="exotic_category",
                seed_text="A seed that was removed from the bank.",
                status="confirmed",
            ))
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings)
        original_waves, patched_waves = _make_mock_waves()
        extra = _world_gen_patches()

        wg_mod.WORLD_WAVES = patched_waves
        try:
            with (
                patch.object(
                    pipeline.context_assembler,
                    'build_world_context',
                    new_callable=AsyncMock,
                    return_value={"prior_context": "", "stages_completed": []},
                ),
                patch(
                    "aiwebnovel.story.world_generator.select_seeds",
                ) as mock_select,
                patch(
                    "aiwebnovel.story.world_generator"
                    ".assemble_genre_conventions",
                ) as mock_assemble,
                patch.object(
                    pipeline._title_generator,
                    'generate_title_and_synopsis',
                    new_callable=AsyncMock,
                ),
                patch.object(
                    pipeline._character_seeder,
                    'seed_characters_from_world',
                    new_callable=AsyncMock,
                ),
                extra["anti_rep"],
                extra["char_ids"],
                extra["fmt_ids"],
            ):
                mock_assemble.return_value = "test conventions"
                result = await pipeline.generate_world(novel_id, user_id=1)

            assert result.success
            mock_select.assert_not_called()
            # Check the seed passed to assemble_genre_conventions
            call_kwargs = mock_assemble.call_args
            seeds = call_kwargs.kwargs.get("selected_seeds") or call_kwargs[1].get("selected_seeds")
            if seeds is None:
                seeds = call_kwargs[0][1]  # positional
            assert len(seeds) == 1
            assert seeds[0].id == "deleted_seed_xyz"
            assert seeds[0].category == "exotic_category"
            assert seeds[0].text == "A seed that was removed from the bank."
        finally:
            wg_mod.WORLD_WAVES = original_waves


class TestGenerateChapter:
    """Test chapter generation lifecycle."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, db_engine, mock_llm, mock_settings, mock_redis):
        """Verify all 10 pipeline steps execute in order."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings, mock_redis)

        # Mock sub-components
        mock_context = MagicMock()
        mock_context.sections = {}
        mock_context.total_tokens = 100
        mock_context.to_prompt.return_value = "test context"

        pipeline.context_assembler.build_chapter_context = AsyncMock(return_value=mock_context)
        pipeline.generator.generate = AsyncMock(return_value="Generated chapter text here.")
        pipeline.analyzer.analyze = AsyncMock(return_value=AnalysisResult(
            narrative_success=True, system_success=True,
        ))
        pipeline.validator.validate = AsyncMock(return_value=ValidationResult(passed=True))
        pipeline.extractor.extract_from_analysis = AsyncMock()

        result = await pipeline.generate_chapter(novel_id, 1, user_id=1)

        assert result.success
        assert result.chapter_text == "Generated chapter text here."
        assert result.chapter_id is not None

        # Verify sub-components were called
        pipeline.context_assembler.build_chapter_context.assert_awaited_once()
        pipeline.generator.generate.assert_awaited_once()
        pipeline.analyzer.analyze.assert_awaited_once()
        pipeline.validator.validate.assert_awaited_once()
        pipeline.extractor.extract_from_analysis.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejection_triggers_retry(
        self, db_engine, mock_llm, mock_settings, mock_redis,
    ):
        """Verify first rejection triggers a retry with guidance."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings, mock_redis)

        mock_context = MagicMock()
        mock_context.sections = {}
        mock_context.total_tokens = 100

        pipeline.context_assembler.build_chapter_context = AsyncMock(return_value=mock_context)
        pipeline.generator.generate = AsyncMock(return_value="Chapter text")

        # First validation fails, second passes
        failed_validation = ValidationResult(
            passed=False,
            retry_guidance="Fix the power advancement",
        )
        from aiwebnovel.story.validator import ValidationIssue
        failed_validation.issues.append(ValidationIssue(
            issue_type="earned_power",
            description="Unearned advancement",
            severity="critical",
        ))

        passed_validation = ValidationResult(passed=True)

        pipeline.analyzer.analyze = AsyncMock(return_value=AnalysisResult(
            narrative_success=True, system_success=True,
        ))
        pipeline.validator.validate = AsyncMock(
            side_effect=[failed_validation, passed_validation],
        )
        pipeline.extractor.extract_from_analysis = AsyncMock()

        result = await pipeline.generate_chapter(novel_id, 1, user_id=1)

        assert result.success
        assert result.draft_number == 2
        assert not result.flagged_for_review
        # Generator called twice (initial + retry)
        assert pipeline.generator.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_second_rejection_flags_for_review(
        self, db_engine, mock_llm, mock_settings, mock_redis,
    ):
        """Verify second rejection flags chapter for author review."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings, mock_redis)

        mock_context = MagicMock()
        mock_context.sections = {}
        mock_context.total_tokens = 100

        pipeline.context_assembler.build_chapter_context = AsyncMock(return_value=mock_context)
        pipeline.generator.generate = AsyncMock(return_value="Chapter text")
        pipeline.analyzer.analyze = AsyncMock(return_value=AnalysisResult(
            narrative_success=True, system_success=True,
        ))

        # Both validations fail
        failed_validation = ValidationResult(
            passed=False,
            retry_guidance="Fix issues",
        )
        from aiwebnovel.story.validator import ValidationIssue
        failed_validation.issues.append(ValidationIssue(
            issue_type="earned_power",
            description="Unearned",
            severity="critical",
        ))

        pipeline.validator.validate = AsyncMock(return_value=failed_validation)
        pipeline.extractor.extract_from_analysis = AsyncMock()

        result = await pipeline.generate_chapter(novel_id, 1, user_id=1)

        assert result.success
        assert result.flagged_for_review

    @pytest.mark.asyncio
    async def test_budget_check_before_generation(
        self, db_engine, mock_llm, mock_settings, mock_redis,
    ):
        """Verify budget is checked before generation starts."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings, mock_redis)

        # Make budget check fail
        mock_llm.budget_checker.check_llm_budget = AsyncMock(
            side_effect=BudgetExceededError("Budget exceeded", 500, 500),
        )

        result = await pipeline.generate_chapter(novel_id, 1, user_id=1)

        assert not result.success
        assert "Budget exceeded" in (result.error or "")

    @pytest.mark.asyncio
    async def test_generation_lock_prevents_concurrent(
        self, db_engine, mock_llm, mock_settings,
    ):
        """Verify Redis lock prevents concurrent generation."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        # Redis lock acquisition fails
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=False)

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings, mock_redis)

        result = await pipeline.generate_chapter(novel_id, 1, user_id=1)

        assert not result.success
        assert "already in progress" in (result.error or "")


class TestSceneMarkersPipeline:
    """Test scene marker extraction and ChapterImage creation in pipeline."""

    @pytest.mark.asyncio
    async def test_markers_extracted_before_draft_save(
        self, db_engine, mock_llm, mock_settings, mock_redis,
    ):
        """Verify scene markers are extracted and clean text is stored."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings, mock_redis)

        mock_context = MagicMock()
        mock_context.sections = {}
        mock_context.total_tokens = 100

        pipeline.context_assembler.build_chapter_context = AsyncMock(return_value=mock_context)

        # Generator returns text with scene markers
        raw_text = (
            "The warrior drew his sword.\n\n"
            "[SCENE: A lone warrior on a cliff edge, sword raised against crimson sunset]\n\n"
            "He charged into battle.\n\n"
            "[SCENE: Clash of steel in rain-soaked courtyard]\n\n"
            "Victory was his."
        )
        pipeline.generator.generate = AsyncMock(return_value=raw_text)
        pipeline.analyzer.analyze = AsyncMock(return_value=AnalysisResult(
            narrative_success=True, system_success=True,
        ))
        pipeline.validator.validate = AsyncMock(return_value=ValidationResult(passed=True))
        pipeline.extractor.extract_from_analysis = AsyncMock()

        result = await pipeline.generate_chapter(novel_id, 1, user_id=1)

        assert result.success
        # Markers should be extracted
        assert len(result.scene_markers) == 2
        assert result.scene_markers[0].description == (
            "A lone warrior on a cliff edge,"
            " sword raised against crimson sunset"
        )
        assert result.scene_markers[1].description == "Clash of steel in rain-soaked courtyard"

        # Clean text should be stored (no markers)
        assert "[SCENE:" not in result.chapter_text

    @pytest.mark.asyncio
    async def test_chapter_images_created(
        self, db_engine, mock_llm, mock_settings, mock_redis,
    ):
        """Verify ChapterImage records are created for each scene marker."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings, mock_redis)

        mock_context = MagicMock()
        mock_context.sections = {}
        mock_context.total_tokens = 100

        pipeline.context_assembler.build_chapter_context = AsyncMock(return_value=mock_context)

        raw_text = (
            "Paragraph one.\n\n"
            "[SCENE: Epic battle scene]\n\n"
            "Paragraph two.\n\n"
            "[SCENE: Peaceful aftermath]\n\n"
            "Paragraph three."
        )
        pipeline.generator.generate = AsyncMock(return_value=raw_text)
        pipeline.analyzer.analyze = AsyncMock(return_value=AnalysisResult(
            narrative_success=True, system_success=True,
        ))
        pipeline.validator.validate = AsyncMock(return_value=ValidationResult(passed=True))
        pipeline.extractor.extract_from_analysis = AsyncMock()

        result = await pipeline.generate_chapter(novel_id, 1, user_id=1)

        assert result.success
        assert result.chapter_id is not None

        # Verify ChapterImage records exist
        async with session_factory() as session:
            stmt = select(ChapterImage).where(
                ChapterImage.chapter_id == result.chapter_id,
            )
            ci_result = await session.execute(stmt)
            images = ci_result.scalars().all()

        assert len(images) == 2
        assert images[0].scene_description == "Epic battle scene"
        assert images[0].paragraph_index == 1
        assert images[0].status == "pending"
        assert images[1].scene_description == "Peaceful aftermath"
        assert images[1].paragraph_index == 3

    @pytest.mark.asyncio
    async def test_no_markers_no_chapter_images(
        self, db_engine, mock_llm, mock_settings, mock_redis,
    ):
        """No markers = no ChapterImage records."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings, mock_redis)

        mock_context = MagicMock()
        mock_context.sections = {}
        mock_context.total_tokens = 100

        pipeline.context_assembler.build_chapter_context = AsyncMock(return_value=mock_context)
        pipeline.generator.generate = AsyncMock(return_value="Just plain prose. No markers.")
        pipeline.analyzer.analyze = AsyncMock(return_value=AnalysisResult(
            narrative_success=True, system_success=True,
        ))
        pipeline.validator.validate = AsyncMock(return_value=ValidationResult(passed=True))
        pipeline.extractor.extract_from_analysis = AsyncMock()

        result = await pipeline.generate_chapter(novel_id, 1, user_id=1)

        assert result.success
        assert len(result.scene_markers) == 0


class TestSeedCharactersFromWorld:
    """Test _seed_characters_from_world populates Character table."""

    STAGE_DATA = {
        "protagonist": {
            "name": "Lin Feng",
            "age": 17,
            "background": "Orphan from the Iron Wastes",
            "personality": {
                "core_traits": ["determined", "curious"],
                "flaws": ["reckless"],
                "strengths": ["adaptable"],
                "fears": ["abandonment"],
                "desires": ["strength"],
            },
            "starting_power": {"current_rank": "Rank 1", "discipline": "Body Refinement"},
            "motivation": {
                "surface_motivation": "Survive and grow stronger",
                "deep_motivation": "Discover the truth about family",
            },
            "initial_circumstances": "Enters Azure Sect outer disciples",
        },
        "antagonists": {
            "antagonists": [
                {"name": "Elder Shen", "role": "Corrupt authority",
                 "motivation": "Maintain control",
                 "relationship_to_protagonist": "Sect elder who blocks path"},
                {"name": "The Hollow King", "role": "Arc villain",
                 "motivation": {"surface_motivation": "Open the Void gate"},
                 "relationship_to_protagonist": "Distant cosmic threat"},
            ],
        },
        "supporting_cast": {
            "characters": [
                {"name": "Wei Mei", "role": "Mentor",
                 "narrative_purpose": "Guides protagonist",
                 "connection_to_protagonist": "Sect elder who sees potential"},
                {"name": "Zhu Ling", "role": "Rival/friend",
                 "narrative_purpose": "Fellow disciple foil",
                 "connection_to_protagonist": "Fellow disciple"},
                {"name": "Old Bones", "role": "Info broker",
                 "narrative_purpose": "Comic relief / exposition",
                 "connection_to_protagonist": "Marketplace contact"},
            ],
        },
    }

    @pytest.mark.asyncio
    async def test_seeds_all_character_types(self, db_engine, mock_llm, mock_settings):
        """Protagonist, antagonists, and supporting cast are all seeded."""
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings)

        async with session_factory() as session:
            await pipeline._seed_characters_from_world(session, novel_id, self.STAGE_DATA)
            await session.commit()

        async with session_factory() as session:
            chars = (await session.execute(
                select(Character)
                .where(Character.novel_id == novel_id)
                .order_by(Character.id)
            )).scalars().all()

        assert len(chars) == 6  # 1 + 2 + 3

        protag = [c for c in chars if c.role == "protagonist"]
        assert len(protag) == 1
        assert protag[0].name == "Lin Feng"
        assert protag[0].personality_traits == ["determined", "curious"]
        assert protag[0].motivation == "Survive and grow stronger"
        assert protag[0].current_goal == "Enters Azure Sect outer disciples"
        assert protag[0].background == "Orphan from the Iron Wastes"

        antags = [c for c in chars if c.role == "antagonist"]
        assert len(antags) == 2
        assert {a.name for a in antags} == {"Elder Shen", "The Hollow King"}
        # Dict motivation is extracted
        hollow = [a for a in antags if a.name == "The Hollow King"][0]
        assert hollow.motivation == "Open the Void gate"

        supporting = [c for c in chars if c.role == "supporting"]
        assert len(supporting) == 3
        assert {s.name for s in supporting} == {"Wei Mei", "Zhu Ling", "Old Bones"}

    @pytest.mark.asyncio
    async def test_idempotent_skips_if_characters_exist(self, db_engine, mock_llm, mock_settings):
        """Second call is a no-op when characters already exist."""
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings)

        # Seed once
        async with session_factory() as session:
            await pipeline._seed_characters_from_world(session, novel_id, self.STAGE_DATA)
            await session.commit()

        # Seed again — should be skipped
        async with session_factory() as session:
            await pipeline._seed_characters_from_world(session, novel_id, self.STAGE_DATA)
            await session.commit()

        async with session_factory() as session:
            count = (await session.execute(
                select(func.count()).select_from(Character).where(
                    Character.novel_id == novel_id,
                )
            )).scalar_one()
        assert count == 6  # not 12

    @pytest.mark.asyncio
    async def test_handles_empty_stage_data(self, db_engine, mock_llm, mock_settings):
        """Empty stage data creates no characters."""
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_factory() as session:
            novel_id = await _seed_novel(session)
            await session.commit()

        pipeline = StoryPipeline(mock_llm, session_factory, mock_settings)

        async with session_factory() as session:
            await pipeline._seed_characters_from_world(session, novel_id, {})
            await session.commit()

        async with session_factory() as session:
            count = (await session.execute(
                select(func.count()).select_from(Character).where(
                    Character.novel_id == novel_id,
                )
            )).scalar_one()
        assert count == 0
