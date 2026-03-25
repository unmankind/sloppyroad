"""Maintenance task implementations: stale job detection, stats refresh,
chapter summaries, bible embedding, post-analysis.

Each task follows the arq pattern: ``async def task_name(ctx, **kwargs)``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import func, select

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    Chapter,
    GenerationJob,
    Novel,
    NovelRating,
    NovelStats,
    ReaderBookmark,
    StoryBibleEntry,
)
from aiwebnovel.db.vector import VectorEntry
from aiwebnovel.story.analyzer import ChapterAnalyzer
from aiwebnovel.summarization.chapter_summary import ChapterSummarizer
from aiwebnovel.worker.tasks_common import _utcnow

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Post-Analysis
# ---------------------------------------------------------------------------


async def run_post_analysis_task(
    ctx: dict[str, Any],
    novel_id: int,
    chapter_number: int,
    chapter_text: str,
    user_id: int,
) -> dict[str, Any]:
    """Run narrative + system analysis concurrently."""
    settings: Settings = ctx["settings"]
    llm = ctx["llm"]

    analyzer = ChapterAnalyzer(llm, settings)

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        result = await analyzer.analyze(
            session, novel_id, chapter_number, chapter_text, user_id
        )

    return {
        "success": result.success,
        "narrative_ok": result.narrative_success,
        "system_ok": result.system_success,
    }


# ---------------------------------------------------------------------------
# Bible Embedding
# ---------------------------------------------------------------------------


async def embed_bible_entries_task(
    ctx: dict[str, Any],
    novel_id: int,
    entry_ids: list[int],
) -> dict[str, Any]:
    """Batch embed story bible entries and store in vector DB."""
    if not entry_ids:
        return {"embedded_count": 0}

    llm = ctx["llm"]
    vector_store = ctx.get("vector_store")
    session_factory = ctx["session_factory"]

    # Load entries from DB
    async with session_factory() as session:
        stmt = select(StoryBibleEntry).where(StoryBibleEntry.id.in_(entry_ids))
        result = await session.execute(stmt)
        entries = result.scalars().all()

    if not entries:
        return {"embedded_count": 0}

    # Generate embeddings
    texts = [e.content for e in entries]
    embeddings = await llm.embed(texts)

    # Build vector entries
    vector_entries = []
    for entry, embedding in zip(entries, embeddings, strict=False):
        vector_entries.append(
            VectorEntry(
                id=str(entry.id),
                text=entry.content,
                embedding=embedding,
                metadata={
                    "novel_id": entry.novel_id,
                    "entry_type": entry.entry_type,
                    "chapter": entry.source_chapter,
                    "importance": entry.importance,
                    "is_public_knowledge": getattr(
                        entry, "is_public_knowledge", True,
                    ),
                    "entity_ids": entry.entity_ids or [],
                },
            )
        )

    # Store in vector DB
    if vector_store is not None:
        await vector_store.add(vector_entries)

    logger.info(
        "bible_entries_embedded",
        novel_id=novel_id,
        count=len(vector_entries),
    )

    return {"embedded_count": len(vector_entries)}


# ---------------------------------------------------------------------------
# Chapter Summary
# ---------------------------------------------------------------------------


async def generate_chapter_summary_task(
    ctx: dict[str, Any],
    novel_id: int,
    chapter_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Generate standard summary + enhanced recap for a chapter."""
    settings: Settings = ctx["settings"]
    llm = ctx["llm"]
    session_factory = ctx["session_factory"]

    # Load chapter
    async with session_factory() as session:
        stmt = select(Chapter).where(Chapter.id == chapter_id)
        result = await session.execute(stmt)
        chapter = result.scalar_one_or_none()

    if chapter is None:
        return {"success": False, "error": f"Chapter {chapter_id} not found"}

    summarizer = ChapterSummarizer(llm, settings)

    async with session_factory() as session:
        # Standard summary
        await summarizer.generate_standard_summary(
            session,
            novel_id=novel_id,
            chapter_id=chapter_id,
            chapter_text=chapter.chapter_text,
            user_id=user_id,
            chapter_number=chapter.chapter_number,
        )

        # Enhanced recap
        await summarizer.generate_enhanced_recap(
            session,
            novel_id=novel_id,
            chapter_id=chapter_id,
            chapter_text=chapter.chapter_text,
            user_id=user_id,
            chapter_number=chapter.chapter_number,
        )

        await session.commit()

    logger.info(
        "chapter_summaries_generated",
        novel_id=novel_id,
        chapter_id=chapter_id,
    )

    return {"success": True, "chapter_id": chapter_id}


# ---------------------------------------------------------------------------
# Arc Summary
# ---------------------------------------------------------------------------


async def generate_arc_summary_task(
    ctx: dict[str, Any],
    novel_id: int,
    arc_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Generate LLM-powered arc summary after arc completion.

    Uses ArcSummarizer to produce a prose summary, key themes,
    and outstanding promises. Stores results on the ArcPlan record.
    """
    settings: Settings = ctx["settings"]
    llm = ctx["llm"]
    session_factory = ctx["session_factory"]

    from aiwebnovel.db.models import ArcPlan
    from aiwebnovel.summarization.arc_summary import ArcSummarizer

    summarizer = ArcSummarizer(llm, settings)

    try:
        async with session_factory() as session:
            summary_text = await summarizer.generate_arc_summary(
                session, arc_id, user_id,
            )

            # Parse the full result to get promises_outstanding
            # (generate_arc_summary returns just the summary string,
            # so we store that; for promises we re-parse if needed)
            arc = await session.get(ArcPlan, arc_id)
            if arc is not None:
                arc.arc_summary = summary_text
            await session.commit()

        logger.info(
            "arc_summary_generated",
            novel_id=novel_id,
            arc_id=arc_id,
        )
        return {"success": True, "arc_id": arc_id}

    except Exception as exc:
        logger.warning(
            "arc_summary_failed",
            novel_id=novel_id,
            arc_id=arc_id,
            error=str(exc),
        )
        return {"success": False, "arc_id": arc_id, "error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Cron: Novel Stats Refresh
# ---------------------------------------------------------------------------


async def refresh_novel_stats_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron (every hour): Refresh novel_stats table.

    For each novel, compute:
    - total_chapters, total_words
    - total_readers (unique bookmarks)
    - avg_rating, rating_count
    - last_chapter_at
    """
    session_factory = ctx["session_factory"]
    refreshed = 0

    async with session_factory() as session:
        # Get all novels
        stmt = select(Novel.id)
        result = await session.execute(stmt)
        novel_ids = [row[0] for row in result.all()]

        for novel_id in novel_ids:
            # Chapter stats
            ch_stmt = select(
                func.count(Chapter.id),
                func.coalesce(func.sum(Chapter.word_count), 0),
                func.max(Chapter.created_at),
            ).where(
                Chapter.novel_id == novel_id,
                Chapter.status == "published",
            )
            ch_result = await session.execute(ch_stmt)
            ch_row = ch_result.one()
            total_chapters = ch_row[0]
            total_words = ch_row[1]
            last_chapter_at = ch_row[2]

            # Reader count (unique bookmarks)
            reader_stmt = select(
                func.count(ReaderBookmark.id)
            ).where(ReaderBookmark.novel_id == novel_id)
            reader_result = await session.execute(reader_stmt)
            total_readers = reader_result.scalar_one()

            # Ratings
            rating_stmt = select(
                func.avg(NovelRating.rating),
                func.count(NovelRating.id),
            ).where(NovelRating.novel_id == novel_id)
            rating_result = await session.execute(rating_stmt)
            rating_row = rating_result.one()
            avg_rating = float(rating_row[0]) if rating_row[0] is not None else None
            rating_count = rating_row[1]

            # Upsert NovelStats
            stats_stmt = select(NovelStats).where(
                NovelStats.novel_id == novel_id
            )
            stats_result = await session.execute(stats_stmt)
            stats = stats_result.scalar_one_or_none()

            if stats is None:
                stats = NovelStats(novel_id=novel_id)
                session.add(stats)

            stats.total_chapters = total_chapters
            stats.total_words = total_words
            stats.total_readers = total_readers
            stats.avg_rating = avg_rating
            stats.rating_count = rating_count
            stats.last_chapter_at = last_chapter_at

            refreshed += 1

        await session.commit()

    logger.info("novel_stats_refreshed", count=refreshed)
    return {"refreshed": refreshed}


# ---------------------------------------------------------------------------
# Cron: Stale Job Detection
# ---------------------------------------------------------------------------


async def detect_stale_jobs_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron (every 60s): Detect and recover stale generation jobs.

    A job is stale if status='running' and heartbeat_at > 120s old.
    Marks as stale, releases Redis locks, creates notification.
    """
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]
    health = ctx.get("health")

    if health is None:
        from aiwebnovel.worker.health import WorkerHealth
        health = WorkerHealth(ctx.get("settings"))

    async with session_factory() as session:
        recovered = await health.recover_stale_jobs(session, redis)

    # Dead-letter jobs stuck in failed/stale for over 24 hours
    dead_lettered = 0
    async with session_factory() as session:
        cutoff = _utcnow() - timedelta(hours=24)
        old_failed_stmt = (
            select(GenerationJob)
            .where(
                GenerationJob.status.in_(["failed", "stale"]),
                GenerationJob.completed_at < cutoff,
            )
            .limit(20)
        )
        old_jobs = (await session.execute(old_failed_stmt)).scalars().all()
        for job in old_jobs:
            await health.mark_dead_letter(
                session, job.id,
                f"Auto dead-lettered: {job.status} for >24h",
            )
            dead_lettered += 1

    logger.info(
        "stale_job_check_complete",
        stale_count=len(recovered),
        dead_lettered=dead_lettered,
    )
    return {"stale_count": len(recovered), "dead_lettered": dead_lettered}
