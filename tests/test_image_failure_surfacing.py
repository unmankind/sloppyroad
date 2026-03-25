"""Tests for image generation failure surfacing.

Verifies that image failures create notifications, store error messages
on ChapterImage, and can be retried via the gallery API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aiwebnovel.config import Settings
from aiwebnovel.worker.tasks import (
    generate_scene_image_task,
    process_art_queue_task,
)


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key",
        image_enabled=True,
        image_provider="hf-space",
        debug=True,
    )


@pytest.fixture()
def mock_ctx(test_settings: Settings) -> dict:
    """Worker task context with mocked dependencies."""
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value=1)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()

    session = AsyncMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    return {
        "settings": test_settings,
        "redis": redis,
        "session_factory": session_factory,
        "llm": MagicMock(),
        "pipeline": MagicMock(),
    }


# ---------------------------------------------------------------------------
# process_art_queue_task — notification on failure
# ---------------------------------------------------------------------------


class TestArtQueueFailureNotification:
    """Test that process_art_queue_task creates notifications on failure."""

    @pytest.mark.asyncio
    async def test_failure_creates_notification(self, mock_ctx: dict) -> None:
        """Failed art queue item should create an image_failed notification."""
        # Mock pending item
        mock_queue_item = MagicMock()
        mock_queue_item.id = 1
        mock_queue_item.novel_id = 10
        mock_queue_item.asset_type = "portrait"
        mock_queue_item.entity_id = 5
        mock_queue_item.entity_type = "character"
        mock_queue_item.status = "pending"
        mock_queue_item.priority = 5
        mock_queue_item.created_at = None
        mock_queue_item.source_asset_id = None
        mock_queue_item.feedback = None

        # Track sessions and their operations
        sessions = []
        added_objects = []

        def make_session():
            s = AsyncMock()
            # Track session.add calls
            s.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
            sessions.append(s)
            return s

        # We need different sessions for each context manager entry
        call_count = [0]

        async def session_aenter(*args, **kwargs):
            s = make_session()
            idx = call_count[0]
            call_count[0] += 1

            if idx == 0:
                # First session: fetch pending items
                mock_result = MagicMock()
                mock_result.scalars.return_value.all.return_value = [mock_queue_item]
                s.execute = AsyncMock(return_value=mock_result)
            elif idx == 1:
                # Second session: budget check — return allowed
                mock_profile = MagicMock()
                mock_profile.image_spent_cents = 0
                mock_profile.image_budget_cents = 500
                mock_budget_result = MagicMock()
                mock_budget_result.scalar_one_or_none.return_value = mock_profile
                # Novel budget check
                mock_novel_obj = MagicMock()
                mock_novel_obj.image_budget_cents = 0
                mock_novel_obj.image_spent_cents = 0
                mock_novel_result = MagicMock()
                mock_novel_result.scalar_one_or_none.return_value = mock_novel_obj
                s.execute = AsyncMock(
                    side_effect=[mock_budget_result, mock_novel_result]
                )
            elif idx == 2:
                # Third session: mark as generating
                mock_result = MagicMock()
                mock_result.scalar_one.return_value = mock_queue_item
                s.execute = AsyncMock(return_value=mock_result)
            elif idx == 3:
                # Fourth session: mark as failed + create notification
                mock_result_queue = MagicMock()
                mock_result_queue.scalar_one.return_value = mock_queue_item
                # Novel query result
                mock_novel_row = MagicMock()
                mock_novel_row.one_or_none.return_value = (42, "My Novel")

                s.execute = AsyncMock(
                    side_effect=[mock_result_queue, mock_novel_row]
                )

            return s

        mock_ctx["session_factory"].return_value.__aenter__ = session_aenter

        # Make the image generation fail
        with patch(
            "aiwebnovel.worker.tasks_images.generate_image_task", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.side_effect = RuntimeError("Provider timeout")
            result = await process_art_queue_task(mock_ctx)

        assert result["failed"] == 1
        assert result["processed"] == 0

        # Verify a notification was added
        assert len(added_objects) == 1
        notif = added_objects[0]
        assert notif.notification_type == "image_failed"
        assert notif.user_id == 42
        assert notif.novel_id == 10
        assert "portrait" in notif.message
        assert "My Novel" in notif.message
        assert "Provider timeout" in notif.message
        assert notif.action_url == "/novels/10/gallery"

    @pytest.mark.asyncio
    async def test_failure_stores_error_message(self, mock_ctx: dict) -> None:
        """Failed art queue item should store error_message truncated to 1000 chars."""
        mock_queue_item = MagicMock()
        mock_queue_item.id = 1
        mock_queue_item.novel_id = 10
        mock_queue_item.asset_type = "scene"
        mock_queue_item.entity_id = 5
        mock_queue_item.entity_type = "chapter_image"
        mock_queue_item.status = "pending"
        mock_queue_item.priority = 5
        mock_queue_item.created_at = None
        mock_queue_item.source_asset_id = None
        mock_queue_item.feedback = None

        call_count = [0]

        async def session_aenter(*args, **kwargs):
            s = AsyncMock()
            s.add = MagicMock()
            idx = call_count[0]
            call_count[0] += 1

            if idx == 0:
                mock_result = MagicMock()
                mock_result.scalars.return_value.all.return_value = [mock_queue_item]
                s.execute = AsyncMock(return_value=mock_result)
            elif idx == 1:
                # Budget check — return allowed
                mock_profile = MagicMock()
                mock_profile.image_spent_cents = 0
                mock_profile.image_budget_cents = 500
                mock_budget_result = MagicMock()
                mock_budget_result.scalar_one_or_none.return_value = mock_profile
                mock_novel_obj = MagicMock()
                mock_novel_obj.image_budget_cents = 0
                mock_novel_obj.image_spent_cents = 0
                mock_novel_result = MagicMock()
                mock_novel_result.scalar_one_or_none.return_value = mock_novel_obj
                s.execute = AsyncMock(
                    side_effect=[mock_budget_result, mock_novel_result]
                )
            elif idx == 2:
                mock_result = MagicMock()
                mock_result.scalar_one.return_value = mock_queue_item
                s.execute = AsyncMock(return_value=mock_result)
            elif idx == 3:
                mock_result_queue = MagicMock()
                mock_result_queue.scalar_one.return_value = mock_queue_item
                mock_novel_row = MagicMock()
                mock_novel_row.one_or_none.return_value = (42, "Novel")
                s.execute = AsyncMock(
                    side_effect=[mock_result_queue, mock_novel_row]
                )

            return s

        mock_ctx["session_factory"].return_value.__aenter__ = session_aenter

        long_error = "x" * 2000

        with patch(
            "aiwebnovel.worker.tasks_images.generate_scene_image_task", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.side_effect = RuntimeError(long_error)
            await process_art_queue_task(mock_ctx)

        # error_message should be truncated to 1000 chars
        assert mock_queue_item.error_message == long_error[:1000]
        assert mock_queue_item.status == "failed"


# ---------------------------------------------------------------------------
# generate_scene_image_task — error_message on ChapterImage
# ---------------------------------------------------------------------------


class TestSceneImageErrorMessage:
    """Test that generate_scene_image_task stores error on ChapterImage."""

    @pytest.mark.asyncio
    async def test_stores_error_on_chapter_image(self, mock_ctx: dict) -> None:
        """Provider failure should store error_message on ChapterImage."""
        from aiwebnovel.images.budget import ImageBudgetResult
        from aiwebnovel.images.provider import ImageRequest

        mock_chapter_image = MagicMock()
        mock_chapter_image.id = 1
        mock_chapter_image.chapter_id = 10
        mock_chapter_image.scene_description = "A warrior on a cliff"
        mock_chapter_image.paragraph_index = 2
        mock_chapter_image.status = "pending"
        mock_chapter_image.error_message = None

        call_count = [0]

        async def session_aenter(*args, **kwargs):
            s = AsyncMock()
            idx = call_count[0]
            call_count[0] += 1

            if idx == 0:
                # First session: budget check (patched, but context still opens)
                pass
            elif idx == 1:
                # Second session: load ChapterImage + Chapter
                mock_ci_result = MagicMock()
                mock_ci_result.scalar_one_or_none.return_value = mock_chapter_image
                mock_ch_result = MagicMock()
                mock_ch_result.scalar_one_or_none.return_value = 5
                s.execute = AsyncMock(
                    side_effect=[mock_ci_result, mock_ch_result]
                )
            elif idx == 2:
                # Third session: BYOK key resolution (returns no author)
                mock_author_result = MagicMock()
                mock_author_result.scalar_one_or_none.return_value = None
                s.execute = AsyncMock(return_value=mock_author_result)
            elif idx == 3:
                # Fourth session: mark as failed
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = mock_chapter_image
                s.execute = AsyncMock(return_value=mock_result)

            return s

        mock_ctx["session_factory"].return_value.__aenter__ = session_aenter

        mock_request = ImageRequest(
            prompt="A warrior on a cliff",
            negative_prompt="",
            width=512,
            height=512,
        )

        with (
            patch(
                "aiwebnovel.worker.tasks_images.check_image_budget",
                new_callable=AsyncMock,
                return_value=ImageBudgetResult(allowed=True),
            ),
            patch(
                "aiwebnovel.worker.tasks_images.ImagePromptComposer"
            ) as mock_composer_cls,
            patch(
                "aiwebnovel.worker.tasks_images.get_image_provider"
            ) as mock_provider_fn,
        ):
            mock_composer = MagicMock()
            mock_composer.compose_scene_prompt = AsyncMock(return_value=mock_request)
            mock_composer_cls.return_value = mock_composer

            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(
                side_effect=RuntimeError("GPU out of memory")
            )
            mock_provider_fn.return_value = mock_provider

            with pytest.raises(RuntimeError, match="GPU out of memory"):
                await generate_scene_image_task(
                    mock_ctx, novel_id=1, chapter_image_id=1
                )

        assert mock_chapter_image.status == "failed"
        assert mock_chapter_image.error_message == "GPU out of memory"
