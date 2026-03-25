"""Tests for budget enforcement.

Uses in-memory SQLite with real ORM models.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import AuthorProfile, LLMUsageLog, Novel, User
from aiwebnovel.llm.budget import BudgetChecker, BudgetExceededError


@pytest.fixture()
def budget_settings() -> Settings:
    return Settings(
        jwt_secret_key="test-secret",
        autonomous_daily_budget_cents=100,
    )


@pytest.fixture()
def checker(budget_settings: Settings) -> BudgetChecker:
    return BudgetChecker(budget_settings)


async def _create_test_data(
    session: AsyncSession,
    api_budget: int = 500,
    api_spent: int = 0,
    image_budget: int = 200,
    image_spent: int = 0,
    autonomous_daily_budget: int = 100,
) -> tuple[User, AuthorProfile, Novel]:
    """Create a user + author profile + novel for budget tests."""
    user = User(
        email="budget_test@example.com",
        username="budgettest",
        role="author",
        is_anonymous=False,
        auth_provider="local",
    )
    session.add(user)
    await session.flush()

    profile = AuthorProfile(
        user_id=user.id,
        api_budget_cents=api_budget,
        api_spent_cents=api_spent,
        image_budget_cents=image_budget,
        image_spent_cents=image_spent,
    )
    session.add(profile)
    await session.flush()

    novel = Novel(
        author_id=user.id,
        title="Budget Test Novel",
        genre="progression_fantasy",
        autonomous_daily_budget_cents=autonomous_daily_budget,
    )
    session.add(novel)
    await session.flush()

    return user, profile, novel


# ═══════════════════════════════════════════════════════════════════════════
# LLM BUDGET
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckLLMBudget:
    @pytest.mark.asyncio
    async def test_passes_when_under_budget(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, api_budget=500, api_spent=100
        )
        # Should not raise
        await checker.check_llm_budget(db_session, novel.id)

    @pytest.mark.asyncio
    async def test_raises_when_over_budget(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, api_budget=500, api_spent=500
        )
        with pytest.raises(BudgetExceededError, match="LLM budget exceeded"):
            await checker.check_llm_budget(db_session, novel.id)

    @pytest.mark.asyncio
    async def test_raises_when_exactly_at_budget(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, api_budget=500, api_spent=500
        )
        with pytest.raises(BudgetExceededError):
            await checker.check_llm_budget(db_session, novel.id)

    @pytest.mark.asyncio
    async def test_error_has_amounts(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, api_budget=500, api_spent=600
        )
        with pytest.raises(BudgetExceededError) as exc_info:
            await checker.check_llm_budget(db_session, novel.id)
        assert exc_info.value.spent_cents == 600
        assert exc_info.value.budget_cents == 500


# ═══════════════════════════════════════════════════════════════════════════
# IMAGE BUDGET
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckImageBudget:
    @pytest.mark.asyncio
    async def test_passes_when_under_budget(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, image_budget=200, image_spent=50
        )
        await checker.check_image_budget(db_session, novel.id)

    @pytest.mark.asyncio
    async def test_raises_when_over_budget(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, image_budget=200, image_spent=200
        )
        with pytest.raises(BudgetExceededError, match="Image budget exceeded"):
            await checker.check_image_budget(db_session, novel.id)


# ═══════════════════════════════════════════════════════════════════════════
# AUTONOMOUS DAILY BUDGET
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckAutonomousDailyBudget:
    @pytest.mark.asyncio
    async def test_passes_when_no_spending_today(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, autonomous_daily_budget=100
        )
        await checker.check_autonomous_daily_budget(db_session, novel.id)

    @pytest.mark.asyncio
    async def test_raises_when_over_daily_cap(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, autonomous_daily_budget=100
        )
        # Add usage logs that sum over the daily cap
        for _ in range(5):
            log = LLMUsageLog(
                novel_id=novel.id,
                user_id=user.id,
                model="anthropic/claude-3-haiku-20240307",
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500,
                cost_cents=25.0,
                purpose="autonomous_generation",
                duration_ms=500,
            )
            db_session.add(log)
        await db_session.flush()

        with pytest.raises(BudgetExceededError, match="daily budget exceeded"):
            await checker.check_autonomous_daily_budget(db_session, novel.id)


# ═══════════════════════════════════════════════════════════════════════════
# UPDATE SPENT
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateSpent:
    @pytest.mark.asyncio
    async def test_updates_llm_spent(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, api_spent=100
        )
        await checker.update_spent(db_session, novel.id, 50.0)

        # Re-fetch the profile
        result = await db_session.execute(
            select(AuthorProfile).where(AuthorProfile.user_id == user.id)
        )
        updated = result.scalar_one()
        assert updated.api_spent_cents == 150

    @pytest.mark.asyncio
    async def test_updates_image_spent(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(
            db_session, image_spent=10
        )
        await checker.update_spent(db_session, novel.id, 5.0, cost_type="image")

        result = await db_session.execute(
            select(AuthorProfile).where(AuthorProfile.user_id == user.id)
        )
        updated = result.scalar_one()
        assert updated.image_spent_cents == 15


# ═══════════════════════════════════════════════════════════════════════════
# LOG USAGE
# ═══════════════════════════════════════════════════════════════════════════


class TestLogUsage:
    @pytest.mark.asyncio
    async def test_creates_log_entry(
        self, db_session: AsyncSession, checker: BudgetChecker
    ) -> None:
        user, profile, novel = await _create_test_data(db_session)

        await checker.log_usage(
            session=db_session,
            novel_id=novel.id,
            user_id=user.id,
            model="anthropic/claude-sonnet-4-6",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_cents=2.25,
            purpose="chapter_generation",
            duration_ms=3000,
        )

        result = await db_session.execute(
            select(LLMUsageLog).where(LLMUsageLog.novel_id == novel.id)
        )
        log = result.scalar_one()
        assert log.model == "anthropic/claude-sonnet-4-6"
        assert log.prompt_tokens == 1000
        assert log.completion_tokens == 500
        assert log.total_tokens == 1500
        assert log.cost_cents == 2.25
        assert log.purpose == "chapter_generation"
        assert log.duration_ms == 3000
