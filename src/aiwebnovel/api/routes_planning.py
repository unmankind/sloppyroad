"""Arc and chapter planning routes."""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import require_novel_owner
from aiwebnovel.db.models import ArcPlan, ChapterPlan
from aiwebnovel.db.queries import get_active_plot_threads
from aiwebnovel.db.schemas import ArcPlanRead, PlotThreadRead
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────


class ArcReviseRequest(BaseModel):
    author_notes: str = Field(..., min_length=1, max_length=5000)


class ChapterPlanRead(BaseModel):
    id: int
    novel_id: int
    arc_plan_id: Optional[int] = None
    chapter_number: int
    title: Optional[str] = None
    status: str
    is_bridge: bool = False

    class Config:
        from_attributes = True


class GenerateArcResponse(BaseModel):
    arc_id: int
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/{novel_id}/arcs", response_model=list[ArcPlanRead])
async def list_arcs(
    novel_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[ArcPlanRead]:
    """List all arc plans for a novel."""
    stmt = (
        select(ArcPlan)
        .where(ArcPlan.novel_id == novel_id)
        .order_by(ArcPlan.arc_number.asc())
    )
    result = await db.execute(stmt)
    arcs = result.scalars().all()
    return [ArcPlanRead.model_validate(a) for a in arcs]


@router.get("/{novel_id}/arcs/{arc_id}", response_model=ArcPlanRead)
async def get_arc(
    novel_id: int,
    arc_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> ArcPlanRead:
    """Get arc detail."""
    stmt = select(ArcPlan).where(ArcPlan.id == arc_id, ArcPlan.novel_id == novel_id)
    result = await db.execute(stmt)
    arc = result.scalar_one_or_none()
    if arc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arc not found")
    return ArcPlanRead.model_validate(arc)


@router.post("/{novel_id}/arcs/generate", response_model=GenerateArcResponse)
async def generate_arc(
    novel_id: int,
    request: Request,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> GenerateArcResponse:
    """Generate a new arc plan via LLM. Returns arc_id."""
    # Create a placeholder arc to be populated by the planner
    from sqlalchemy import func as sa_func

    arc_count_stmt = select(sa_func.count(ArcPlan.id)).where(ArcPlan.novel_id == novel_id)
    count_result = await db.execute(arc_count_stmt)
    next_arc = (count_result.scalar_one() or 0) + 1

    arc = ArcPlan(
        novel_id=novel_id,
        arc_number=next_arc,
        title=f"Arc {next_arc} (generating...)",
        description="Arc plan generation in progress",
        status="generating",
    )
    db.add(arc)
    await db.flush()

    # Enqueue arc planning task via arq
    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        try:
            from aiwebnovel.worker.queue import enqueue_task

            await enqueue_task(
                arq_pool,
                "generate_arc_task",
                novel_id=novel_id,
                arc_id=arc.id,
                user_id=user["user_id"],
            )
        except (SQLAlchemyError, RuntimeError, ValueError) as exc:
            logger.warning("enqueue_arc_failed", error=str(exc), arc_id=arc.id)
    else:
        logger.warning("arq_pool_unavailable", arc_id=arc.id)

    logger.info("arc_generation_queued", novel_id=novel_id, arc_id=arc.id)

    return GenerateArcResponse(arc_id=arc.id, message="Arc generation started")


@router.post("/{novel_id}/arcs/{arc_id}/approve", response_model=ArcPlanRead)
async def approve_arc(
    novel_id: int,
    arc_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> ArcPlanRead:
    """Approve an arc plan and decompose into chapter plans."""
    stmt = select(ArcPlan).where(ArcPlan.id == arc_id, ArcPlan.novel_id == novel_id)
    result = await db.execute(stmt)
    arc = result.scalar_one_or_none()
    if arc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arc not found")
    if arc.status not in ("proposed", "revised"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve arc in status '{arc.status}'",
        )

    # Decompose arc into chapter plans (the critical step)
    from aiwebnovel.story.planner import approve_arc_plans

    chapter_plans = await approve_arc_plans(db, arc_id)
    await db.flush()

    logger.info(
        "arc_approved", arc_id=arc.id, novel_id=novel_id,
        chapter_plans_created=len(chapter_plans),
    )
    return ArcPlanRead.model_validate(arc)


@router.post("/{novel_id}/arcs/{arc_id}/revise", response_model=ArcPlanRead)
async def revise_arc(
    novel_id: int,
    arc_id: int,
    body: ArcReviseRequest,
    request: Request,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> ArcPlanRead:
    """Submit revision notes for an arc plan."""
    stmt = select(ArcPlan).where(ArcPlan.id == arc_id, ArcPlan.novel_id == novel_id)
    result = await db.execute(stmt)
    arc = result.scalar_one_or_none()
    if arc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arc not found")

    arc.author_notes = body.author_notes
    arc.status = "revision_requested"
    await db.flush()

    # Enqueue revision task via arq (reuses arc generation with revision context)
    arq_pool = request.app.state.arq_pool
    if arq_pool is not None:
        try:
            from aiwebnovel.worker.queue import enqueue_task

            await enqueue_task(
                arq_pool,
                "generate_arc_task",
                novel_id=novel_id,
                arc_id=arc.id,
                user_id=user["user_id"],
                author_notes=body.author_notes,
            )
        except (SQLAlchemyError, RuntimeError, ValueError) as exc:
            logger.warning("enqueue_arc_revision_failed", error=str(exc), arc_id=arc.id)

    logger.info("arc_revision_requested", arc_id=arc.id, novel_id=novel_id)
    return ArcPlanRead.model_validate(arc)


@router.get("/{novel_id}/arcs/{arc_id}/chapters", response_model=list[ChapterPlanRead])
async def list_chapter_plans(
    novel_id: int,
    arc_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[ChapterPlanRead]:
    """List chapter plans within an arc."""
    stmt = (
        select(ChapterPlan)
        .where(ChapterPlan.arc_plan_id == arc_id, ChapterPlan.novel_id == novel_id)
        .order_by(ChapterPlan.chapter_number.asc())
    )
    result = await db.execute(stmt)
    plans = result.scalars().all()
    return [ChapterPlanRead.model_validate(p) for p in plans]


@router.post("/{novel_id}/chapters/{num}/approve")
async def approve_chapter_plan(
    novel_id: int,
    num: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve a chapter plan."""
    stmt = select(ChapterPlan).where(
        ChapterPlan.novel_id == novel_id,
        ChapterPlan.chapter_number == num,
    )
    result = await db.execute(stmt)
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter plan not found",
        )

    plan.status = "approved"
    await db.flush()

    logger.info("chapter_plan_approved", novel_id=novel_id, chapter_number=num)
    return {"message": "Chapter plan approved", "chapter_number": num}


@router.get("/{novel_id}/threads", response_model=list[PlotThreadRead])
async def list_threads(
    novel_id: int,
    user: dict = Depends(require_novel_owner),
    db: AsyncSession = Depends(get_db),
) -> list[PlotThreadRead]:
    """List active plot threads for a novel."""
    threads = await get_active_plot_threads(db, novel_id)
    return [PlotThreadRead.model_validate(t) for t in threads]
