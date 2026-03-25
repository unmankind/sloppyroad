"""Reader influence routes: Oracle, Butterfly choices, factions, signals."""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import get_current_user
from aiwebnovel.db.models import (
    ButterflyChoice,
    FactionAlignment,
    Novel,
    OracleQuestion,
    ReaderSignal,
)
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────


class OracleSubmitRequest(BaseModel):
    question_text: str = Field(..., min_length=5, max_length=500)


class OracleResponse(BaseModel):
    id: int
    question_text: str
    status: str
    votes: int


class OracleStatusResponse(BaseModel):
    active_questions: list[OracleResponse]
    total_questions: int


class ButterflyVoteRequest(BaseModel):
    choice: str = Field(..., pattern="^[AB]$")


class FactionPledgeRequest(BaseModel):
    pass  # Just the path parameter faction_id is needed


class SignalRequest(BaseModel):
    signal_type: str = Field(..., max_length=50)
    intensity: int = Field(3, ge=1, le=5)
    target_entity_id: Optional[int] = None
    target_entity_type: Optional[str] = Field(None, max_length=50)


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post(
    "/{novel_id}/oracle",
    response_model=OracleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_oracle_question(
    novel_id: int,
    body: OracleSubmitRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OracleResponse:
    """Submit an Oracle question."""
    # Verify novel exists
    stmt = select(Novel).where(Novel.id == novel_id)
    result = await db.execute(stmt)
    novel = result.scalar_one_or_none()
    if novel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

    question = OracleQuestion(
        novel_id=novel_id,
        reader_id=user["user_id"],
        question_text=body.question_text,
        status="queued",
    )
    db.add(question)
    await db.flush()

    logger.info("oracle_question_submitted", novel_id=novel_id, question_id=question.id)

    return OracleResponse(
        id=question.id,
        question_text=question.question_text,
        status=question.status,
        votes=question.votes,
    )


@router.get("/{novel_id}/oracle/status", response_model=OracleStatusResponse)
async def oracle_status(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
) -> OracleStatusResponse:
    """Get current Oracle state for a novel."""
    from sqlalchemy import func

    stmt = (
        select(OracleQuestion)
        .where(
            OracleQuestion.novel_id == novel_id,
            OracleQuestion.status.in_(["queued", "validated"]),
        )
        .order_by(OracleQuestion.votes.desc())
        .limit(10)
    )
    result = await db.execute(stmt)
    questions = result.scalars().all()

    count_stmt = (
        select(func.count(OracleQuestion.id))
        .where(OracleQuestion.novel_id == novel_id)
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    return OracleStatusResponse(
        active_questions=[
            OracleResponse(
                id=q.id,
                question_text=q.question_text,
                status=q.status,
                votes=q.votes,
            )
            for q in questions
        ],
        total_questions=total,
    )


@router.post("/{novel_id}/butterfly/{choice_id}/vote")
async def butterfly_vote(
    novel_id: int,
    choice_id: int,
    body: ButterflyVoteRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cast a Butterfly choice vote."""
    stmt = select(ButterflyChoice).where(
        ButterflyChoice.id == choice_id,
        ButterflyChoice.novel_id == novel_id,
    )
    result = await db.execute(stmt)
    choice = result.scalar_one_or_none()

    if choice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Butterfly choice not found",
        )

    if choice.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voting is closed for this choice",
        )

    # Prevent duplicate votes — track voters in a JSON list on the choice
    user_id = user.get("user_id")
    voters = choice.personality_modifier or {}
    voter_list = voters.get("_voters", [])
    if user_id in voter_list:
        return {
            "message": "Already voted",
            "choice_id": choice_id,
            "vote": body.choice,
            "counts": {"A": choice.vote_count_a, "B": choice.vote_count_b},
        }

    if body.choice == "A":
        choice.vote_count_a += 1
    else:
        choice.vote_count_b += 1

    voter_list.append(user_id)
    voters["_voters"] = voter_list
    choice.personality_modifier = voters
    await db.flush()

    logger.info(
        "butterfly_vote_cast",
        choice_id=choice_id,
        vote=body.choice,
        user_id=user_id,
    )

    return {
        "message": "Vote cast",
        "choice_id": choice_id,
        "vote": body.choice,
        "counts": {"A": choice.vote_count_a, "B": choice.vote_count_b},
    }


@router.post("/{novel_id}/factions/{faction_id}/pledge")
async def faction_pledge(
    novel_id: int,
    faction_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pledge alignment to a faction."""
    # Verify faction belongs to the specified novel
    from aiwebnovel.db.models import Faction

    faction = (
        await db.execute(
            select(Faction).where(
                Faction.id == faction_id,
                Faction.novel_id == novel_id,
            )
        )
    ).scalar_one_or_none()
    if faction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Faction not found in this novel",
        )

    # Check existing alignment
    stmt = select(FactionAlignment).where(
        FactionAlignment.reader_id == user["user_id"],
        FactionAlignment.novel_id == novel_id,
        FactionAlignment.faction_id == faction_id,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # Increase alignment score
        existing.alignment_score = min(1.0, existing.alignment_score + 0.1)
        await db.flush()
        score = existing.alignment_score
    else:
        alignment = FactionAlignment(
            reader_id=user["user_id"],
            novel_id=novel_id,
            faction_id=faction_id,
            alignment_score=0.5,
        )
        db.add(alignment)
        await db.flush()
        score = 0.5

    logger.info(
        "faction_pledge",
        novel_id=novel_id,
        faction_id=faction_id,
        user_id=user["user_id"],
    )

    return {
        "message": "Faction alignment updated",
        "faction_id": faction_id,
        "alignment_score": score,
    }


@router.post("/{novel_id}/signal", status_code=status.HTTP_201_CREATED)
async def submit_signal(
    novel_id: int,
    body: SignalRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Submit an engagement signal (excitement, curiosity, concern, etc.)."""
    signal = ReaderSignal(
        novel_id=novel_id,
        reader_id=user["user_id"],
        signal_type=body.signal_type,
        intensity=body.intensity,
        target_entity_id=body.target_entity_id,
        target_entity_type=body.target_entity_type,
    )
    db.add(signal)
    await db.flush()

    logger.info(
        "reader_signal",
        novel_id=novel_id,
        signal_type=body.signal_type,
        intensity=body.intensity,
    )

    return {"message": "Signal recorded", "signal_id": signal.id}
