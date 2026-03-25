"""Tests for image generation pipeline triggers.

Verifies that world and chapter tasks fire image generation
when image_enabled=True and appropriate events occur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aiwebnovel.config import Settings
from aiwebnovel.worker.tasks import (
    _generate_initial_assets,
    _trigger_chapter_images,
    _trigger_scene_images,
    generate_chapter_task,
    generate_scene_image_task,
    generate_world_task,
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
def disabled_image_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key",
        image_enabled=False,
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
# World task -> initial assets
# ---------------------------------------------------------------------------


class TestWorldTaskImageTrigger:
    """Test that world generation triggers initial asset generation."""

    @pytest.mark.asyncio
    async def test_world_success_triggers_initial_assets(self, mock_ctx: dict) -> None:
        """Successful world gen with image_enabled fires _generate_initial_assets."""
        mock_world_result = MagicMock(
            success=True, stages_completed=["cosmology"], error=None,
        )
        mock_ctx["pipeline"].generate_world = AsyncMock(return_value=mock_world_result)

        with patch(
            "aiwebnovel.worker.tasks_images._generate_initial_assets", new_callable=AsyncMock
        ) as mock_gen:
            result = await generate_world_task(mock_ctx, novel_id=1, user_id=1)

        assert result["success"] is True
        mock_gen.assert_awaited_once_with(mock_ctx, 1, 1)

    @pytest.mark.asyncio
    async def test_world_failure_skips_images(self, mock_ctx: dict) -> None:
        """Failed world gen does not trigger image generation."""
        mock_world_result = MagicMock(
            success=False, stages_completed=[], error="boom",
        )
        mock_ctx["pipeline"].generate_world = AsyncMock(return_value=mock_world_result)

        with patch(
            "aiwebnovel.worker.tasks_images._generate_initial_assets", new_callable=AsyncMock
        ) as mock_gen:
            result = await generate_world_task(mock_ctx, novel_id=1, user_id=1)

        assert result["success"] is False
        mock_gen.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_images_disabled_skips(
        self, mock_ctx: dict, disabled_image_settings: Settings
    ) -> None:
        """image_enabled=False skips image generation."""
        mock_ctx["settings"] = disabled_image_settings
        mock_world_result = MagicMock(
            success=True, stages_completed=["cosmology"], error=None,
        )
        mock_ctx["pipeline"].generate_world = AsyncMock(return_value=mock_world_result)

        with patch(
            "aiwebnovel.worker.tasks_images._generate_initial_assets", new_callable=AsyncMock
        ) as mock_gen:
            await generate_world_task(mock_ctx, novel_id=1, user_id=1)

        mock_gen.assert_not_awaited()


# ---------------------------------------------------------------------------
# _generate_initial_assets
# ---------------------------------------------------------------------------


class TestGenerateInitialAssets:
    """Test the initial asset generation helper."""

    @pytest.mark.asyncio
    async def test_enqueues_cover_portraits_and_map(self, mock_ctx: dict) -> None:
        """Should enqueue cover, character portraits, and world map via art queue."""
        # Mock character query — return one protagonist
        mock_char = MagicMock()
        mock_char.id = 42
        mock_char.role = "protagonist"

        mock_chars_result = MagicMock()
        mock_chars_result.scalars.return_value.all.return_value = [mock_char]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_chars_result)
        mock_ctx["session_factory"].return_value.__aenter__ = AsyncMock(
            return_value=session
        )

        enqueue_calls: list = []

        async def fake_enqueue(sess, **kwargs):
            enqueue_calls.append(kwargs)
            return len(enqueue_calls)

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation",
            side_effect=fake_enqueue,
        ), patch(
            "aiwebnovel.worker.tasks_images.derive_style_from_world",
            new_callable=AsyncMock,
        ):
            await _generate_initial_assets(mock_ctx, novel_id=1, user_id=1)

        # Should enqueue: cover + 1 portrait + world_map = 3 entries
        assert len(enqueue_calls) == 3
        asset_types = [c["asset_type"] for c in enqueue_calls]
        assert "cover" in asset_types
        assert "portrait" in asset_types
        assert "world_map" in asset_types

    @pytest.mark.asyncio
    async def test_no_characters_still_enqueues_cover_and_map(self, mock_ctx: dict) -> None:
        """If no characters found, still enqueue cover + world map."""
        mock_chars_result = MagicMock()
        mock_chars_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_chars_result)
        mock_ctx["session_factory"].return_value.__aenter__ = AsyncMock(
            return_value=session
        )

        enqueue_calls: list = []

        async def fake_enqueue(sess, **kwargs):
            enqueue_calls.append(kwargs)
            return len(enqueue_calls)

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation",
            side_effect=fake_enqueue,
        ), patch(
            "aiwebnovel.worker.tasks_images.derive_style_from_world",
            new_callable=AsyncMock,
        ):
            await _generate_initial_assets(mock_ctx, novel_id=1, user_id=1)

        # cover + world_map = 2 entries (no portraits)
        assert len(enqueue_calls) == 2
        asset_types = [c["asset_type"] for c in enqueue_calls]
        assert "cover" in asset_types
        assert "world_map" in asset_types
        assert "portrait" not in asset_types

    @pytest.mark.asyncio
    async def test_enqueue_failure_does_not_raise(self, mock_ctx: dict) -> None:
        """Enqueue failure should be logged, not raised."""
        mock_chars_result = MagicMock()
        mock_chars_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_chars_result)
        mock_ctx["session_factory"].return_value.__aenter__ = AsyncMock(
            return_value=session
        )

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB down"),
        ), patch(
            "aiwebnovel.worker.tasks_images.derive_style_from_world",
            new_callable=AsyncMock,
        ):
            # Should not raise
            await _generate_initial_assets(mock_ctx, novel_id=1, user_id=1)


# ---------------------------------------------------------------------------
# Chapter task -> rank-up portraits
# ---------------------------------------------------------------------------


@dataclass
class FakePowerEvent:
    character_name: str = "Kai"
    event_type: str = "rank_up"
    new_rank: str | None = "Silver"
    description: str = "Kai advanced to Silver rank"
    struggle_context: str = "grueling trial"
    foundation: str = "training arc"


@dataclass
class FakeSystemAnalysis:
    power_events: list = field(default_factory=list)
    earned_power_evaluations: list = field(default_factory=list)
    ability_usages: list = field(default_factory=list)
    consistency_issues: list = field(default_factory=list)
    chekhov_interactions: list = field(default_factory=list)
    has_critical_violations: bool = False


@dataclass
class FakeAnalysis:
    system: FakeSystemAnalysis | None = None
    system_success: bool = True
    narrative: object = None
    narrative_success: bool = True

    @property
    def success(self) -> bool:
        return self.narrative_success and self.system_success


class TestChapterTaskImageTrigger:
    """Test that chapter generation triggers portrait evolution on rank-ups."""

    @pytest.mark.asyncio
    async def test_rank_up_triggers_portrait(self, mock_ctx: dict) -> None:
        """Power event with new_rank enqueues portrait via art queue."""
        # Mock character lookup
        mock_char = MagicMock()
        mock_char.id = 7

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_char

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_ctx["session_factory"].return_value.__aenter__ = AsyncMock(
            return_value=session
        )

        analysis = FakeAnalysis(
            system=FakeSystemAnalysis(
                power_events=[FakePowerEvent(character_name="Kai", new_rank="Silver")]
            ),
        )

        enqueue_calls: list = []

        async def fake_enqueue(sess, **kwargs):
            enqueue_calls.append(kwargs)
            return len(enqueue_calls)

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation",
            side_effect=fake_enqueue,
        ):
            await _trigger_chapter_images(mock_ctx, novel_id=1, analysis=analysis)

        assert len(enqueue_calls) == 1
        assert enqueue_calls[0]["asset_type"] == "portrait"
        assert enqueue_calls[0]["entity_id"] == 7
        assert enqueue_calls[0]["entity_type"] == "character"

    @pytest.mark.asyncio
    async def test_no_rank_up_skips(self, mock_ctx: dict) -> None:
        """Power events without new_rank should not trigger images."""
        analysis = FakeAnalysis(
            system=FakeSystemAnalysis(
                power_events=[FakePowerEvent(new_rank=None)]
            ),
        )

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation", new_callable=AsyncMock
        ) as mock_enqueue:
            await _trigger_chapter_images(mock_ctx, novel_id=1, analysis=analysis)

        mock_enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_system_analysis_skips(self, mock_ctx: dict) -> None:
        """Missing system analysis should not trigger images."""
        analysis = FakeAnalysis(system=None, system_success=False)

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation", new_callable=AsyncMock
        ) as mock_enqueue:
            await _trigger_chapter_images(mock_ctx, novel_id=1, analysis=analysis)

        mock_enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enqueue_failure_does_not_raise(self, mock_ctx: dict) -> None:
        """Enqueue failure should be logged, not raised."""
        mock_char = MagicMock()
        mock_char.id = 7

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_char

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_ctx["session_factory"].return_value.__aenter__ = AsyncMock(
            return_value=session
        )

        analysis = FakeAnalysis(
            system=FakeSystemAnalysis(
                power_events=[FakePowerEvent(new_rank="Gold")]
            ),
        )

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB down"),
        ):
            # Should not raise
            await _trigger_chapter_images(mock_ctx, novel_id=1, analysis=analysis)

    @pytest.mark.asyncio
    async def test_character_not_found_skips(self, mock_ctx: dict) -> None:
        """If character name not found in DB, skip portrait generation."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_ctx["session_factory"].return_value.__aenter__ = AsyncMock(
            return_value=session
        )

        analysis = FakeAnalysis(
            system=FakeSystemAnalysis(
                power_events=[FakePowerEvent(character_name="Unknown", new_rank="Silver")]
            ),
        )

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation", new_callable=AsyncMock
        ) as mock_enqueue:
            await _trigger_chapter_images(mock_ctx, novel_id=1, analysis=analysis)

        mock_enqueue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Scene image generation
# ---------------------------------------------------------------------------


@dataclass
class FakeChapterImage:
    id: int = 1
    chapter_id: int = 10
    paragraph_index: int = 2
    scene_description: str = "A warrior on a cliff"
    status: str = "pending"


class TestTriggerSceneImages:
    """Test the _trigger_scene_images helper."""

    @pytest.mark.asyncio
    async def test_triggers_for_pending_images(self, mock_ctx: dict) -> None:
        """Should enqueue art generation for each pending ChapterImage."""
        fake_images = [
            FakeChapterImage(id=1, paragraph_index=0),
            FakeChapterImage(id=2, paragraph_index=3),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = fake_images

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_ctx["session_factory"].return_value.__aenter__ = AsyncMock(
            return_value=session
        )

        enqueue_calls: list = []

        async def fake_enqueue(sess, **kwargs):
            enqueue_calls.append(kwargs)
            return len(enqueue_calls)

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation",
            side_effect=fake_enqueue,
        ):
            await _trigger_scene_images(mock_ctx, novel_id=1, chapter_id=10)

        assert len(enqueue_calls) == 2
        assert enqueue_calls[0]["asset_type"] == "scene"
        assert enqueue_calls[0]["entity_id"] == 1
        assert enqueue_calls[1]["entity_id"] == 2

    @pytest.mark.asyncio
    async def test_none_chapter_id_skips(self, mock_ctx: dict) -> None:
        """None chapter_id should skip entirely."""
        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation", new_callable=AsyncMock
        ) as mock_enqueue:
            await _trigger_scene_images(mock_ctx, novel_id=1, chapter_id=None)

        mock_enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scene_enqueue_failure_does_not_raise(self, mock_ctx: dict) -> None:
        """Individual scene enqueue failures should not propagate."""
        fake_images = [FakeChapterImage(id=1)]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = fake_images

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_ctx["session_factory"].return_value.__aenter__ = AsyncMock(
            return_value=session
        )

        with patch(
            "aiwebnovel.worker.tasks_images.enqueue_art_generation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB down"),
        ):
            # Should not raise
            await _trigger_scene_images(mock_ctx, novel_id=1, chapter_id=10)


class TestGenerateSceneImageTask:
    """Test the generate_scene_image_task function."""

    @pytest.mark.asyncio
    async def test_chapter_image_not_found(self, mock_ctx: dict) -> None:
        """Should return error if ChapterImage not found."""
        from aiwebnovel.images.budget import ImageBudgetResult

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_ctx["session_factory"].return_value.__aenter__ = AsyncMock(
            return_value=session
        )

        with patch(
            "aiwebnovel.worker.tasks_images.check_image_budget",
            new_callable=AsyncMock,
            return_value=ImageBudgetResult(allowed=True),
        ):
            result = await generate_scene_image_task(
                mock_ctx, novel_id=1, chapter_image_id=999
            )

        assert result["success"] is False
        assert "not found" in result["error"]


class TestChapterTaskSceneTrigger:
    """Test that generate_chapter_task triggers scene images."""

    @pytest.mark.asyncio
    async def test_scene_images_triggered_on_success(self, mock_ctx: dict) -> None:
        """Successful chapter with scene markers triggers _trigger_scene_images."""
        mock_chapter_result = MagicMock(
            success=True,
            chapter_id=42,
            chapter_text="Clean text",
            scene_markers=[MagicMock()],  # Non-empty markers
            analysis=None,
            flagged_for_review=False,
            error=None,
        )
        mock_ctx["pipeline"].generate_chapter = AsyncMock(
            return_value=mock_chapter_result
        )

        with patch(
            "aiwebnovel.worker.tasks_images._trigger_scene_images", new_callable=AsyncMock
        ) as mock_trigger, patch(
            "aiwebnovel.worker.tasks_images._trigger_chapter_images", new_callable=AsyncMock
        ):
            result = await generate_chapter_task(
                mock_ctx, novel_id=1, chapter_number=1, user_id=1, job_id="test"
            )

        assert result["success"] is True
        mock_trigger.assert_awaited_once_with(mock_ctx, 1, 42)

    @pytest.mark.asyncio
    async def test_no_scene_markers_skips_trigger(self, mock_ctx: dict) -> None:
        """No scene markers should not trigger scene image generation."""
        mock_chapter_result = MagicMock(
            success=True,
            chapter_id=42,
            chapter_text="Clean text",
            scene_markers=[],  # Empty markers
            analysis=None,
            flagged_for_review=False,
            error=None,
        )
        mock_ctx["pipeline"].generate_chapter = AsyncMock(
            return_value=mock_chapter_result
        )

        with patch(
            "aiwebnovel.worker.tasks_images._trigger_scene_images", new_callable=AsyncMock
        ) as mock_trigger, patch(
            "aiwebnovel.worker.tasks_images._trigger_chapter_images", new_callable=AsyncMock
        ):
            result = await generate_chapter_task(
                mock_ctx, novel_id=1, chapter_number=1, user_id=1, job_id="test"
            )

        assert result["success"] is True
        mock_trigger.assert_not_awaited()
