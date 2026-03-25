"""Pipeline job management: creation, heartbeat, completion, Redis locking.

Extracted from pipeline.py to reduce module size.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import GenerationJob

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime for DB compatibility."""
    return datetime.now(UTC).replace(tzinfo=None)


class PipelineJobManager:
    """Manages generation job lifecycle and Redis concurrency locks."""

    def __init__(self, redis: Any | None = None) -> None:
        self.redis = redis

    # ------------------------------------------------------------------
    # Redis lock helpers
    # ------------------------------------------------------------------

    async def acquire_lock(self, novel_id: int) -> bool:
        """Acquire Redis generation lock. Returns True if acquired."""
        if self.redis is None:
            logger.warning(
                "generation_lock_bypassed_no_redis",
                novel_id=novel_id,
                msg="Concurrent generation protection disabled — Redis unavailable",
            )
            return True
        key = f"novel:{novel_id}:generating"
        result = await self.redis.set(key, "1", nx=True, ex=600)  # 10 min TTL
        return result is not None and result is not False

    async def release_lock(self, novel_id: int) -> None:
        """Release Redis generation lock."""
        if self.redis is None:
            return
        key = f"novel:{novel_id}:generating"
        await self.redis.delete(key)

    # ------------------------------------------------------------------
    # Generation job tracking
    # ------------------------------------------------------------------

    async def create_job(
        self,
        session: AsyncSession,
        novel_id: int,
        job_type: str,
        chapter_number: int | None = None,
    ) -> GenerationJob:
        """Create a generation job record."""
        job = GenerationJob(
            novel_id=novel_id,
            job_type=job_type,
            chapter_number=chapter_number,
            status="running",
            started_at=_utcnow(),
            heartbeat_at=_utcnow(),
        )
        session.add(job)
        await session.flush()
        return job

    async def update_heartbeat(
        self, session: AsyncSession, job: GenerationJob,
    ) -> None:
        """Update heartbeat on job."""
        job.heartbeat_at = _utcnow()
        await session.flush()

    async def update_stage(
        self,
        session: AsyncSession,
        job: GenerationJob,
        stage_name: str,
    ) -> None:
        """Update the current stage on the job (for polling UI)."""
        job.stage_name = stage_name
        job.heartbeat_at = _utcnow()
        await session.flush()

    async def complete_job(
        self,
        session: AsyncSession,
        job: GenerationJob,
        status: str = "completed",
        error: str | None = None,
    ) -> None:
        """Mark job as complete or failed."""
        job.status = status
        job.completed_at = _utcnow()
        if error:
            job.error_message = error
        await session.flush()
