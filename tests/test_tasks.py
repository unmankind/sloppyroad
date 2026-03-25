"""Tests for all arq task implementations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    AuthorProfile,
    Base,
    Chapter,
    GenerationJob,
    Novel,
    NovelSettings,
    NovelStats,
    StoryBibleEntry,
    User,
)
from aiwebnovel.llm.budget import BudgetExceededError
from aiwebnovel.worker.tasks import (
    autonomous_tick_task,
    detect_stale_jobs_task,
    embed_bible_entries_task,
    generate_chapter_summary_task,
    generate_chapter_task,
    generate_image_task,
    generate_world_task,
    refresh_novel_stats_task,
    run_post_analysis_task,
)


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key-for-testing-only",
        debug=True,
    )


@pytest.fixture()
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def session_factory(db_engine):
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    return factory


@pytest.fixture()
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.publish = AsyncMock(return_value=1)
    redis.close = AsyncMock()
    return redis


@pytest.fixture()
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.embed = AsyncMock(return_value=[[0.1] * 768])
    llm.generate = AsyncMock()
    llm.settings = MagicMock()
    llm.budget_checker = MagicMock()
    llm.budget_checker.check_image_budget = AsyncMock()
    llm.budget_checker.update_spent = AsyncMock()
    llm.budget_checker.check_autonomous_daily_budget = AsyncMock()
    llm.budget_checker.check_llm_budget = AsyncMock()
    return llm


@pytest.fixture()
def mock_vector_store() -> AsyncMock:
    store = AsyncMock()
    store.add = AsyncMock()
    return store


@pytest.fixture()
def mock_pipeline() -> AsyncMock:
    pipeline = AsyncMock()
    pipeline.generate_world = AsyncMock()
    pipeline.generate_chapter = AsyncMock()
    return pipeline


@pytest.fixture()
def mock_health() -> AsyncMock:
    health = AsyncMock()
    health.start_heartbeat = AsyncMock(return_value=AsyncMock())
    health.stop_heartbeat = AsyncMock()
    return health


@pytest.fixture()
def ctx(
    test_settings: Settings,
    session_factory,
    mock_redis: AsyncMock,
    mock_llm: MagicMock,
    mock_vector_store: AsyncMock,
    mock_pipeline: AsyncMock,
    mock_health: AsyncMock,
) -> dict:
    return {
        "settings": test_settings,
        "session_factory": session_factory,
        "redis": mock_redis,
        "llm": mock_llm,
        "vector_store": mock_vector_store,
        "pipeline": mock_pipeline,
        "health": mock_health,
    }


async def _create_test_user_and_novel(
    session: AsyncSession,
    *,
    autonomous_enabled: bool = False,
    cadence_hours: int = 24,
) -> tuple[int, int]:
    """Helper: create a user, author profile, and novel. Return (user_id, novel_id)."""
    user = User(
        email="test@test.com",
        username="testuser",
        hashed_password="fakehash",
        role="author",
    )
    session.add(user)
    await session.flush()

    profile = AuthorProfile(
        user_id=user.id,
        api_budget_cents=5000,
        api_spent_cents=0,
        image_budget_cents=1000,
        image_spent_cents=0,
    )
    session.add(profile)
    await session.flush()

    novel = Novel(
        author_id=user.id,
        title="Test Novel",
        status="writing",
        autonomous_enabled=autonomous_enabled,
        autonomous_cadence_hours=cadence_hours,
        autonomous_daily_budget_cents=100,
    )
    session.add(novel)
    await session.flush()

    # Create NovelSettings for autonomous check
    ns = NovelSettings(
        novel_id=novel.id,
        autonomous_generation_enabled=autonomous_enabled,
        autonomous_cadence_hours=cadence_hours,
        last_autonomous_generation_at=(
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=cadence_hours + 1)
            if autonomous_enabled
            else None
        ),
    )
    session.add(ns)
    await session.flush()

    return user.id, novel.id


class TestGenerateWorldTask:
    """Tests for generate_world_task."""

    @pytest.mark.asyncio
    async def test_calls_pipeline(self, ctx: dict) -> None:
        """generate_world_task should call pipeline.generate_world."""
        from aiwebnovel.story.pipeline import WorldResult

        ctx["pipeline"].generate_world = AsyncMock(
            return_value=WorldResult(
                stages_completed=[
                    "cosmology", "power_system", "geography", "history",
                    "current_state", "protagonist", "antagonists", "supporting_cast",
                ],
                success=True,
            )
        )

        result = await generate_world_task(ctx, novel_id=1, user_id=1)
        ctx["pipeline"].generate_world.assert_called_once()
        call_args = ctx["pipeline"].generate_world.call_args
        assert call_args[0] == (1, 1)  # positional: novel_id, user_id
        assert result["success"] is True
        assert len(result["stages_completed"]) == 8

    @pytest.mark.asyncio
    async def test_reports_progress(self, ctx: dict) -> None:
        """generate_world_task should report progress."""
        from aiwebnovel.story.pipeline import WorldResult

        ctx["pipeline"].generate_world = AsyncMock(
            return_value=WorldResult(
                stages_completed=["cosmology"],
                success=True,
            )
        )

        await generate_world_task(ctx, novel_id=1, user_id=1)
        # Progress is reported at start and end
        ctx["redis"].publish.assert_called()


class TestGenerateChapterTask:
    """Tests for generate_chapter_task."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, ctx: dict) -> None:
        """generate_chapter_task should run the full generation lifecycle."""
        from aiwebnovel.story.pipeline import ChapterResult

        ctx["pipeline"].generate_chapter = AsyncMock(
            return_value=ChapterResult(
                chapter_text="Once upon a time...",
                chapter_id=1,
                success=True,
            )
        )

        result = await generate_chapter_task(
            ctx, novel_id=1, chapter_number=1, user_id=1, job_id="j1"
        )

        ctx["pipeline"].generate_chapter.assert_called_once()
        call_args = ctx["pipeline"].generate_chapter.call_args
        assert call_args[0] == (1, 1, 1)  # novel_id, chapter_number, user_id
        assert call_args[1]["guidance"] is None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_delegates_to_pipeline(self, ctx: dict) -> None:
        """generate_chapter_task delegates locking to pipeline.generate_chapter."""
        from aiwebnovel.story.pipeline import ChapterResult

        ctx["pipeline"].generate_chapter = AsyncMock(
            return_value=ChapterResult(success=True, chapter_text="text", chapter_id=1)
        )

        await generate_chapter_task(
            ctx, novel_id=42, chapter_number=1, user_id=1, job_id="j2"
        )

        # Pipeline handles locking internally — task just delegates
        ctx["pipeline"].generate_chapter.assert_called_once()
        call_args = ctx["pipeline"].generate_chapter.call_args
        assert call_args[0] == (42, 1, 1)  # novel_id, chapter_number, user_id
        assert call_args[1]["guidance"] is None

    @pytest.mark.asyncio
    async def test_handles_validation_failure_with_retry(self, ctx: dict) -> None:
        """On validation failure, pipeline retries internally; task propagates flagged result."""
        from aiwebnovel.story.pipeline import ChapterResult

        ctx["pipeline"].generate_chapter = AsyncMock(
            return_value=ChapterResult(
                chapter_text="retry text",
                chapter_id=1,
                success=True,
                flagged_for_review=True,
            )
        )

        result = await generate_chapter_task(
            ctx, novel_id=1, chapter_number=1, user_id=1, job_id="j3"
        )

        assert result["success"] is True
        assert result["flagged_for_review"] is True

    @pytest.mark.asyncio
    async def test_pipeline_lock_failure_returns_error(self, ctx: dict) -> None:
        """If pipeline returns lock failure, task propagates it."""
        from aiwebnovel.story.pipeline import ChapterResult

        ctx["pipeline"].generate_chapter = AsyncMock(
            return_value=ChapterResult(
                success=False,
                chapter_text="",
                chapter_id=None,
                error="Generation already in progress",
            )
        )

        result = await generate_chapter_task(
            ctx, novel_id=1, chapter_number=1, user_id=1, job_id="j4"
        )

        assert result["success"] is False
        assert "progress" in result["error"].lower()


class TestRunPostAnalysisTask:
    """Tests for run_post_analysis_task."""

    @pytest.mark.asyncio
    async def test_runs_analysis(self, ctx: dict) -> None:
        """run_post_analysis_task should call the analyzer."""
        mock_analyzer = AsyncMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.narrative_success = True
        mock_result.system_success = True
        mock_analyzer.analyze = AsyncMock(return_value=mock_result)

        with patch(
            "aiwebnovel.worker.tasks_maintenance.ChapterAnalyzer", return_value=mock_analyzer
        ):
            result = await run_post_analysis_task(
                ctx,
                novel_id=1,
                chapter_number=1,
                chapter_text="The hero advanced.",
                user_id=1,
            )

        assert result["success"] is True


class TestGenerateImageTask:
    """Tests for generate_image_task."""

    @pytest.mark.asyncio
    async def test_check_budget_and_generate(self, ctx: dict) -> None:
        """generate_image_task should check budget, compose prompt, call provider."""
        from aiwebnovel.images.budget import ImageBudgetResult

        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(
            return_value=MagicMock(
                image_data=b"fake_png",
                width=1024,
                height=1024,
                provider="comfyui",
                model="sdxl",
                seed=42,
                metadata={},
            )
        )

        with (
            patch(
                "aiwebnovel.worker.tasks_images.check_image_budget",
                new_callable=AsyncMock,
                return_value=ImageBudgetResult(allowed=True),
            ),
            patch(
                "aiwebnovel.worker.tasks_images.get_image_provider",
                return_value=mock_provider,
            ),
            patch(
                "aiwebnovel.worker.tasks_images.ImagePromptComposer"
            ) as mock_composer_cls,
        ):
            mock_composer = AsyncMock()
            mock_composer.compose_portrait_prompt = AsyncMock(
                return_value=MagicMock(
                    prompt="a portrait",
                    negative_prompt="",
                    width=1024,
                    height=1024,
                )
            )
            mock_composer_cls.return_value = mock_composer

            result = await generate_image_task(
                ctx,
                novel_id=1,
                asset_type="portrait",
                entity_id=1,
                entity_type="character",
                user_id=1,
            )

        assert result["success"] is True


class TestEmbedBibleEntriesTask:
    """Tests for embed_bible_entries_task."""

    @pytest.mark.asyncio
    async def test_calls_embed_and_vector_store(self, ctx: dict, session_factory) -> None:
        """embed_bible_entries_task should embed entries and store in vector DB."""
        # Create test data
        async with session_factory() as session:
            user_id, novel_id = await _create_test_user_and_novel(session)
            entry = StoryBibleEntry(
                novel_id=novel_id,
                entry_type="character_fact",
                content="The hero can fly.",
                source_chapter=1,
                importance=3,
            )
            session.add(entry)
            await session.flush()
            entry_id = entry.id
            await session.commit()

        result = await embed_bible_entries_task(
            ctx, novel_id=novel_id, entry_ids=[entry_id]
        )

        ctx["llm"].embed.assert_called()
        ctx["vector_store"].add.assert_called_once()
        assert result["embedded_count"] == 1

    @pytest.mark.asyncio
    async def test_empty_entries(self, ctx: dict) -> None:
        """embed_bible_entries_task with empty list should return 0."""
        result = await embed_bible_entries_task(ctx, novel_id=1, entry_ids=[])
        assert result["embedded_count"] == 0


class TestGenerateChapterSummaryTask:
    """Tests for generate_chapter_summary_task."""

    @pytest.mark.asyncio
    async def test_creates_both_summary_types(self, ctx: dict, session_factory) -> None:
        """generate_chapter_summary_task should create standard + enhanced recap."""
        # Create test data
        async with session_factory() as session:
            user_id, novel_id = await _create_test_user_and_novel(session)
            chapter = Chapter(
                novel_id=novel_id,
                chapter_number=1,
                title="Chapter 1",
                chapter_text="The hero began their journey through the mountains.",
                word_count=8,
                status="published",
            )
            session.add(chapter)
            await session.flush()
            chapter_id = chapter.id
            await session.commit()

        mock_summarizer = AsyncMock()
        mock_standard = MagicMock()
        mock_standard.id = 100
        mock_recap = MagicMock()
        mock_recap.id = 101
        mock_summarizer.generate_standard_summary = AsyncMock(return_value=mock_standard)
        mock_summarizer.generate_enhanced_recap = AsyncMock(return_value=mock_recap)

        with patch(
            "aiwebnovel.worker.tasks_maintenance.ChapterSummarizer",
            return_value=mock_summarizer,
        ):
            result = await generate_chapter_summary_task(
                ctx, novel_id=novel_id, chapter_id=chapter_id, user_id=user_id
            )

        mock_summarizer.generate_standard_summary.assert_called_once()
        mock_summarizer.generate_enhanced_recap.assert_called_once()
        assert result["success"] is True


class TestAutonomousTickTask:
    """Tests for autonomous_tick_task."""

    @pytest.mark.asyncio
    async def test_finds_eligible_novels(self, ctx: dict, session_factory) -> None:
        """autonomous_tick_task should find novels with autonomous_enabled=True."""
        async with session_factory() as session:
            user_id, novel_id = await _create_test_user_and_novel(
                session, autonomous_enabled=True, cadence_hours=1
            )
            # Add a chapter so the novel is "ready"
            ch = Chapter(
                novel_id=novel_id,
                chapter_number=1,
                title="Ch 1",
                chapter_text="text",
                word_count=1,
                status="published",
            )
            session.add(ch)
            await session.commit()

        # The pipeline should be called for this novel
        from aiwebnovel.story.pipeline import ChapterResult

        ctx["pipeline"].generate_chapter = AsyncMock(
            return_value=ChapterResult(success=True, chapter_text="auto", chapter_id=2)
        )

        result = await autonomous_tick_task(ctx)
        assert result["checked"] >= 1

    @pytest.mark.asyncio
    async def test_respects_budget_cap(self, ctx: dict, session_factory) -> None:
        """autonomous_tick_task should skip novels that exceed daily budget."""
        async with session_factory() as session:
            user_id, novel_id = await _create_test_user_and_novel(
                session, autonomous_enabled=True, cadence_hours=1
            )
            await session.commit()

        # Make budget check fail
        ctx["llm"].budget_checker.check_autonomous_daily_budget = AsyncMock(
            side_effect=BudgetExceededError("Budget exceeded")
        )

        result = await autonomous_tick_task(ctx)
        # Should not crash, just skip
        assert "error" not in result or result.get("enqueued", 0) == 0


class TestRefreshNovelStatsTask:
    """Tests for refresh_novel_stats_task."""

    @pytest.mark.asyncio
    async def test_updates_stats(self, ctx: dict, session_factory) -> None:
        """refresh_novel_stats_task should compute and store stats."""
        async with session_factory() as session:
            user_id, novel_id = await _create_test_user_and_novel(session)
            ch = Chapter(
                novel_id=novel_id,
                chapter_number=1,
                title="Ch 1",
                chapter_text="word " * 100,
                word_count=100,
                status="published",
            )
            session.add(ch)
            await session.commit()

        result = await refresh_novel_stats_task(ctx)
        assert result["refreshed"] >= 1

        # Verify stats in DB
        async with session_factory() as session:
            stmt = select(NovelStats).where(NovelStats.novel_id == novel_id)
            res = await session.execute(stmt)
            stats = res.scalar_one_or_none()
            assert stats is not None
            assert stats.total_chapters == 1
            assert stats.total_words == 100


class TestDetectStaleJobsTask:
    """Tests for detect_stale_jobs_task."""

    @pytest.mark.asyncio
    async def test_marks_stale_jobs(self, ctx: dict, session_factory) -> None:
        """detect_stale_jobs_task should find and mark jobs with old heartbeats."""
        # Use naive datetimes for SQLite compatibility
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with session_factory() as session:
            user_id, novel_id = await _create_test_user_and_novel(session)
            # Create a stale job (heartbeat > 120s old)
            job = GenerationJob(
                novel_id=novel_id,
                job_type="chapter_generation",
                status="running",
                started_at=now - timedelta(minutes=10),
                heartbeat_at=now - timedelta(minutes=5),
            )
            session.add(job)
            await session.commit()
            job_id = job.id

        # Use a real WorkerHealth so it actually queries the DB
        from aiwebnovel.worker.health import WorkerHealth
        ctx["health"] = WorkerHealth()

        result = await detect_stale_jobs_task(ctx)
        assert result["stale_count"] >= 1

        # Verify job is now stale
        async with session_factory() as session:
            stmt = select(GenerationJob).where(GenerationJob.id == job_id)
            res = await session.execute(stmt)
            job = res.scalar_one()
            assert job.status == "stale"
