"""Tests for image budget enforcement (images/budget.py).

Covers dual-level (author + novel) budget checking and notification creation.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import AuthorProfile, Notification, Novel, User
from aiwebnovel.images.budget import (
    check_image_budget,
    notify_image_budget_exceeded,
)


async def _create_test_data(
    session: AsyncSession,
    image_budget: int = 200,
    image_spent: int = 0,
    novel_image_budget: int = 0,
    novel_image_spent: int = 0,
) -> tuple[User, AuthorProfile, Novel]:
    """Create a user + author profile + novel for image budget tests."""
    user = User(
        email="imgbudget@example.com",
        username="imgbudgettest",
        role="author",
        is_anonymous=False,
        auth_provider="local",
    )
    session.add(user)
    await session.flush()

    profile = AuthorProfile(
        user_id=user.id,
        api_budget_cents=500,
        api_spent_cents=0,
        image_budget_cents=image_budget,
        image_spent_cents=image_spent,
    )
    session.add(profile)
    await session.flush()

    novel = Novel(
        author_id=user.id,
        title="Image Budget Test Novel",
        genre="progression_fantasy",
        image_budget_cents=novel_image_budget,
        image_spent_cents=novel_image_spent,
    )
    session.add(novel)
    await session.flush()

    return user, profile, novel


# ═══════════════════════════════════════════════════════════════════════════
# check_image_budget
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckImageBudget:
    @pytest.mark.asyncio
    async def test_allowed_when_under_author_budget(
        self, db_session: AsyncSession
    ) -> None:
        _, _, novel = await _create_test_data(
            db_session, image_budget=200, image_spent=50
        )
        result = await check_image_budget(db_session, novel.id)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_blocked_when_author_budget_exhausted(
        self, db_session: AsyncSession
    ) -> None:
        _, _, novel = await _create_test_data(
            db_session, image_budget=200, image_spent=200
        )
        result = await check_image_budget(db_session, novel.id)
        assert result.allowed is False
        assert "Author image budget exhausted" in result.reason

    @pytest.mark.asyncio
    async def test_blocked_when_author_budget_exceeded(
        self, db_session: AsyncSession
    ) -> None:
        _, _, novel = await _create_test_data(
            db_session, image_budget=200, image_spent=250
        )
        result = await check_image_budget(db_session, novel.id)
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_blocked_when_novel_budget_exhausted(
        self, db_session: AsyncSession
    ) -> None:
        _, _, novel = await _create_test_data(
            db_session,
            image_budget=500,
            image_spent=100,
            novel_image_budget=50,
            novel_image_spent=50,
        )
        result = await check_image_budget(db_session, novel.id)
        assert result.allowed is False
        assert "Novel image budget exhausted" in result.reason

    @pytest.mark.asyncio
    async def test_novel_budget_zero_means_unlimited(
        self, db_session: AsyncSession
    ) -> None:
        """When novel image_budget_cents is 0, novel-level check is skipped."""
        _, _, novel = await _create_test_data(
            db_session,
            image_budget=500,
            image_spent=100,
            novel_image_budget=0,
            novel_image_spent=999,
        )
        result = await check_image_budget(db_session, novel.id)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_result_contains_amounts(
        self, db_session: AsyncSession
    ) -> None:
        _, _, novel = await _create_test_data(
            db_session,
            image_budget=500,
            image_spent=100,
            novel_image_budget=300,
            novel_image_spent=50,
        )
        result = await check_image_budget(db_session, novel.id)
        assert result.allowed is True
        assert result.author_spent_cents == 100
        assert result.author_budget_cents == 500
        assert result.novel_spent_cents == 50
        assert result.novel_budget_cents == 300

    @pytest.mark.asyncio
    async def test_no_profile_returns_blocked(
        self, db_session: AsyncSession
    ) -> None:
        result = await check_image_budget(db_session, 99999)
        assert result.allowed is False
        assert "No author profile" in result.reason


# ═══════════════════════════════════════════════════════════════════════════
# notify_image_budget_exceeded
# ═══════════════════════════════════════════════════════════════════════════


class TestNotifyImageBudgetExceeded:
    @pytest.mark.asyncio
    async def test_creates_notification(
        self, db_session: AsyncSession
    ) -> None:
        user, _, novel = await _create_test_data(db_session)

        await notify_image_budget_exceeded(
            db_session, novel.id, user.id, "Budget exhausted"
        )

        stmt = select(Notification).where(
            Notification.user_id == user.id,
            Notification.notification_type == "budget_warning",
        )
        result = await db_session.execute(stmt)
        notif = result.scalar_one()
        assert notif.title == "Image budget exhausted"
        assert notif.message == "Budget exhausted"
        assert notif.novel_id == novel.id


# ═══════════════════════════════════════════════════════════════════════════
# Novel-level update_spent
# ═══════════════════════════════════════════════════════════════════════════


class TestNovelImageSpentTracking:
    @pytest.mark.asyncio
    async def test_update_spent_tracks_novel_level(
        self, db_session: AsyncSession
    ) -> None:
        from aiwebnovel.config import Settings
        from aiwebnovel.llm.budget import BudgetChecker

        user, profile, novel = await _create_test_data(
            db_session, novel_image_budget=100, novel_image_spent=10
        )
        checker = BudgetChecker(Settings(jwt_secret_key="test-secret"))

        await checker.update_spent(
            db_session, novel.id, 5.0, cost_type="image"
        )

        # Check author-level updated
        result = await db_session.execute(
            select(AuthorProfile).where(AuthorProfile.user_id == user.id)
        )
        updated_profile = result.scalar_one()
        assert updated_profile.image_spent_cents == 5

        # Check novel-level updated
        result = await db_session.execute(
            select(Novel).where(Novel.id == novel.id)
        )
        updated_novel = result.scalar_one()
        assert updated_novel.image_spent_cents == 15
