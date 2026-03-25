"""Worker health: heartbeat, stale job recovery, dead letter handling.

Ensures generation jobs don't silently stall. Workers update heartbeat_at
on their GenerationJob row; a cron task detects stale jobs and recovers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.db.models import GenerationJob, Notification, Novel

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime for SQLite compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkerHealth:
    """Worker health management: heartbeat, recovery, dead letter."""

    def __init__(self, settings: Any | None = None) -> None:
        if settings is not None:
            self._stale_threshold = settings.worker_stale_threshold_seconds
            self._heartbeat_interval = settings.worker_heartbeat_interval_seconds
        else:
            self._stale_threshold = 120
            self._heartbeat_interval = 30

    async def start_heartbeat(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        job_id: int,
        interval: int | None = None,
    ) -> asyncio.Task:
        """Start a background task that updates GenerationJob.heartbeat_at.

        Args:
            session_factory: Async session factory for DB access.
            job_id: The GenerationJob.id to update.
            interval: Seconds between heartbeat updates (defaults to settings value).

        Returns:
            The asyncio.Task running the heartbeat loop.
        """
        if interval is None:
            interval = self._heartbeat_interval

        async def _heartbeat_loop() -> None:
            while True:
                try:
                    async with session_factory() as session:
                        stmt = select(GenerationJob).where(
                            GenerationJob.id == job_id
                        )
                        result = await session.execute(stmt)
                        job = result.scalar_one_or_none()
                        if job is not None:
                            job.heartbeat_at = _utcnow()
                            await session.commit()
                except asyncio.CancelledError:
                    raise
                except Exception:  # Intentional broad catch: heartbeat is best-effort
                    logger.warning(
                        "heartbeat_update_failed",
                        job_id=job_id,
                    )
                await asyncio.sleep(interval)

        task = asyncio.create_task(_heartbeat_loop())
        logger.debug("heartbeat_started", job_id=job_id, interval=interval)
        return task

    async def stop_heartbeat(self, task: asyncio.Task) -> None:
        """Cancel the heartbeat background task."""
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.debug("heartbeat_stopped")

    async def recover_stale_jobs(
        self,
        session: AsyncSession,
        redis: Any,
    ) -> list[int]:
        """Find and recover stale jobs on worker startup.

        A job is stale if:
        - status = 'running'
        - heartbeat_at is older than ``self._stale_threshold``

        Recovery:
        - Mark job status as 'stale'
        - Release Redis generation lock for the novel
        - Create notification for the author

        Args:
            session: Active async database session.
            redis: Redis client for lock cleanup.

        Returns:
            List of recovered job IDs.
        """
        threshold = _utcnow() - timedelta(
            seconds=self._stale_threshold
        )

        stmt = select(GenerationJob).where(
            GenerationJob.status == "running",
            or_(
                GenerationJob.heartbeat_at < threshold,
                GenerationJob.heartbeat_at.is_(None),
            ),
        )
        result = await session.execute(stmt)
        stale_jobs = result.scalars().all()

        recovered_ids: list[int] = []

        for job in stale_jobs:
            # Mark as stale
            job.status = "stale"
            job.error_message = (
                f"Job stale: heartbeat not updated for >{self._stale_threshold}s"
            )
            job.completed_at = _utcnow()

            # Release Redis lock
            lock_key = f"novel:{job.novel_id}:generating"
            try:
                await redis.delete(lock_key)
            except Exception:  # Intentional broad catch: lock release is best-effort
                logger.warning(
                    "stale_lock_release_failed",
                    job_id=job.id,
                    novel_id=job.novel_id,
                )

            # Create notification for the author
            novel = await session.get(Novel, job.novel_id)
            if novel:
                notification = Notification(
                    user_id=novel.author_id,
                    novel_id=job.novel_id,
                    notification_type="generation_stale",
                    title="Generation job stale",
                    message=(
                        f"A {job.job_type} job (ID {job.id}) was detected as stale "
                        f"and has been recovered. You may need to retry."
                    ),
                )
                session.add(notification)

            recovered_ids.append(job.id)

            logger.info(
                "stale_job_recovered",
                job_id=job.id,
                novel_id=job.novel_id,
                job_type=job.job_type,
            )

        if recovered_ids:
            await session.commit()

        return recovered_ids

    async def mark_dead_letter(
        self,
        session: AsyncSession,
        job_id: int,
        error: str,
    ) -> None:
        """Move a permanently failed job to dead_letter status.

        Args:
            session: Active async database session.
            job_id: The GenerationJob.id to mark.
            error: Description of the permanent failure.
        """
        stmt = select(GenerationJob).where(GenerationJob.id == job_id)
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()

        if job is None:
            logger.warning("dead_letter_job_not_found", job_id=job_id)
            return

        job.status = "dead_letter"
        job.error_message = error
        job.completed_at = _utcnow()
        await session.commit()

        logger.info(
            "job_dead_lettered",
            job_id=job_id,
            error=error,
        )
