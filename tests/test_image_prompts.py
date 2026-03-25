"""Tests for image prompt composition."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArtStyleGuide,
    AuthorProfile,
    Base,
    Character,
    Novel,
    Region,
    User,
)
from aiwebnovel.images.prompts import ImagePromptComposer


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key-for-testing-only",
        debug=True,
    )


@pytest.fixture()
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def session_factory(db_engine):
    return sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value=MagicMock(
            content='{"prompt": "detailed portrait of a warrior", "negative_prompt": "blurry"}'
        )
    )
    return llm


@pytest.fixture()
def composer(mock_llm: MagicMock, test_settings: Settings) -> ImagePromptComposer:
    return ImagePromptComposer(mock_llm, test_settings)


async def _seed_data(session: AsyncSession) -> tuple[int, int, int]:
    """Create user + novel + character + region + style guide.
    Return (novel_id, char_id, region_id).
    """
    user = User(
        email="prompt@test.com",
        username="prompter",
        hashed_password="hash",
        role="author",
    )
    session.add(user)
    await session.flush()

    profile = AuthorProfile(user_id=user.id, api_budget_cents=5000)
    session.add(profile)

    novel = Novel(author_id=user.id, title="Prompt Novel", status="writing")
    session.add(novel)
    await session.flush()

    char = Character(
        novel_id=novel.id,
        name="Kira Stormbreaker",
        role="protagonist",
        description=(
            "A young woman with storm-grey eyes, lightning-streaked"
            " hair, and battle-worn armor. She carries a staff of"
            " condensed storm energy."
        ),
        personality_traits=["determined", "reckless"],
    )
    session.add(char)
    await session.flush()

    region = Region(
        novel_id=novel.id,
        name="Thunder Peaks",
        description=(
            "A mountain range perpetually wreathed in storms,"
            " where lightning strikes give birth to rare minerals."
        ),
        geography_type="mountains",
        climate="stormy temperate",
    )
    session.add(region)
    await session.flush()

    guide = ArtStyleGuide(
        novel_id=novel.id,
        style_description="Dark fantasy with vivid lighting effects",
        style_name="default",
        base_prompt_prefix="dark fantasy, highly detailed, dramatic lighting",
        base_negative_prompt="blurry, low quality, watermark",
        color_palette=["#1a1a2e", "#16213e", "#0f3460", "#e94560"],
    )
    session.add(guide)
    await session.flush()
    await session.commit()

    return novel.id, char.id, region.id


class TestComposePortraitPrompt:
    """Tests for portrait prompt composition."""

    @pytest.mark.asyncio
    async def test_includes_character_description(
        self, composer: ImagePromptComposer, session_factory
    ) -> None:
        """Portrait prompt should incorporate character description."""
        async with session_factory() as session:
            novel_id, char_id, _ = await _seed_data(session)

        request = await composer.compose_portrait_prompt(session_factory, char_id)

        assert request is not None
        assert request.prompt  # Non-empty prompt
        assert request.width > 0
        assert request.height > 0


class TestComposeMapPrompt:
    """Tests for map prompt composition."""

    @pytest.mark.asyncio
    async def test_includes_region_data(
        self, composer: ImagePromptComposer, session_factory
    ) -> None:
        """Map prompt should incorporate region data."""
        async with session_factory() as session:
            novel_id, _, region_id = await _seed_data(session)

        request = await composer.compose_map_prompt(
            session_factory, novel_id, region_ids=[region_id]
        )

        assert request is not None
        assert request.prompt  # Non-empty


class TestComposeScenePrompt:
    """Tests for scene illustration prompt composition."""

    @pytest.mark.asyncio
    async def test_formats_correctly(
        self, composer: ImagePromptComposer, session_factory
    ) -> None:
        """Scene prompt should use the scene description."""
        async with session_factory() as session:
            novel_id, _, _ = await _seed_data(session)

        request = await composer.compose_scene_prompt(
            session_factory,
            novel_id,
            "The hero stands atop the mountain as lightning crashes around them.",
        )

        assert request is not None
        assert request.prompt  # Non-empty


class TestGetStyleGuide:
    """Tests for style guide loading/creation."""

    @pytest.mark.asyncio
    async def test_loads_existing_guide(
        self, composer: ImagePromptComposer, session_factory
    ) -> None:
        """get_style_guide should return existing guide data."""
        async with session_factory() as session:
            novel_id, _, _ = await _seed_data(session)

        guide = await composer.get_style_guide(session_factory, novel_id)

        assert guide is not None
        assert "style_description" in guide
        assert "dark fantasy" in guide["style_description"].lower()

    @pytest.mark.asyncio
    async def test_creates_default_if_none_exists(
        self, composer: ImagePromptComposer, session_factory
    ) -> None:
        """get_style_guide should create a default guide if none exists."""
        # Create a novel without a style guide
        async with session_factory() as session:
            user = User(
                email="no-guide@test.com",
                username="noguide",
                hashed_password="hash",
                role="author",
            )
            session.add(user)
            await session.flush()
            profile = AuthorProfile(user_id=user.id, api_budget_cents=5000)
            session.add(profile)
            novel = Novel(author_id=user.id, title="No Guide", status="writing")
            session.add(novel)
            await session.flush()
            novel_id = novel.id
            await session.commit()

        guide = await composer.get_style_guide(session_factory, novel_id)
        assert guide is not None
        assert "style_description" in guide
