"""Budget enforcement for LLM and image generation costs.

All budget checks and usage logging flow through BudgetChecker.
The provider calls these before and after every LLM invocation.
"""

from __future__ import annotations

from datetime import date, datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import AuthorProfile, LLMUsageLog, Novel

logger = structlog.get_logger(__name__)


class BudgetExceededError(Exception):
    """Raised when an author's LLM or image budget is exhausted."""

    def __init__(self, message: str, spent_cents: float = 0, budget_cents: float = 0) -> None:
        super().__init__(message)
        self.spent_cents = spent_cents
        self.budget_cents = budget_cents


class BudgetChecker:
    """Budget enforcement and usage logging."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _get_author_profile(
        self, session: AsyncSession, novel_id: int,
        *, for_update: bool = False,
    ) -> AuthorProfile:
        """Resolve the author profile for a given novel.

        When *for_update* is True, locks the row to prevent concurrent
        budget check + update races (TOCTOU).
        """
        stmt = (
            select(AuthorProfile)
            .join(Novel, Novel.author_id == AuthorProfile.user_id)
            .where(Novel.id == novel_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()
        if profile is None:
            logger.warning("budget_check_no_profile", novel_id=novel_id)
            raise BudgetExceededError(
                "Author profile not found — please complete registration"
            )
        return profile

    async def check_llm_budget(self, session: AsyncSession, novel_id: int) -> None:
        """Raise BudgetExceededError if author's LLM budget is exhausted.

        Uses optimistic read (no FOR UPDATE) to avoid lock contention.
        Also creates a warning notification at 80% spent (once per 24h).
        """
        profile = await self._get_author_profile(session, novel_id)

        # Soft warning at 80%
        if profile.api_budget_cents > 0:
            spent_pct = profile.api_spent_cents / profile.api_budget_cents * 100
            if 80 <= spent_pct < 100:
                await self._maybe_warn_llm_budget(
                    session, profile.user_id, novel_id,
                    profile.api_spent_cents, profile.api_budget_cents,
                )

        if profile.api_spent_cents >= profile.api_budget_cents:
            logger.warning(
                "llm_budget_exceeded",
                novel_id=novel_id,
                spent=profile.api_spent_cents,
                budget=profile.api_budget_cents,
            )
            raise BudgetExceededError(
                f"LLM budget exceeded: spent {profile.api_spent_cents} cents "
                f"of {profile.api_budget_cents} cents",
                spent_cents=profile.api_spent_cents,
                budget_cents=profile.api_budget_cents,
            )

    async def check_image_budget(self, session: AsyncSession, novel_id: int) -> None:
        """Raise BudgetExceededError if author's image budget is exhausted.

        Uses optimistic read (no FOR UPDATE) to avoid lock contention.
        """
        profile = await self._get_author_profile(session, novel_id)
        if profile.image_spent_cents >= profile.image_budget_cents:
            logger.warning(
                "image_budget_exceeded",
                novel_id=novel_id,
                spent=profile.image_spent_cents,
                budget=profile.image_budget_cents,
            )
            raise BudgetExceededError(
                f"Image budget exceeded: spent {profile.image_spent_cents} cents "
                f"of {profile.image_budget_cents} cents",
                spent_cents=profile.image_spent_cents,
                budget_cents=profile.image_budget_cents,
            )

    async def _maybe_warn_llm_budget(
        self,
        session: AsyncSession,
        user_id: int,
        novel_id: int,
        spent: int,
        budget: int,
    ) -> None:
        """Create a budget warning notification, max once per 24h per user."""
        from datetime import timedelta

        from aiwebnovel.db.models import Notification
        from aiwebnovel.worker.tasks_common import _utcnow

        cutoff = _utcnow() - timedelta(hours=24)
        existing = (
            await session.execute(
                select(Notification.id).where(
                    Notification.user_id == user_id,
                    Notification.notification_type == "budget_warning",
                    Notification.created_at >= cutoff,
                ).limit(1)
            )
        ).scalar_one_or_none()

        if existing is not None:
            return  # Already warned recently

        pct = int(spent / max(budget, 1) * 100)
        session.add(Notification(
            user_id=user_id,
            novel_id=novel_id,
            notification_type="budget_warning",
            title=f"LLM budget at {pct}%",
            message=(
                f"You've used {spent} of {budget} cents. "
                f"Generation will stop when the budget is exhausted."
            ),
            action_url="/dashboard/settings",
        ))
        await session.flush()
        logger.info(
            "llm_budget_warning_sent",
            user_id=user_id,
            spent=spent,
            budget=budget,
        )

    async def check_autonomous_daily_budget(
        self, session: AsyncSession, novel_id: int
    ) -> None:
        """Check if today's autonomous generation spending exceeds daily cap.

        Reads the daily budget from NovelSettings (canonical source) with
        fallback to Novel.autonomous_daily_budget_cents for legacy data.
        """
        from aiwebnovel.db.models import NovelSettings

        # Prefer NovelSettings (canonical), fall back to Novel
        ns_stmt = select(NovelSettings).where(NovelSettings.novel_id == novel_id)
        ns = (await session.execute(ns_stmt)).scalar_one_or_none()

        if ns is not None:
            daily_cap = ns.autonomous_daily_budget_cents
        else:
            stmt = select(Novel).where(Novel.id == novel_id)
            novel = (await session.execute(stmt)).scalar_one_or_none()
            if novel is None:
                msg = f"Novel not found: {novel_id}"
                raise ValueError(msg)
            daily_cap = novel.autonomous_daily_budget_cents

        # Sum today's LLM costs for this novel
        today_start = datetime.combine(
            date.today(), datetime.min.time(),
        )
        stmt_cost = (
            select(func.coalesce(func.sum(LLMUsageLog.cost_cents), 0.0))
            .where(LLMUsageLog.novel_id == novel_id)
            .where(LLMUsageLog.created_at >= today_start)
        )
        result_cost = await session.execute(stmt_cost)
        today_spent = result_cost.scalar_one()

        if today_spent >= daily_cap:
            logger.warning(
                "autonomous_daily_budget_exceeded",
                novel_id=novel_id,
                spent=today_spent,
                cap=daily_cap,
            )
            raise BudgetExceededError(
                f"Autonomous daily budget exceeded: spent {today_spent:.2f} cents "
                f"of {daily_cap} cents today",
                spent_cents=today_spent,
                budget_cents=daily_cap,
            )

    async def update_spent(
        self,
        session: AsyncSession,
        novel_id: int,
        cost_cents: float,
        cost_type: str = "llm",
    ) -> None:
        """Update the author's spent amount using optimistic atomic increment.

        Uses UPDATE ... SET col = col + N instead of read-modify-write to avoid
        lock contention. For image costs, also updates novel-level spending.
        """
        profile = await self._get_author_profile(session, novel_id)
        cost_int = int(cost_cents)

        if cost_type == "image":
            await session.execute(
                update(AuthorProfile)
                .where(AuthorProfile.id == profile.id)
                .values(image_spent_cents=AuthorProfile.image_spent_cents + cost_int)
            )
            # Also update novel-level image spending
            await session.execute(
                update(Novel)
                .where(Novel.id == novel_id)
                .values(image_spent_cents=Novel.image_spent_cents + cost_int)
            )
        else:
            await session.execute(
                update(AuthorProfile)
                .where(AuthorProfile.id == profile.id)
                .values(api_spent_cents=AuthorProfile.api_spent_cents + cost_int)
            )

        await session.flush()
        logger.debug(
            "budget_updated",
            novel_id=novel_id,
            cost_type=cost_type,
            cost_cents=cost_cents,
        )

    async def log_usage(
        self,
        session: AsyncSession,
        novel_id: int | None,
        user_id: int,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_cents: float,
        purpose: str,
        duration_ms: int,
    ) -> None:
        """Write an entry to the llm_usage_log table."""
        entry = LLMUsageLog(
            novel_id=novel_id,
            user_id=user_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_cents=cost_cents,
            purpose=purpose,
            duration_ms=duration_ms,
        )
        session.add(entry)
        await session.flush()
        logger.debug(
            "llm_usage_logged",
            novel_id=novel_id,
            model=model,
            tokens=prompt_tokens + completion_tokens,
            cost_cents=cost_cents,
            purpose=purpose,
        )
