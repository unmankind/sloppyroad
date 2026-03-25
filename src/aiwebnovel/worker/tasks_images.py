"""Image-related task implementations.

Handles art queue processing, image generation, scene images,
regeneration, and image pipeline triggers.

Each task follows the arq pattern: ``async def task_name(ctx, **kwargs)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from aiwebnovel.auth.key_resolver import resolve_image_key
from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArtAsset,
    ArtGenerationQueue,
    Chapter,
    ChapterImage,
    ImageUsageLog,
    Notification,
    Novel,
)
from aiwebnovel.images.budget import check_image_budget, notify_image_budget_exceeded
from aiwebnovel.images.prompts import ImagePromptComposer, derive_style_from_world
from aiwebnovel.images.provider import get_image_provider
from aiwebnovel.worker.progress import report_progress
from aiwebnovel.worker.tasks_common import _utcnow, enqueue_art_generation

logger = structlog.get_logger(__name__)


async def _resolve_novel_image_key(
    session_factory: Any,
    novel_id: int,
    settings: Settings,
) -> str | None:
    """Resolve BYOK Replicate key for a novel's author. Returns None for platform key."""
    async with session_factory() as session:
        author_id = (
            await session.execute(
                select(Novel.author_id).where(Novel.id == novel_id)
            )
        ).scalar_one_or_none()
        if not author_id:
            return None
        return await resolve_image_key(session, author_id, settings)


# ---------------------------------------------------------------------------
# Art Generation Queue
# ---------------------------------------------------------------------------


async def process_art_queue_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """Process pending art generation queue items.

    Queries pending items ordered by priority (lower = higher),
    dispatches to the appropriate generation function, and
    updates queue status on success/failure.
    """
    session_factory = ctx["session_factory"]
    settings: Settings = ctx["settings"]
    processed = 0
    failed = 0

    # Early exit: if image generation is disabled, mark all pending as failed
    # with a helpful message instead of letting them crash
    if not getattr(settings, "image_enabled", False):
        reason = (
            "Image generation is disabled. "
            "Set AIWN_IMAGE_ENABLED=true and configure a provider to enable it."
        )

        async with session_factory() as session:
            stmt = (
                select(ArtGenerationQueue)
                .where(ArtGenerationQueue.status == "pending")
                .limit(25)
            )
            pending_items = (await session.execute(stmt)).scalars().all()
            for item in pending_items:
                item.status = "failed"
                item.error_message = reason
            await session.commit()

            if pending_items:
                logger.warning(
                    "art_queue_images_disabled",
                    count=len(pending_items),
                    hint="Set AIWN_IMAGE_ENABLED=true to enable",
                )

        return {"processed": 0, "failed": len(pending_items), "budget_blocked": 0}

    # Fetch batch of pending items
    async with session_factory() as session:
        stmt = (
            select(ArtGenerationQueue)
            .where(ArtGenerationQueue.status == "pending")
            .order_by(
                ArtGenerationQueue.priority.asc(),
                ArtGenerationQueue.created_at.asc(),
            )
            .limit(25)
        )
        result = await session.execute(stmt)
        pending = result.scalars().all()
        # Detach data before leaving session
        pending_data = [
            {
                "id": item.id,
                "novel_id": item.novel_id,
                "asset_type": item.asset_type,
                "entity_id": item.entity_id,
                "entity_type": item.entity_type,
                "source_asset_id": item.source_asset_id,
                "feedback": item.feedback,
            }
            for item in pending
        ]

    budget_blocked = 0

    for item_data in pending_data:
        queue_id = item_data["id"]

        # Budget check before processing each item
        async with session_factory() as session:
            budget = await check_image_budget(session, item_data["novel_id"])
            if not budget.allowed:
                stmt = select(ArtGenerationQueue).where(ArtGenerationQueue.id == queue_id)
                res = await session.execute(stmt)
                item = res.scalar_one()
                item.status = "budget_blocked"
                item.error_message = budget.reason

                # Notify author
                novel_stmt = select(Novel.author_id).where(Novel.id == item_data["novel_id"])
                novel_result = await session.execute(novel_stmt)
                author_id = novel_result.scalar_one_or_none() or 0
                await notify_image_budget_exceeded(
                    session, item_data["novel_id"], author_id, budget.reason,
                )
                await session.commit()
                budget_blocked += 1
                logger.info(
                    "art_queue_item_budget_blocked",
                    queue_id=queue_id,
                    novel_id=item_data["novel_id"],
                    reason=budget.reason,
                )
                continue

        # Mark as generating
        async with session_factory() as session:
            stmt = select(ArtGenerationQueue).where(ArtGenerationQueue.id == queue_id)
            res = await session.execute(stmt)
            item = res.scalar_one()
            item.status = "generating"
            await session.commit()

        try:
            # Dispatch: regeneration, scene chapter_images, or standard generation
            if item_data["source_asset_id"] and item_data["feedback"]:
                await regenerate_image_task(
                    ctx,
                    novel_id=item_data["novel_id"],
                    source_asset_id=item_data["source_asset_id"],
                    feedback=item_data["feedback"],
                )
            elif item_data["asset_type"] == "scene" and item_data["entity_type"] == "chapter_image":
                await generate_scene_image_task(
                    ctx,
                    novel_id=item_data["novel_id"],
                    chapter_image_id=item_data["entity_id"],
                )
            else:
                await generate_image_task(
                    ctx,
                    novel_id=item_data["novel_id"],
                    asset_type=item_data["asset_type"],
                    entity_id=item_data["entity_id"] or 0,
                    entity_type=item_data["entity_type"] or "",
                    user_id=0,
                )

            # Mark complete
            async with session_factory() as session:
                stmt = select(ArtGenerationQueue).where(ArtGenerationQueue.id == queue_id)
                res = await session.execute(stmt)
                item = res.scalar_one()
                item.status = "complete"
                item.completed_at = _utcnow()
                await session.commit()

            processed += 1

        except (SQLAlchemyError, RuntimeError, OSError) as exc:
            logger.warning(
                "art_queue_item_failed",
                queue_id=queue_id,
                error=str(exc),
            )
            async with session_factory() as session:
                stmt = select(ArtGenerationQueue).where(ArtGenerationQueue.id == queue_id)
                res = await session.execute(stmt)
                item = res.scalar_one()
                item.status = "failed"
                item.error_message = str(exc)[:1000]

                # Create notification for the novel's author
                novel_stmt = select(Novel.author_id, Novel.title).where(
                    Novel.id == item_data["novel_id"]
                )
                novel_row = (await session.execute(novel_stmt)).one_or_none()
                if novel_row:
                    author_id, novel_title = novel_row
                    error_brief = str(exc)[:200]
                    notification = Notification(
                        user_id=author_id,
                        novel_id=item_data["novel_id"],
                        notification_type="image_failed",
                        title="Image generation failed",
                        message=(
                            f"Failed to generate {item_data['asset_type']} image"
                            f" for \"{novel_title}\": {error_brief}"
                        ),
                        action_url=f"/novels/{item_data['novel_id']}/gallery",
                        related_entity_id=queue_id,
                        related_entity_type="art_generation_queue",
                    )
                    session.add(notification)

                await session.commit()
            failed += 1

    logger.info(
        "art_queue_processed",
        processed=processed,
        failed=failed,
        budget_blocked=budget_blocked,
        total=len(pending_data),
    )
    return {"processed": processed, "failed": failed, "budget_blocked": budget_blocked}


# ---------------------------------------------------------------------------
# Image Pipeline Triggers
# ---------------------------------------------------------------------------


async def _generate_initial_assets(
    ctx: dict[str, Any],
    novel_id: int,
    user_id: int,
) -> None:
    """Enqueue protagonist portrait + world map after world pipeline completes.

    Called from generate_world_task. Creates ArtGenerationQueue entries
    for processing by the art queue worker.
    """
    try:
        await report_progress(
            ctx, stage="enqueuing_initial_art", progress=0.9,
            job_id=f"world-{novel_id}",
        )

        session_factory = ctx["session_factory"]

        # Derive art style from world data before generating any assets
        await derive_style_from_world(session_factory, novel_id)

        async with session_factory() as session:
            from aiwebnovel.db.models import Character

            # Cover art (highest priority — generate first)
            await enqueue_art_generation(
                session,
                novel_id=novel_id,
                asset_type="cover",
                entity_id=novel_id,
                entity_type="novel",
                priority=0,
                trigger_event="world_generation_complete",
            )

            # Character portraits — all characters, priority by role
            role_priority = {
                "protagonist": 1,
                "antagonist": 2,
                "supporting": 3,
            }
            char_stmt = (
                select(Character)
                .where(Character.novel_id == novel_id)
                .order_by(Character.id)
            )
            characters = (
                await session.execute(char_stmt)
            ).scalars().all()

            for character in characters:
                priority = role_priority.get(character.role, 3)
                await enqueue_art_generation(
                    session,
                    novel_id=novel_id,
                    asset_type="portrait",
                    entity_id=character.id,
                    entity_type="character",
                    priority=priority,
                    trigger_event="world_generation_complete",
                )

            # World map
            await enqueue_art_generation(
                session,
                novel_id=novel_id,
                asset_type="world_map",
                entity_id=novel_id,
                entity_type="novel",
                priority=1,
                trigger_event="world_generation_complete",
            )

            await session.commit()

        logger.info(
            "initial_assets_enqueued",
            novel_id=novel_id,
            portrait_count=len(characters),
        )

    except (SQLAlchemyError, RuntimeError) as exc:
        logger.warning(
            "initial_asset_enqueue_failed",
            novel_id=novel_id,
            error=str(exc),
        )


async def _trigger_chapter_images(
    ctx: dict[str, Any],
    novel_id: int,
    analysis: Any,
) -> None:
    """Check analysis for events that warrant image generation.

    Triggers:
    - Character rank-up (new_rank set) -> enqueue portrait evolution
    Failures are logged but do not fail the chapter task.
    """
    if not analysis.system or not analysis.system_success:
        return

    session_factory = ctx["session_factory"]

    for power_event in analysis.system.power_events:
        if not power_event.new_rank:
            continue

        try:
            async with session_factory() as session:
                from aiwebnovel.db.models import Character

                stmt = (
                    select(Character)
                    .where(
                        Character.novel_id == novel_id,
                        Character.name == power_event.character_name,
                    )
                )
                result = await session.execute(stmt)
                character = result.scalar_one_or_none()

                if character is None:
                    logger.debug(
                        "rank_up_character_not_found",
                        name=power_event.character_name,
                    )
                    continue

                await enqueue_art_generation(
                    session,
                    novel_id=novel_id,
                    asset_type="portrait",
                    entity_id=character.id,
                    entity_type="character",
                    priority=3,
                    trigger_event=f"rank_up:{power_event.new_rank}",
                )
                await session.commit()

            logger.info(
                "rank_up_portrait_enqueued",
                novel_id=novel_id,
                character=power_event.character_name,
                new_rank=power_event.new_rank,
            )
        except (SQLAlchemyError, RuntimeError) as exc:
            logger.warning(
                "rank_up_portrait_enqueue_failed",
                character=power_event.character_name,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Scene Image Generation (inline chapter illustrations)
# ---------------------------------------------------------------------------


async def _trigger_scene_images(
    ctx: dict[str, Any],
    novel_id: int,
    chapter_id: int | None,
) -> None:
    """Enqueue scene image generation for pending ChapterImage records.

    Called from generate_chapter_task after a successful chapter with
    scene markers. Failures are logged but never block the chapter pipeline.
    """
    if chapter_id is None:
        return

    session_factory = ctx["session_factory"]

    try:
        async with session_factory() as session:
            stmt = (
                select(ChapterImage)
                .where(
                    ChapterImage.chapter_id == chapter_id,
                    ChapterImage.status == "pending",
                )
            )
            result = await session.execute(stmt)
            pending_images = result.scalars().all()

            for chapter_image in pending_images:
                try:
                    await enqueue_art_generation(
                        session,
                        novel_id=novel_id,
                        asset_type="scene",
                        entity_id=chapter_image.id,
                        entity_type="chapter_image",
                        priority=5,
                        trigger_event="chapter_scene_marker",
                        trigger_chapter=chapter_id,
                    )
                except (SQLAlchemyError, RuntimeError) as exc:
                    logger.warning(
                        "scene_image_enqueue_failed",
                        chapter_image_id=chapter_image.id,
                        error=str(exc),
                    )

            await session.commit()
    except (SQLAlchemyError, RuntimeError) as exc:
        logger.warning(
            "trigger_scene_images_failed",
            chapter_id=chapter_id,
            error=str(exc),
        )


async def regenerate_image_task(
    ctx: dict[str, Any],
    novel_id: int,
    source_asset_id: int,
    feedback: str,
) -> dict[str, Any]:
    """Regenerate an image based on author feedback.

    1. Check image budget
    2. Load source ArtAsset
    3. Compose revised prompt via ImagePromptComposer
    4. Call image provider
    5. Save new version to disk
    6. DB: mark old asset not current, create new asset, update ChapterImage if scene
    7. Log cost
    """
    settings: Settings = ctx["settings"]
    llm = ctx["llm"]
    session_factory = ctx["session_factory"]

    # 1. Budget check
    async with session_factory() as session:
        budget = await check_image_budget(session, novel_id)
        if not budget.allowed:
            novel_stmt = select(Novel.author_id).where(Novel.id == novel_id)
            author_id = (await session.execute(novel_stmt)).scalar_one_or_none() or 0
            await notify_image_budget_exceeded(session, novel_id, author_id, budget.reason)
            await session.commit()
            return {"success": False, "skipped": True, "reason": budget.reason}

    # 2. Load source asset
    async with session_factory() as session:
        source = await session.get(ArtAsset, source_asset_id)
        if source is None:
            return {"success": False, "error": "Source asset not found"}

        asset_type = source.asset_type
        entity_id = source.entity_id
        entity_type = source.entity_type
        old_version = source.version
        chapter_context = source.chapter_context

    # 3. Compose revised prompt
    composer = ImagePromptComposer(llm, settings)
    request = await composer.compose_regeneration_prompt(
        session_factory, source_asset_id, feedback,
    )

    # 4. Call provider (with BYOK key if available)
    byok_key = await _resolve_novel_image_key(session_factory, novel_id, settings)
    provider = get_image_provider(
        settings, model_override=request.model_preference, api_token=byok_key,
    )
    generated = await provider.generate(request)

    # 5. Save to disk
    new_version = old_version + 1
    entity_slug = f"{entity_id}" if entity_id else "none"
    asset_dir = Path(settings.image_asset_path) / str(novel_id) / f"{asset_type}_{entity_slug}"
    asset_dir.mkdir(parents=True, exist_ok=True)
    file_path = asset_dir / f"v{new_version}.png"
    file_path.write_bytes(generated.image_data)
    relative_path = str(file_path.relative_to(Path(settings.image_asset_path)))

    # 6. DB transaction
    cost_cents = settings.image_pricing.get(settings.image_provider, 0.0)

    async with session_factory() as session:
        # Mark old asset as not current
        old_asset = await session.get(ArtAsset, source_asset_id)
        if old_asset:
            old_asset.is_current = False

        # Create new asset
        new_asset = ArtAsset(
            novel_id=novel_id,
            asset_type=asset_type,
            entity_id=entity_id,
            entity_type=entity_type,
            prompt_used=request.prompt,
            file_path=relative_path,
            provider=generated.provider,
            model_used=generated.model,
            width=generated.width,
            height=generated.height,
            seed_value=generated.seed,
            chapter_context=chapter_context,
            version=new_version,
            is_current=True,
            parent_asset_id=source_asset_id,
        )
        session.add(new_asset)
        await session.flush()
        new_asset_id = new_asset.id

        # If this was a scene image, update any ChapterImage pointing to the old asset
        if asset_type == "scene":
            ci_stmt = select(ChapterImage).where(
                ChapterImage.art_asset_id == source_asset_id,
            )
            chapter_images = (await session.execute(ci_stmt)).scalars().all()
            for ci in chapter_images:
                ci.art_asset_id = new_asset_id

        # 7. Log cost
        usage_log = ImageUsageLog(
            novel_id=novel_id,
            provider=generated.provider,
            model=generated.model,
            dimensions=f"{generated.width}x{generated.height}",
            cost_cents=cost_cents,
            purpose=f"{asset_type}_regeneration",
            art_asset_id=new_asset_id,
        )
        session.add(usage_log)

        await llm.budget_checker.update_spent(
            session, novel_id, cost_cents, cost_type="image",
        )
        await session.commit()

    logger.info(
        "image_regenerated",
        novel_id=novel_id,
        source_asset_id=source_asset_id,
        new_asset_id=new_asset_id,
        version=new_version,
    )

    return {
        "success": True,
        "asset_id": new_asset_id,
        "file_path": relative_path,
        "version": new_version,
    }


async def generate_scene_image_task(
    ctx: dict[str, Any],
    novel_id: int,
    chapter_image_id: int,
) -> dict[str, Any]:
    """Generate a scene illustration for a ChapterImage record.

    0. Check image budget (author + novel level)
    1. Load ChapterImage + Chapter for context
    2. Compose prompt via ImagePromptComposer (full style guide)
    3. Call image provider
    4. Save to disk at {asset_path}/{novel_id}/scene_{chapter_id}_{para_idx}/v1.png
    5. Create ArtAsset record
    6. Update ChapterImage with art_asset_id + status=complete
    7. Log cost to ImageUsageLog
    """
    settings: Settings = ctx["settings"]
    session_factory = ctx["session_factory"]

    # 0. Check budget (skip gracefully if exhausted)
    async with session_factory() as session:
        budget = await check_image_budget(session, novel_id)
        if not budget.allowed:
            # Resolve author_id for notification
            novel_stmt = select(Novel.author_id).where(Novel.id == novel_id)
            novel_result = await session.execute(novel_stmt)
            author_id = novel_result.scalar_one_or_none() or 0
            await notify_image_budget_exceeded(
                session, novel_id, author_id, budget.reason,
            )
            await session.commit()
            logger.info(
                "scene_image_skipped_budget",
                novel_id=novel_id,
                chapter_image_id=chapter_image_id,
                reason=budget.reason,
            )
            return {"success": False, "skipped": True, "reason": budget.reason}

    # 1. Load ChapterImage
    llm = ctx["llm"]
    async with session_factory() as session:
        stmt = select(ChapterImage).where(ChapterImage.id == chapter_image_id)
        result = await session.execute(stmt)
        chapter_image = result.scalar_one_or_none()

        if chapter_image is None:
            return {"success": False, "error": "ChapterImage not found"}

        chapter_id = chapter_image.chapter_id
        scene_description = chapter_image.scene_description
        paragraph_index = chapter_image.paragraph_index

        # Get chapter number for context
        ch_stmt = select(Chapter.chapter_number).where(Chapter.id == chapter_id)
        ch_result = await session.execute(ch_stmt)
        chapter_number = ch_result.scalar_one_or_none() or 0

        # Mark as generating
        chapter_image.status = "generating"
        await session.commit()

    # 2 + 3. Compose prompt via ImagePromptComposer (uses full style guide)
    composer = ImagePromptComposer(llm, settings)
    request = await composer.compose_scene_prompt(
        session_factory, novel_id, scene_description,
    )
    byok_key = await _resolve_novel_image_key(session_factory, novel_id, settings)
    provider = get_image_provider(
        settings, model_override=request.model_preference, api_token=byok_key,
    )

    try:
        generated = await provider.generate(request)
    except (SQLAlchemyError, RuntimeError, OSError) as exc:
        # Mark as failed with error message
        async with session_factory() as session:
            stmt = select(ChapterImage).where(ChapterImage.id == chapter_image_id)
            result = await session.execute(stmt)
            ci = result.scalar_one_or_none()
            if ci:
                ci.status = "failed"
                ci.error_message = str(exc)[:1000]
                await session.commit()
        raise

    # 5. Save to disk
    scene_dir = f"scene_{chapter_id}_{paragraph_index}"
    asset_dir = (
        Path(settings.image_asset_path) / str(novel_id) / scene_dir
    )
    asset_dir.mkdir(parents=True, exist_ok=True)
    file_path = asset_dir / "v1.png"
    file_path.write_bytes(generated.image_data)
    relative_path = str(file_path.relative_to(Path(settings.image_asset_path)))

    # 6 + 7 + 8. Create ArtAsset, link to ChapterImage, log cost
    cost_cents = settings.image_pricing.get(settings.image_provider, 0.0)

    async with session_factory() as session:
        asset = ArtAsset(
            novel_id=novel_id,
            asset_type="scene",
            entity_id=chapter_id,
            entity_type="chapter",
            prompt_used=request.prompt,
            file_path=relative_path,
            provider=generated.provider,
            model_used=generated.model,
            width=generated.width,
            height=generated.height,
            seed_value=generated.seed,
            chapter_context=chapter_number,
            version=1,
            is_current=True,
        )
        session.add(asset)
        await session.flush()

        # Update ChapterImage
        ci_stmt = select(ChapterImage).where(ChapterImage.id == chapter_image_id)
        ci_result = await session.execute(ci_stmt)
        ci = ci_result.scalar_one()
        ci.art_asset_id = asset.id
        ci.status = "complete"

        # Log cost
        usage_log = ImageUsageLog(
            novel_id=novel_id,
            provider=generated.provider,
            model=generated.model,
            dimensions=f"{generated.width}x{generated.height}",
            cost_cents=cost_cents,
            purpose="scene",
            art_asset_id=asset.id,
        )
        session.add(usage_log)

        # Update budget counters (author + novel)
        llm = ctx["llm"]
        await llm.budget_checker.update_spent(
            session, novel_id, cost_cents, cost_type="image"
        )
        await session.commit()

    logger.info(
        "scene_image_generated",
        novel_id=novel_id,
        chapter_image_id=chapter_image_id,
        paragraph_index=paragraph_index,
    )

    return {
        "success": True,
        "asset_id": asset.id,
        "file_path": str(file_path),
    }


# ---------------------------------------------------------------------------
# Image Generation
# ---------------------------------------------------------------------------


async def generate_image_task(
    ctx: dict[str, Any],
    novel_id: int,
    asset_type: str,
    entity_id: int,
    entity_type: str,
    user_id: int,
) -> dict[str, Any]:
    """Generate an image asset.

    1. Check image budget (author + novel level)
    2. Compose prompt via ImagePromptComposer
    3. Call image provider
    4. Store result as ArtAsset
    5. Log cost to image_usage_log
    """
    settings: Settings = ctx["settings"]
    llm = ctx["llm"]
    session_factory = ctx["session_factory"]

    # 1. Check budget (skip gracefully if exhausted)
    async with session_factory() as session:
        budget = await check_image_budget(session, novel_id)
        if not budget.allowed:
            await notify_image_budget_exceeded(
                session, novel_id, user_id, budget.reason,
            )
            await session.commit()
            logger.info(
                "image_generation_skipped_budget",
                novel_id=novel_id,
                reason=budget.reason,
            )
            return {"success": False, "skipped": True, "reason": budget.reason}

    # 2. Compose prompt (uses full style guide: model_preference, default_params, etc.)
    composer = ImagePromptComposer(llm, settings)

    logger.info(
        "image_generation_composing_prompt",
        novel_id=novel_id,
        asset_type=asset_type,
        entity_id=entity_id,
    )

    if asset_type == "cover":
        request = await composer.compose_cover_prompt(session_factory, novel_id)
    elif asset_type == "portrait":
        request = await composer.compose_portrait_prompt(session_factory, entity_id)
    elif asset_type == "world_map":
        request = await composer.compose_map_prompt(session_factory, novel_id)
    elif asset_type == "scene":
        request = await composer.compose_scene_prompt(
            session_factory, novel_id, f"Scene for {entity_type} {entity_id}"
        )
    else:
        request = await composer.compose_scene_prompt(
            session_factory, novel_id, f"{asset_type} for {entity_type} {entity_id}"
        )

    # 3. Call provider (model_preference from style guide overrides default)
    byok_key = await _resolve_novel_image_key(session_factory, novel_id, settings)
    provider = get_image_provider(
        settings, model_override=request.model_preference, api_token=byok_key,
    )
    generated = await provider.generate(request)

    # 4. Save image to disk
    entity_slug = f"{entity_id}" if entity_id else "none"
    asset_dir = Path(settings.image_asset_path) / str(novel_id) / f"{asset_type}_{entity_slug}"
    asset_dir.mkdir(parents=True, exist_ok=True)
    file_path = asset_dir / "v1.png"
    file_path.write_bytes(generated.image_data)

    # 5. Store result in DB
    cost_cents = settings.image_pricing.get(settings.image_provider, 0.0)
    # file_path relative to image_asset_path for URL serving
    relative_path = str(file_path.relative_to(Path(settings.image_asset_path)))

    async with session_factory() as session:
        asset = ArtAsset(
            novel_id=novel_id,
            asset_type=asset_type,
            entity_id=entity_id,
            entity_type=entity_type,
            prompt_used=request.prompt,
            file_path=relative_path,
            provider=generated.provider,
            model_used=generated.model,
            width=generated.width,
            height=generated.height,
            seed_value=generated.seed,
            version=1,
            is_current=True,
        )
        session.add(asset)
        await session.flush()
        asset_id = asset.id

        # 6. Log cost
        usage_log = ImageUsageLog(
            novel_id=novel_id,
            provider=generated.provider,
            model=generated.model,
            dimensions=f"{generated.width}x{generated.height}",
            cost_cents=cost_cents,
            purpose=asset_type,
            art_asset_id=asset_id,
        )
        session.add(usage_log)

        # Update budget
        await llm.budget_checker.update_spent(
            session, novel_id, cost_cents, cost_type="image"
        )
        await session.commit()

    return {
        "success": True,
        "asset_id": asset_id,
        "file_path": relative_path,
        "provider": generated.provider,
        "cost_cents": cost_cents,
    }
