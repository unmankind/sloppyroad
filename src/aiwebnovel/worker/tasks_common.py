"""Shared helpers used across task modules.

Provides utility functions and re-exports used by tasks_generation,
tasks_images, and tasks_maintenance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    ArtGenerationQueue,
    GenerationJob,
    NovelSettings,
)
from aiwebnovel.images.budget import check_image_budget
from aiwebnovel.worker.progress import report_progress

logger = structlog.get_logger(__name__)

# Re-export report_progress so consumers can import from tasks_common
__all__ = [
    "_mark_job_failed",
    "_utcnow",
    "enqueue_art_generation",
    "report_progress",
]


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime for SQLite compatibility."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _mark_job_failed(
    ctx: dict[str, Any], job_id: int, error: str,
) -> None:
    """Best-effort: mark a GenerationJob as failed so the UI reflects it."""
    try:
        session_factory = ctx["session_factory"]
        async with session_factory() as session:
            job = await session.get(GenerationJob, job_id)
            if job is not None and job.status not in ("completed", "failed"):
                job.status = "failed"
                job.error_message = error
                job.completed_at = _utcnow()
                await session.commit()
    except (SQLAlchemyError, RuntimeError):
        logger.warning("mark_job_failed_error", job_id=job_id)


async def enqueue_art_generation(
    session: AsyncSession,
    novel_id: int,
    asset_type: str,
    entity_id: int | None = None,
    entity_type: str | None = None,
    prompt: str | None = None,
    priority: int = 5,
    trigger_event: str | None = None,
    trigger_chapter: int | None = None,
    source_asset_id: int | None = None,
    feedback: str | None = None,
    *,
    pre_check_budget: bool = False,
) -> int | None:
    """Create a pending ArtGenerationQueue entry.

    Returns the queue entry ID, or ``None`` if *pre_check_budget* is True
    and the image budget is exhausted.
    """
    # Check per-novel image generation setting
    ns_enabled = (await session.execute(
        select(NovelSettings.image_generation_enabled)
        .where(NovelSettings.novel_id == novel_id)
    )).scalar_one_or_none()
    if ns_enabled is False:
        logger.info(
            "art_enqueue_skipped_disabled",
            novel_id=novel_id,
            asset_type=asset_type,
        )
        return None

    if pre_check_budget:
        budget = await check_image_budget(session, novel_id)
        if not budget.allowed:
            logger.info(
                "art_enqueue_skipped_budget",
                novel_id=novel_id,
                asset_type=asset_type,
                reason=budget.reason,
            )
            return None

    entry = ArtGenerationQueue(
        novel_id=novel_id,
        asset_type=asset_type,
        entity_id=entity_id,
        entity_type=entity_type,
        prompt=prompt,
        priority=priority,
        status="pending",
        trigger_event=trigger_event,
        trigger_chapter=trigger_chapter,
        source_asset_id=source_asset_id,
        feedback=feedback,
    )
    session.add(entry)
    await session.flush()
    queue_id = entry.id
    logger.info(
        "art_generation_enqueued",
        queue_id=queue_id,
        novel_id=novel_id,
        asset_type=asset_type,
        priority=priority,
    )
    return queue_id
