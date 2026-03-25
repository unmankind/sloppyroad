"""arq-based async task queue infrastructure.

Provides WorkerSettings for arq, enqueue helper, and re-exports
report_progress from progress module.
"""

from __future__ import annotations

import os
from typing import Any

import redis.asyncio as redis_asyncio
import structlog
from arq import cron
from arq.connections import ArqRedis, RedisSettings

from aiwebnovel.config import Settings
from aiwebnovel.db.session import get_engine, get_session_factory
from aiwebnovel.llm.provider import LLMProvider
from aiwebnovel.story.pipeline import StoryPipeline
from aiwebnovel.worker.health import WorkerHealth
from aiwebnovel.worker.progress import report_progress  # re-export

logger = structlog.get_logger(__name__)

# Re-export for consumers
__all__ = [
    "ImageWorkerSettings",
    "WorkerSettings",
    "enqueue_task",
    "report_progress",
]


# ---------------------------------------------------------------------------
# Worker configuration
# ---------------------------------------------------------------------------


class WorkerSettings:
    """arq worker configuration.

    Defines all task functions, cron jobs, and lifecycle hooks.
    """

    # Import task functions lazily to avoid circular imports at module load.
    # arq resolves `functions` and `cron_jobs` after the worker process starts,
    # so lazy population in on_startup is the canonical approach.  We also
    # eagerly populate below (via _get_*) so that tests can inspect the list
    # at import time.

    @staticmethod
    def _get_functions() -> list:
        from aiwebnovel.worker.tasks_generation import (  # noqa: WPS433
            autonomous_tick_task,
            generate_arc_task,
            generate_chapter_task,
            generate_world_task,
        )
        from aiwebnovel.worker.tasks_maintenance import (  # noqa: WPS433
            detect_stale_jobs_task,
            embed_bible_entries_task,
            generate_arc_summary_task,
            generate_chapter_summary_task,
            refresh_novel_stats_task,
            run_post_analysis_task,
        )

        return [
            generate_world_task,
            generate_arc_task,
            generate_chapter_task,
            run_post_analysis_task,
            embed_bible_entries_task,
            generate_chapter_summary_task,
            generate_arc_summary_task,
            autonomous_tick_task,
            refresh_novel_stats_task,
            detect_stale_jobs_task,
        ]

    @staticmethod
    def _get_cron_jobs() -> list:
        from aiwebnovel.worker.tasks_generation import (  # noqa: WPS433
            autonomous_tick_task,
        )
        from aiwebnovel.worker.tasks_maintenance import (  # noqa: WPS433
            detect_stale_jobs_task,
            refresh_novel_stats_task,
        )

        return [
            cron(autonomous_tick_task, minute={0}, run_at_startup=False),
            cron(refresh_novel_stats_task, minute={0}, run_at_startup=False),
            cron(detect_stale_jobs_task, second={0}, run_at_startup=True),
        ]

    # arq reads these as class attributes — populated lazily below
    functions: list = []
    cron_jobs: list = []
    redis_settings: RedisSettings = RedisSettings.from_dsn(
        os.environ.get("AIWN_REDIS_URL", "redis://localhost:6379")
    )

    max_jobs = 4
    job_timeout = 900  # 15 minutes
    max_tries = 3
    health_check_interval = 30
    health_check_key = "arq:health-check"

    @staticmethod
    async def on_startup(ctx: dict[str, Any]) -> None:
        """Initialize DB engine, LLM provider, settings, Redis on worker startup."""
        settings = Settings()
        engine = get_engine(settings.database_url, echo=settings.database_echo)
        session_factory = get_session_factory(engine)
        llm = LLMProvider(settings, session_factory)

        redis = redis_asyncio.from_url(
            settings.redis_url, decode_responses=True
        )

        # Create arq pool for enqueuing tasks from within worker tasks
        arq_pool = None
        try:
            from arq import create_pool

            arq_pool = await create_pool(
                RedisSettings.from_dsn(settings.redis_url)
            )
        except (OSError, Exception) as exc:
            logger.warning("arq_pool_creation_failed", error=str(exc))

        health = WorkerHealth(settings)

        # Recover any stale jobs from previous worker crashes
        async with session_factory() as session:
            recovered = await health.recover_stale_jobs(session, redis)
            if recovered:
                logger.info("recovered_stale_jobs_on_startup", job_ids=recovered)

        # Vector store (graceful — None if unavailable)
        from aiwebnovel.db.vector import create_vector_store

        vector_store = await create_vector_store(settings)

        pipeline = StoryPipeline(
            llm, session_factory, settings, redis,
            vector_store=vector_store,
        )

        ctx["settings"] = settings
        ctx["engine"] = engine
        ctx["session_factory"] = session_factory
        ctx["llm"] = llm
        ctx["redis"] = redis
        ctx["arq_pool"] = arq_pool
        ctx["health"] = health
        ctx["vector_store"] = vector_store
        ctx["pipeline"] = pipeline

        logger.info("worker_started", redis_url=settings.redis_url)

    @staticmethod
    async def on_shutdown(ctx: dict[str, Any]) -> None:
        """Close connections on worker shutdown."""
        engine = ctx.get("engine")
        redis = ctx.get("redis")
        vector_store = ctx.get("vector_store")

        if vector_store is not None and hasattr(vector_store, "close"):
            await vector_store.close()
        if engine is not None:
            await engine.dispose()
        if redis is not None:
            await redis.close()

        logger.info("worker_shutdown")


def _populate_worker_settings() -> None:
    """Populate WorkerSettings.functions and cron_jobs at import time.

    Called at the bottom of this module. Wrapped in a function so that
    the circular-import guard catches it cleanly.
    """
    try:
        WorkerSettings.functions = WorkerSettings._get_functions()
        WorkerSettings.cron_jobs = WorkerSettings._get_cron_jobs()
    except ImportError:
        # During isolated unit-testing of tasks.py, queue.py may be
        # partially initialised. Functions will be populated on_startup.
        pass


_populate_worker_settings()


# ---------------------------------------------------------------------------
# Image Worker configuration
# ---------------------------------------------------------------------------


class ImageWorkerSettings:
    """arq worker configuration for the dedicated image worker.

    Handles only image generation tasks, keeping them separate from
    chapter/world generation so they don't compete for job slots.
    Uses a separate queue name so arq routes tasks correctly.
    """

    @staticmethod
    def _get_functions() -> list:
        from aiwebnovel.worker.tasks_images import (  # noqa: WPS433
            generate_image_task,
            generate_scene_image_task,
            process_art_queue_task,
            regenerate_image_task,
        )

        return [
            process_art_queue_task,
            generate_image_task,
            generate_scene_image_task,
            regenerate_image_task,
        ]

    @staticmethod
    def _get_cron_jobs() -> list:
        from aiwebnovel.worker.tasks_images import (  # noqa: WPS433
            process_art_queue_task,
        )

        return [
            cron(
                process_art_queue_task,
                second={0, 30},
                run_at_startup=False,
            ),
        ]

    functions: list = []
    cron_jobs: list = []
    redis_settings: RedisSettings = RedisSettings.from_dsn(
        os.environ.get("AIWN_REDIS_URL", "redis://localhost:6379")
    )

    queue_name = "arq:queue:images"
    max_jobs = 6  # image gen is pure I/O wait (Replicate API)
    job_timeout = 300  # 5 min per image is generous
    max_tries = 3
    health_check_interval = 30
    health_check_key = "arq:health-check:images"

    @staticmethod
    async def on_startup(ctx: dict[str, Any]) -> None:
        """Image worker startup — needs LLM for prompt composition."""
        settings = Settings()
        engine = get_engine(settings.database_url, echo=settings.database_echo)
        session_factory = get_session_factory(engine)
        llm = LLMProvider(settings, session_factory)

        redis = redis_asyncio.from_url(
            settings.redis_url, decode_responses=True,
        )

        ctx["settings"] = settings
        ctx["engine"] = engine
        ctx["session_factory"] = session_factory
        ctx["llm"] = llm
        ctx["redis"] = redis

        logger.info("image_worker_started", redis_url=settings.redis_url)

    @staticmethod
    async def on_shutdown(ctx: dict[str, Any]) -> None:
        """Close connections on image worker shutdown."""
        engine = ctx.get("engine")
        redis = ctx.get("redis")

        if engine is not None:
            await engine.dispose()
        if redis is not None:
            await redis.close()

        logger.info("image_worker_shutdown")


def _populate_image_worker_settings() -> None:
    """Populate ImageWorkerSettings at import time."""
    try:
        ImageWorkerSettings.functions = (
            ImageWorkerSettings._get_functions()
        )
        ImageWorkerSettings.cron_jobs = (
            ImageWorkerSettings._get_cron_jobs()
        )
    except ImportError:
        pass


_populate_image_worker_settings()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def enqueue_task(pool: ArqRedis, task_name: str, **kwargs: Any) -> str:
    """Enqueue a task and return the arq job ID."""
    job = await pool.enqueue_job(task_name, **kwargs)
    logger.info("task_enqueued", task=task_name, job_id=job.job_id, kwargs=kwargs)
    return job.job_id
