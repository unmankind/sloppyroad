"""Tests for worker queue infrastructure (arq-based)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aiwebnovel.config import Settings
from aiwebnovel.worker.queue import WorkerSettings, enqueue_task, report_progress


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key-for-testing-only",
        debug=True,
    )


@pytest.fixture()
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value=1)
    redis.close = AsyncMock()
    return redis


class TestWorkerSettings:
    """Tests for WorkerSettings configuration."""

    def test_has_functions(self) -> None:
        """WorkerSettings must list all task functions."""
        assert hasattr(WorkerSettings, "functions")
        assert len(WorkerSettings.functions) > 0

    def test_has_cron_jobs(self) -> None:
        """WorkerSettings must define cron jobs."""
        assert hasattr(WorkerSettings, "cron_jobs")
        assert len(WorkerSettings.cron_jobs) > 0

    def test_max_jobs(self) -> None:
        assert WorkerSettings.max_jobs == 4

    def test_job_timeout(self) -> None:
        assert WorkerSettings.job_timeout == 900

    def test_max_tries(self) -> None:
        assert WorkerSettings.max_tries == 3

    def test_health_check_interval(self) -> None:
        assert WorkerSettings.health_check_interval == 30

    @pytest.mark.asyncio
    async def test_on_startup_initializes_context(
        self, test_settings: Settings
    ) -> None:
        """on_startup should populate ctx with db, llm, settings, redis."""
        ctx: dict = {}
        with (
            patch("aiwebnovel.worker.queue.Settings", return_value=test_settings),
            patch("aiwebnovel.worker.queue.get_engine") as mock_engine,
            patch("aiwebnovel.worker.queue.get_session_factory") as mock_sf,
            patch("aiwebnovel.worker.queue.LLMProvider") as mock_llm_cls,
            patch("aiwebnovel.worker.queue.redis_asyncio") as mock_redis_mod,
            patch("aiwebnovel.worker.queue.WorkerHealth") as mock_health_cls,
        ):
            mock_engine.return_value = MagicMock()
            # Session factory must return an async context manager
            mock_session = AsyncMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=False
            )
            mock_sf.return_value = mock_session_factory
            mock_llm_cls.return_value = MagicMock()
            mock_redis_inst = AsyncMock()
            # redis_asyncio.from_url is NOT a coroutine, it returns synchronously
            mock_redis_mod.from_url = MagicMock(return_value=mock_redis_inst)
            mock_health_inst = AsyncMock()
            mock_health_inst.recover_stale_jobs = AsyncMock(return_value=[])
            mock_health_cls.return_value = mock_health_inst

            await WorkerSettings.on_startup(ctx)

            assert "settings" in ctx
            assert "session_factory" in ctx
            assert "llm" in ctx
            assert "redis" in ctx
            assert "health" in ctx

    @pytest.mark.asyncio
    async def test_on_shutdown_cleans_up(self) -> None:
        """on_shutdown should close connections."""
        mock_engine = AsyncMock()
        mock_redis = AsyncMock()

        ctx = {
            "engine": mock_engine,
            "redis": mock_redis,
        }

        await WorkerSettings.on_shutdown(ctx)

        mock_engine.dispose.assert_called_once()
        mock_redis.close.assert_called_once()


class TestEnqueueTask:
    """Tests for enqueue_task helper."""

    @pytest.mark.asyncio
    async def test_enqueue_returns_job_id(self, mock_redis: AsyncMock) -> None:
        """enqueue_task should create a job and return its ID."""
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "test-job-123"
        pool.enqueue_job.return_value = mock_job

        job_id = await enqueue_task(pool, "generate_chapter_task", novel_id=1)
        assert job_id == "test-job-123"
        pool.enqueue_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_enqueue_passes_kwargs(self, mock_redis: AsyncMock) -> None:
        """enqueue_task should forward all kwargs to the task."""
        pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "test-job-456"
        pool.enqueue_job.return_value = mock_job

        await enqueue_task(
            pool, "generate_chapter_task", novel_id=1, chapter_number=5
        )

        call_kwargs = pool.enqueue_job.call_args
        assert call_kwargs[1]["novel_id"] == 1
        assert call_kwargs[1]["chapter_number"] == 5


class TestReportProgress:
    """Tests for progress reporting via Redis pub/sub."""

    @pytest.mark.asyncio
    async def test_publishes_to_correct_channel(self, mock_redis: AsyncMock) -> None:
        """report_progress should publish to job:<id>:progress channel."""
        ctx = {"redis": mock_redis}
        await report_progress(ctx, stage="generating", progress=0.5, job_id="job-42")

        mock_redis.publish.assert_called_once()
        channel = mock_redis.publish.call_args[0][0]
        assert channel == "job:job-42:progress"

    @pytest.mark.asyncio
    async def test_progress_payload(self, mock_redis: AsyncMock) -> None:
        """report_progress should send stage and progress in JSON payload."""
        ctx = {"redis": mock_redis}
        await report_progress(ctx, stage="analyzing", progress=0.7, job_id="job-99")

        payload = json.loads(mock_redis.publish.call_args[0][1])
        assert payload["stage"] == "analyzing"
        assert payload["progress"] == 0.7

    @pytest.mark.asyncio
    async def test_noop_without_redis(self) -> None:
        """report_progress should silently do nothing if redis is missing."""
        ctx: dict = {}
        # Should not raise
        await report_progress(ctx, stage="test", progress=0.1, job_id="nope")

    @pytest.mark.asyncio
    async def test_noop_without_job_id(self, mock_redis: AsyncMock) -> None:
        """report_progress should do nothing without a job_id."""
        ctx = {"redis": mock_redis}
        await report_progress(ctx, stage="test", progress=0.1, job_id=None)
        mock_redis.publish.assert_not_called()
