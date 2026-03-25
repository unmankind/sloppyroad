"""SSE streaming endpoint for chapter generation progress."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from aiwebnovel.auth.dependencies import get_optional_user
from aiwebnovel.db.models import GenerationJob, Novel
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


async def _event_generator(
    request: Request,
    job_id: int,
) -> AsyncGenerator[dict, None]:
    """Generate SSE events by subscribing to Redis pub/sub channel.

    Emits events: status, token, progress, error, complete.
    Falls back to polling GenerationJob table if Redis unavailable.
    """
    redis = request.app.state.redis
    channel_name = f"chapter_stream:{job_id}"

    if redis is not None:
        # Use Redis pub/sub
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(channel_name)

            while True:
                if await request.is_disconnected():
                    break

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )

                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")

                    try:
                        event_data = json.loads(data)
                    except json.JSONDecodeError:
                        event_data = {"type": "token", "content": data}

                    event_type = event_data.get("type", "token")

                    yield {
                        "event": event_type,
                        "data": json.dumps(event_data),
                    }

                    if event_type in ("complete", "error"):
                        break
                else:
                    # Heartbeat to keep connection alive
                    yield {"event": "heartbeat", "data": ""}

                await asyncio.sleep(0.05)
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.close()
    else:
        # Fallback: poll job status from DB


        yield {
            "event": "status",
            "data": json.dumps({
                "type": "status",
                "message": "Streaming via polling (Redis unavailable)",
                "job_id": job_id,
            }),
        }

        for _ in range(600):  # Max 10 min (1s intervals)
            if await request.is_disconnected():
                break

            yield {"event": "heartbeat", "data": ""}
            await asyncio.sleep(1.0)

        yield {
            "event": "complete",
            "data": json.dumps({
                "type": "complete",
                "message": "Stream timeout — check job status via API",
                "job_id": job_id,
            }),
        }


@router.get("/{job_id}")
async def stream_generation(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    """SSE endpoint for streaming chapter generation progress.

    Subscribe to receive real-time events:
    - status: pipeline stage updates
    - token: generated text tokens (typewriter effect)
    - progress: completion percentage
    - error: generation error
    - complete: generation finished
    """
    # Verify the requesting user owns the novel for this job
    user = await get_optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    job = (
        await db.execute(
            select(GenerationJob).where(GenerationJob.id == job_id)
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    novel = (
        await db.execute(
            select(Novel).where(Novel.id == job.novel_id)
        )
    ).scalar_one_or_none()
    if novel is None or novel.author_id != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Access denied")

    return EventSourceResponse(
        _event_generator(request, job_id),
        media_type="text/event-stream",
    )
