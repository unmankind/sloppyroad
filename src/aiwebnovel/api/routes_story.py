"""Novel CRUD routes: list, create, detail, settings, world generation, share."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from jose import JWTError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import (
    get_optional_user,
    require_db_author,
    require_novel_owner,
)
from aiwebnovel.auth.tier import check_lifetime_budget, check_world_limit
from aiwebnovel.db.models import (
    AuthorProfile,
    GenerationJob,
    Novel,
    NovelSeed,
    NovelSettings,
    NovelStats,
    NovelTag,
)
from aiwebnovel.db.schemas import (
    NovelCreate,
    NovelList,
    NovelRead,
    NovelSettingsRead,
    NovelTagRead,
    TagCatalogResponse,
    TagInfo,
)
from aiwebnovel.db.session import get_db
from aiwebnovel.story.seeds import select_seeds
from aiwebnovel.story.tags import ALL_TAGS, TAG_CATEGORIES

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────


class NovelSettingsUpdate(BaseModel):
    planning_mode: Optional[str] = None
    pov_mode: Optional[str] = None
    content_rating: Optional[str] = None
    target_chapter_length: Optional[int] = None
    default_temperature: Optional[float] = None
    reader_influence_enabled: Optional[bool] = None
    image_generation_enabled: Optional[bool] = None
    autonomous_generation_enabled: Optional[bool] = None
    autonomous_cadence_hours: Optional[int] = None
    autonomous_skip_arc_boundaries: Optional[bool] = None
    generation_model: Optional[str] = None
    analysis_model: Optional[str] = None
    autonomous_daily_budget_cents: Optional[int] = None


class GenerateWorldResponse(BaseModel):
    job_id: int
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/", response_model=list[NovelList])
async def list_novels(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> list[NovelList]:
    """List public novels, or author's novels if authenticated."""
    # Try to get user from token (optional auth)
    from aiwebnovel.auth.jwt import decode_access_token

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = None
    if token:
        try:
            settings = request.app.state.settings
            payload = decode_access_token(
                token, settings.jwt_secret_key, settings.jwt_algorithm,
            )
            user_id = payload.get("user_id")
        except JWTError:
            pass

    if user_id:
        stmt = (
            select(Novel)
            .where(Novel.author_id == user_id)
            .order_by(Novel.updated_at.desc())
        )
    else:
        stmt = (
            select(Novel)
            .where(Novel.is_public.is_(True))
            .order_by(Novel.updated_at.desc())
        )

    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)
    result = await db.execute(stmt)
    novels = result.scalars().all()

    return [NovelList.model_validate(n) for n in novels]


@router.post("/", response_model=NovelRead, status_code=status.HTTP_201_CREATED)
async def create_novel(
    body: NovelCreate,
    request: Request,
    user: dict = Depends(require_db_author),
    db: AsyncSession = Depends(get_db),
) -> NovelRead:
    """Create a new novel."""
    settings = request.app.state.settings

    # Free tier limit checks
    allowed, reason = await check_world_limit(
        db, user["user_id"], settings,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason,
            headers={"HX-Trigger": "show-upgrade-modal"},
        )

    allowed, reason = await check_lifetime_budget(
        db, user["user_id"], settings,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason,
            headers={"HX-Trigger": "show-upgrade-modal"},
        )

    share_token = secrets.token_urlsafe(32)

    # Validate tags if provided
    if body.tags:
        invalid = [t for t in body.tags if t not in ALL_TAGS]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Unknown tags: {', '.join(invalid)}."
                    " Use GET /novels/tags/catalog for valid options."
                ),
            )

    novel = Novel(
        author_id=user["user_id"],
        title=body.title,
        genre=body.genre,
        share_token=share_token,
    )
    db.add(novel)
    await db.flush()

    # Create default settings (with custom conventions if provided)
    # Inherit image generation preference from author profile
    author_profile = (await db.execute(
        select(AuthorProfile).where(AuthorProfile.user_id == user["user_id"])
    )).scalar_one_or_none()
    settings = NovelSettings(
        novel_id=novel.id,
        image_generation_enabled=(
            author_profile.default_image_generation_enabled
            if author_profile else False
        ),
    )
    if body.custom_genre_conventions:
        settings.custom_genre_conventions = body.custom_genre_conventions
    db.add(settings)

    # Create stats record
    stats = NovelStats(novel_id=novel.id)
    db.add(stats)

    # Create tag records
    for tag_slug in body.tags:
        td = ALL_TAGS[tag_slug]
        tag = NovelTag(
            novel_id=novel.id,
            tag_name=tag_slug,
            tag_category=td.category,
            is_system_generated=False,
        )
        db.add(tag)

    # Select and persist diversity seeds for author review
    seeds = select_seeds(author_tags=body.tags)
    for seed in seeds:
        novel_seed = NovelSeed(
            novel_id=novel.id,
            seed_id=seed.id,
            seed_category=seed.category,
            seed_text=seed.text,
            status="proposed",
        )
        db.add(novel_seed)

    await db.flush()

    logger.info(
        "novel_created",
        novel_id=novel.id,
        author_id=user["user_id"],
        tags=body.tags,
    )

    return NovelRead.model_validate(novel)


@router.get("/{novel_id}", response_model=NovelRead)
async def get_novel(
    novel_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> NovelRead:
    """Get novel detail (public or owned by requester)."""
    stmt = select(Novel).where(Novel.id == novel_id)
    result = await db.execute(stmt)
    novel = result.scalar_one_or_none()

    if novel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Novel not found",
        )

    # Private novels require ownership
    if not novel.is_public:
        user = await get_optional_user(request)
        if user is None or user.get("user_id") != novel.author_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Novel not found",
            )

    return NovelRead.model_validate(novel)


@router.get("/{novel_id}/settings", response_model=NovelSettingsRead)
async def get_novel_settings(
    novel_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> NovelSettingsRead:
    """Get novel settings (author only)."""
    stmt = select(NovelSettings).where(NovelSettings.novel_id == novel_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Novel settings not found",
        )
    return NovelSettingsRead.model_validate(settings)


@router.put("/{novel_id}/settings", response_model=NovelSettingsRead)
async def update_novel_settings(
    novel_id: int,
    body: NovelSettingsUpdate,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> NovelSettingsRead:
    """Update novel settings (author only)."""
    stmt = select(NovelSettings).where(NovelSettings.novel_id == novel_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Novel settings not found",
        )

    update_data = body.model_dump(exclude_unset=True)

    # Validate model selections against allowed models
    from aiwebnovel.config import ALL_MODEL_IDS

    for model_field in ("generation_model", "analysis_model"):
        if model_field in update_data and update_data[model_field]:
            if update_data[model_field] not in ALL_MODEL_IDS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid model: {update_data[model_field]}",
                )

    for field_name, value in update_data.items():
        setattr(settings, field_name, value)

    await db.flush()
    logger.info("novel_settings_updated", novel_id=novel_id)

    return NovelSettingsRead.model_validate(settings)


@router.post("/{novel_id}/generate-world", response_model=GenerateWorldResponse)
async def generate_world(
    novel_id: int,
    request: Request,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> GenerateWorldResponse:
    """Trigger world generation pipeline. Returns job_id for tracking."""
    settings = request.app.state.settings

    # Budget check before world generation
    allowed, reason = await check_lifetime_budget(
        db, user["user_id"], settings,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason,
            headers={"HX-Trigger": "show-upgrade-modal"},
        )

    # Create a generation job
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    job = GenerationJob(
        novel_id=novel_id,
        job_type="world_generation",
        status="queued",
        heartbeat_at=now,
    )
    db.add(job)
    await db.flush()

    # Enqueue world generation task via arq
    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        try:
            from aiwebnovel.worker.queue import enqueue_task

            await enqueue_task(
                arq_pool,
                "generate_world_task",
                novel_id=novel_id,
                user_id=user["user_id"],
            )
            job.status = "running"
            await db.flush()
        except (SQLAlchemyError, ValueError, RuntimeError) as exc:
            logger.warning("enqueue_world_failed", error=str(exc), job_id=job.id)
    else:
        logger.warning("arq_pool_unavailable", job_id=job.id)

    logger.info("world_generation_queued", novel_id=novel_id, job_id=job.id)

    return GenerateWorldResponse(
        job_id=job.id,
        message="World generation queued",
    )


@router.get("/s/{share_token}", response_model=NovelRead)
async def get_shared_novel(
    share_token: str,
    db: AsyncSession = Depends(get_db),
) -> NovelRead:
    """Access a novel via share token (anyone with the link)."""
    stmt = select(Novel).where(Novel.share_token == share_token)
    result = await db.execute(stmt)
    novel = result.scalar_one_or_none()

    if novel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Novel not found",
        )

    return NovelRead.model_validate(novel)


# ── Tag management ──────────────────────────────────────────────────────────


@router.get("/tags/catalog", response_model=TagCatalogResponse)
async def get_tag_catalog() -> TagCatalogResponse:
    """Return the full tag taxonomy for UI display."""
    categories: dict[str, list[TagInfo]] = {}
    for cat_name, tag_defs in TAG_CATEGORIES.items():
        categories[cat_name] = [
            TagInfo(
                name=td.name,
                slug=td.slug,
                category=td.category,
                description=td.description,
            )
            for td in tag_defs
        ]
    return TagCatalogResponse(categories=categories)


@router.get("/{novel_id}/tags", response_model=list[NovelTagRead])
async def get_novel_tags(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[NovelTagRead]:
    """List all tags for a novel."""
    stmt = select(NovelTag).where(NovelTag.novel_id == novel_id)
    result = await db.execute(stmt)
    tags = result.scalars().all()
    return [NovelTagRead.model_validate(t) for t in tags]


class AddTagsRequest(BaseModel):
    tags: list[str] = Field(..., min_length=1, max_length=10)


@router.post("/{novel_id}/tags", response_model=list[NovelTagRead])
async def add_novel_tags(
    novel_id: int,
    body: AddTagsRequest,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[NovelTagRead]:
    """Add tags to a novel (author only)."""
    invalid = [t for t in body.tags if t not in ALL_TAGS]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown tags: {', '.join(invalid)}",
        )

    added: list[NovelTag] = []
    for tag_slug in body.tags:
        # Check if already exists
        existing = (await db.execute(
            select(NovelTag).where(
                NovelTag.novel_id == novel_id,
                NovelTag.tag_name == tag_slug,
            )
        )).scalar_one_or_none()
        if existing:
            continue

        td = ALL_TAGS[tag_slug]
        tag = NovelTag(
            novel_id=novel_id,
            tag_name=tag_slug,
            tag_category=td.category,
            is_system_generated=False,
        )
        db.add(tag)
        added.append(tag)

    await db.flush()
    return [NovelTagRead.model_validate(t) for t in added]


@router.delete("/{novel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_novel(
    novel_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete a novel and all its associated data (author only).

    Cascade-deletes chapters, drafts, world building stages, generation jobs, etc.
    """
    novel = (
        await db.execute(select(Novel).where(Novel.id == novel_id))
    ).scalar_one_or_none()

    if novel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Novel not found",
        )

    if novel.author_id != user["user_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this novel",
        )

    await db.delete(novel)
    await db.flush()
    logger.info("novel_deleted", novel_id=novel_id, user_id=user["user_id"])


@router.delete("/{novel_id}/tags/{tag_slug}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_novel_tag(
    novel_id: int,
    tag_slug: str,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a tag from a novel (author only)."""
    tag = (await db.execute(
        select(NovelTag).where(
            NovelTag.novel_id == novel_id,
            NovelTag.tag_name == tag_slug,
        )
    )).scalar_one_or_none()

    if tag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag '{tag_slug}' not found on this novel",
        )

    await db.delete(tag)
    await db.flush()
