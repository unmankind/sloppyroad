"""All arq task implementations — thin re-export shim.

The actual implementations live in:
- tasks_common.py   — shared helpers (_utcnow, _mark_job_failed, enqueue_art_generation)
- tasks_generation.py — world, chapter, arc, autonomous tick
- tasks_images.py   — art queue, image gen, scene images, regeneration
- tasks_maintenance.py — stale jobs, stats refresh, summaries, embeddings, post-analysis

This module re-exports everything so that existing imports from
``aiwebnovel.worker.tasks`` continue to work unchanged.
"""

from __future__ import annotations

# --- Common helpers ---
from aiwebnovel.worker.tasks_common import (  # noqa: F401
    _mark_job_failed,
    _utcnow,
    enqueue_art_generation,
    report_progress,
)

# --- Generation tasks ---
from aiwebnovel.worker.tasks_generation import (  # noqa: F401
    autonomous_tick_task,
    generate_arc_task,
    generate_chapter_task,
    generate_world_task,
)

# --- Image tasks ---
from aiwebnovel.worker.tasks_images import (  # noqa: F401
    _generate_initial_assets,
    _trigger_chapter_images,
    _trigger_scene_images,
    generate_image_task,
    generate_scene_image_task,
    process_art_queue_task,
    regenerate_image_task,
)

# --- Maintenance tasks ---
from aiwebnovel.worker.tasks_maintenance import (  # noqa: F401
    detect_stale_jobs_task,
    embed_bible_entries_task,
    generate_arc_summary_task,
    generate_chapter_summary_task,
    refresh_novel_stats_task,
    run_post_analysis_task,
)

__all__ = [
    # Common
    "_mark_job_failed",
    "_utcnow",
    "enqueue_art_generation",
    "report_progress",
    # Generation
    "autonomous_tick_task",
    "generate_arc_task",
    "generate_chapter_task",
    "generate_world_task",
    # Images
    "_generate_initial_assets",
    "_trigger_chapter_images",
    "_trigger_scene_images",
    "generate_image_task",
    "generate_scene_image_task",
    "process_art_queue_task",
    "regenerate_image_task",
    # Maintenance
    "detect_stale_jobs_task",
    "embed_bible_entries_task",
    "generate_arc_summary_task",
    "generate_chapter_summary_task",
    "refresh_novel_stats_task",
    "run_post_analysis_task",
]
