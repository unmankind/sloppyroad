"""Tests for Pydantic v2 API schemas.

Validates serialization from ORM objects, required fields,
type checking, and field constraints.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from aiwebnovel.db.schemas import (
    ArcPlanCreate,
    ArcPlanRead,
    ChapterList,
    ChapterRead,
    ChekhovGunRead,
    GenerationJobRead,
    NotificationRead,
    NovelCreate,
    NovelList,
    NovelRatingCreate,
    NovelRead,
    NovelStatsRead,
    PaginatedResponse,
    ReaderBookmarkRead,
    UserRead,
)

# ---------------------------------------------------------------------------
# Utility: simulate ORM objects with attribute access
# ---------------------------------------------------------------------------


class FakeORM:
    """Simple namespace that supports attribute access like an ORM model."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


NOW = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# User schemas
# ---------------------------------------------------------------------------


class TestUserSchemas:
    def test_user_read_from_orm(self):
        orm = FakeORM(
            id=1, email="test@example.com", username="tester",
            display_name="Test User", role="author", is_active=True,
            created_at=NOW,
        )
        schema = UserRead.model_validate(orm)
        assert schema.id == 1
        assert schema.email == "test@example.com"
        assert schema.role == "author"

    def test_user_read_nullable_email(self):
        orm = FakeORM(
            id=2, email=None, username=None, display_name=None,
            role="reader", is_active=True, created_at=NOW,
        )
        schema = UserRead.model_validate(orm)
        assert schema.email is None


# ---------------------------------------------------------------------------
# Novel schemas
# ---------------------------------------------------------------------------


class TestNovelSchemas:
    def test_novel_create_valid(self):
        nc = NovelCreate(title="My Novel")
        assert nc.title == "My Novel"
        assert nc.genre == "progression_fantasy"

    def test_novel_create_empty_title(self):
        with pytest.raises(ValidationError):
            NovelCreate(title="")

    def test_novel_read_from_orm(self):
        orm = FakeORM(
            id=1, author_id=1, title="Novel", genre="fantasy",
            status="writing", autonomous_enabled=False, is_public=True,
            share_token=None, completion_summary=None,
            created_at=NOW, updated_at=NOW,
        )
        schema = NovelRead.model_validate(orm)
        assert schema.status == "writing"

    def test_novel_list_from_orm(self):
        orm = FakeORM(
            id=1, title="Novel", genre="fantasy",
            status="writing", is_public=False, created_at=NOW,
        )
        schema = NovelList.model_validate(orm)
        assert schema.is_public is False


# ---------------------------------------------------------------------------
# Chapter schemas
# ---------------------------------------------------------------------------


class TestChapterSchemas:
    def test_chapter_read_from_orm(self):
        orm = FakeORM(
            id=1, novel_id=1, chapter_number=1, title="Dawn",
            chapter_text="The story begins...", word_count=500,
            pov_character_id=None, model_used="test-model",
            status="published", is_bridge=False,
            created_at=NOW, updated_at=NOW,
        )
        schema = ChapterRead.model_validate(orm)
        assert schema.chapter_number == 1
        assert schema.chapter_text == "The story begins..."

    def test_chapter_list_from_orm(self):
        orm = FakeORM(
            id=1, novel_id=1, chapter_number=1, title=None,
            word_count=1000, status="draft", is_bridge=True,
            created_at=NOW,
        )
        schema = ChapterList.model_validate(orm)
        assert schema.is_bridge is True


# ---------------------------------------------------------------------------
# ArcPlan schemas
# ---------------------------------------------------------------------------


class TestArcPlanSchemas:
    def test_arc_plan_create_valid(self):
        ap = ArcPlanCreate(
            title="Arc 1",
            description="First arc of the novel",
        )
        assert ap.is_final_arc is False

    def test_arc_plan_create_empty_title(self):
        with pytest.raises(ValidationError):
            ArcPlanCreate(title="", description="desc")

    def test_arc_plan_read_from_orm(self):
        orm = FakeORM(
            id=1, novel_id=1, arc_number=1, title="Arc 1",
            description="desc", planned_chapters=5,
            target_chapter_start=1, target_chapter_end=5,
            status="in_progress", author_notes=None,
            themes=None, key_events=[], character_arcs=[],
            is_final_arc=False, resolution_targets=None,
            created_at=NOW, updated_at=NOW,
        )
        schema = ArcPlanRead.model_validate(orm)
        assert schema.status == "in_progress"


# ---------------------------------------------------------------------------
# ChekhovGun schemas
# ---------------------------------------------------------------------------


class TestChekhovGunSchemas:
    def test_chekhov_gun_read_from_orm(self):
        orm = FakeORM(
            id=1, novel_id=1, description="Mysterious sword",
            introduced_at_chapter=3, gun_type="object",
            status="loaded", pressure_score=0.75,
            last_touched_chapter=5, resolution_chapter=None,
            resolution_description=None, chapters_since_touch=2,
            created_at=NOW,
        )
        schema = ChekhovGunRead.model_validate(orm)
        assert schema.pressure_score == 0.75
        assert schema.gun_type == "object"


# ---------------------------------------------------------------------------
# Notification schemas
# ---------------------------------------------------------------------------


class TestNotificationSchemas:
    def test_notification_read_from_orm(self):
        orm = FakeORM(
            id=1, user_id=1, novel_id=1,
            notification_type="new_chapter",
            title="New chapter!", message="Ch 5 published",
            action_url="/novels/1/chapters/5",
            is_read=False, delivery_channel="in_app",
            created_at=NOW,
        )
        schema = NotificationRead.model_validate(orm)
        assert schema.is_read is False
        assert schema.notification_type == "new_chapter"


# ---------------------------------------------------------------------------
# Discovery schemas
# ---------------------------------------------------------------------------


class TestDiscoverySchemas:
    def test_novel_stats_read_from_orm(self):
        orm = FakeORM(
            id=1, novel_id=1, total_chapters=10, total_words=50000,
            total_readers=42, avg_rating=4.5, rating_count=20,
            last_chapter_at=NOW, updated_at=NOW,
        )
        schema = NovelStatsRead.model_validate(orm)
        assert schema.avg_rating == 4.5

    def test_novel_rating_create_valid_positive(self):
        rc = NovelRatingCreate(novel_id=1, rating=5, review_text="Great!")
        assert rc.rating == 5

    def test_novel_rating_create_valid_negative(self):
        rc = NovelRatingCreate(novel_id=1, rating=-3)
        assert rc.rating == -3

    def test_novel_rating_zero_rejected(self):
        """Zero is not a valid rating (neutral gap between negative and positive)."""
        with pytest.raises(ValidationError):
            NovelRatingCreate(novel_id=1, rating=0)

    def test_novel_rating_out_of_range(self):
        with pytest.raises(ValidationError):
            NovelRatingCreate(novel_id=1, rating=-6)
        with pytest.raises(ValidationError):
            NovelRatingCreate(novel_id=1, rating=6)


# ---------------------------------------------------------------------------
# GenerationJob schemas
# ---------------------------------------------------------------------------


class TestGenerationJobSchemas:
    def test_generation_job_read_from_orm(self):
        orm = FakeORM(
            id=1, novel_id=1, job_type="chapter",
            arq_job_id="abc123", chapter_number=5,
            status="running", attempt_number=1,
            started_at=NOW, completed_at=None,
            heartbeat_at=NOW, error_message=None,
            created_at=NOW,
        )
        schema = GenerationJobRead.model_validate(orm)
        assert schema.status == "running"
        assert schema.arq_job_id == "abc123"


# ---------------------------------------------------------------------------
# Bookmark schemas
# ---------------------------------------------------------------------------


class TestBookmarkSchemas:
    def test_reader_bookmark_from_orm(self):
        orm = FakeORM(
            id=1, user_id=1, novel_id=1,
            last_chapter_read=7, notify_on_update=True,
            created_at=NOW, updated_at=NOW,
        )
        schema = ReaderBookmarkRead.model_validate(orm)
        assert schema.notify_on_update is True


# ---------------------------------------------------------------------------
# Pagination wrapper
# ---------------------------------------------------------------------------


class TestPaginatedResponse:
    def test_total_pages_calculation(self):
        p = PaginatedResponse(items=[], page=1, page_size=10, total=25)
        assert p.total_pages == 3

    def test_total_pages_exact(self):
        p = PaginatedResponse(items=[], page=1, page_size=10, total=20)
        assert p.total_pages == 2

    def test_total_pages_zero(self):
        p = PaginatedResponse(items=[], page=1, page_size=10, total=0)
        assert p.total_pages == 0
