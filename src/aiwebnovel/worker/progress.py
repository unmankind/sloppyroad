"""Progress reporting via Redis pub/sub.

Separated from queue.py to avoid circular imports with tasks.py.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def report_progress(
    ctx: dict[str, Any],
    stage: str,
    progress: float,
    job_id: str | None = None,
) -> None:
    """Publish progress to Redis pub/sub for SSE consumption.

    Channel: ``job:<job_id>:progress``
    Payload: JSON with ``stage`` and ``progress`` fields.
    """
    redis = ctx.get("redis")
    if redis is None or job_id is None:
        return

    channel = f"job:{job_id}:progress"
    payload = json.dumps({"stage": stage, "progress": progress})

    try:
        await redis.publish(channel, payload)
    except Exception:
        logger.warning(
            "progress_publish_failed",
            channel=channel,
            stage=stage,
            progress=progress,
        )
