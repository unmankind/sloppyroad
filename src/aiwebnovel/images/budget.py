"""Image budget enforcement.

Checks both author-level and novel-level image budgets before generation.
Returns a result instead of raising, so callers can skip gracefully and
create a notification for the author.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import AuthorProfile, Notification, Novel

logger = structlog.get_logger(__name__)


@dataclass
class ImageBudgetResult:
    """Result of an image budget check."""

    allowed: bool
    reason: str = ""
    author_spent_cents: int = 0
    author_budget_cents: int = 0
    novel_spent_cents: int = 0
    novel_budget_cents: int = 0


async def check_image_budget(
    session: AsyncSession,
    novel_id: int,
) -> ImageBudgetResult:
    """Check both author-level and novel-level image budgets.

    Returns an ``ImageBudgetResult`` instead of raising so the caller
    can decide how to handle an exhausted budget (e.g. skip + notify).
    """
    # Fetch author profile via novel
    stmt = (
        select(AuthorProfile)
        .join(Novel, Novel.author_id == AuthorProfile.user_id)
        .where(Novel.id == novel_id)
    )
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        return ImageBudgetResult(
            allowed=False,
            reason=f"No author profile found for novel_id={novel_id}",
        )

    # Author-level check
    if profile.image_spent_cents >= profile.image_budget_cents:
        logger.warning(
            "image_budget_exceeded_author",
            novel_id=novel_id,
            spent=profile.image_spent_cents,
            budget=profile.image_budget_cents,
        )
        return ImageBudgetResult(
            allowed=False,
            reason=(
                f"Author image budget exhausted: "
                f"{profile.image_spent_cents}/{profile.image_budget_cents} cents"
            ),
            author_spent_cents=profile.image_spent_cents,
            author_budget_cents=profile.image_budget_cents,
        )

    # Novel-level check
    novel_stmt = select(Novel).where(Novel.id == novel_id)
    novel_result = await session.execute(novel_stmt)
    novel = novel_result.scalar_one_or_none()

    if novel is None:
        return ImageBudgetResult(
            allowed=False,
            reason=f"Novel not found: {novel_id}",
        )

    # Only enforce novel budget if one has been set (budget > 0)
    if novel.image_budget_cents > 0 and novel.image_spent_cents >= novel.image_budget_cents:
        logger.warning(
            "image_budget_exceeded_novel",
            novel_id=novel_id,
            spent=novel.image_spent_cents,
            budget=novel.image_budget_cents,
        )
        return ImageBudgetResult(
            allowed=False,
            reason=(
                f"Novel image budget exhausted: "
                f"{novel.image_spent_cents}/{novel.image_budget_cents} cents"
            ),
            author_spent_cents=profile.image_spent_cents,
            author_budget_cents=profile.image_budget_cents,
            novel_spent_cents=novel.image_spent_cents,
            novel_budget_cents=novel.image_budget_cents,
        )

    return ImageBudgetResult(
        allowed=True,
        author_spent_cents=profile.image_spent_cents,
        author_budget_cents=profile.image_budget_cents,
        novel_spent_cents=novel.image_spent_cents,
        novel_budget_cents=novel.image_budget_cents,
    )


async def notify_image_budget_exceeded(
    session: AsyncSession,
    novel_id: int,
    user_id: int,
    reason: str,
) -> None:
    """Create a budget_warning notification when image budget is exhausted."""
    notification = Notification(
        user_id=user_id,
        novel_id=novel_id,
        notification_type="budget_warning",
        title="Image budget exhausted",
        message=reason,
        action_url="/dashboard/settings",
    )
    session.add(notification)
    await session.flush()
    logger.info(
        "image_budget_notification_created",
        novel_id=novel_id,
        user_id=user_id,
    )
