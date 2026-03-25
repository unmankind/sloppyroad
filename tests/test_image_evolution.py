"""Tests for image evolution system — portraits, maps, initial assets."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArtAsset,
    ArtStyleGuide,
    AuthorProfile,
    Base,
    Character,
    Novel,
    Region,
    User,
)
from aiwebnovel.images.evolution import ImageEvolver
from aiwebnovel.images.provider import GeneratedImage


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key-for-testing-only",
        image_enabled=True,
        image_asset_path="/tmp/test_assets",
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
def mock_image_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.supports_img2img = True
    provider.generate = AsyncMock(
        return_value=GeneratedImage(
            image_data=b"fake_portrait_data",
            width=1024,
            height=1024,
            provider="comfyui",
            model="sdxl",
            seed=42,
        )
    )
    provider.img2img = AsyncMock(
        return_value=GeneratedImage(
            image_data=b"fake_evolved_data",
            width=1024,
            height=1024,
            provider="comfyui",
            model="sdxl",
            seed=43,
        )
    )
    return provider


@pytest.fixture()
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=MagicMock(content="portrait prompt"))
    return llm


@pytest.fixture()
def evolver(
    mock_image_provider: AsyncMock,
    mock_llm: MagicMock,
    test_settings: Settings,
) -> ImageEvolver:
    return ImageEvolver(mock_image_provider, mock_llm, test_settings)


async def _seed_novel(session: AsyncSession) -> tuple[int, int, int]:
    """Create user + novel + protagonist character. Return (user_id, novel_id, char_id)."""
    user = User(
        email="artist@test.com",
        username="artist",
        hashed_password="hash",
        role="author",
    )
    session.add(user)
    await session.flush()

    profile = AuthorProfile(user_id=user.id, api_budget_cents=5000)
    session.add(profile)

    novel = Novel(author_id=user.id, title="Art Novel", status="writing")
    session.add(novel)
    await session.flush()

    char = Character(
        novel_id=novel.id,
        name="Hero Protagonist",
        role="protagonist",
        description="A tall warrior with silver hair and piercing blue eyes.",
    )
    session.add(char)
    await session.flush()

    # Add a style guide
    guide = ArtStyleGuide(
        novel_id=novel.id,
        style_description="Dark fantasy, painterly style",
        style_name="default",
        base_prompt_prefix="dark fantasy painting, highly detailed",
        base_negative_prompt="blurry, low quality",
    )
    session.add(guide)
    await session.flush()

    await session.commit()
    return user.id, novel.id, char.id


class TestEvolvePortrait:
    """Tests for portrait evolution."""

    @pytest.mark.asyncio
    async def test_creates_new_version(
        self, evolver: ImageEvolver, session_factory
    ) -> None:
        """evolve_portrait should create a new ArtAsset with incremented version."""
        async with session_factory() as session:
            user_id, novel_id, char_id = await _seed_novel(session)
            # Create an existing portrait (v1)
            existing = ArtAsset(
                novel_id=novel_id,
                asset_type="portrait",
                entity_id=char_id,
                entity_type="character",
                prompt_used="original prompt",
                file_path="/tmp/v1.png",
                version=1,
                is_current=True,
            )
            session.add(existing)
            await session.flush()
            v1_id = existing.id
            await session.commit()

        with patch("aiwebnovel.images.evolution.os.makedirs"):
            with patch("aiwebnovel.images.evolution.Path.write_bytes"):
                new_id = await evolver.evolve_portrait(
                    session_factory, char_id, "gained a scar across their left eye"
                )

        assert new_id is not None
        assert new_id != v1_id

    @pytest.mark.asyncio
    async def test_marks_old_version_not_current(
        self, evolver: ImageEvolver, session_factory
    ) -> None:
        """evolve_portrait should mark the previous version as not current."""
        async with session_factory() as session:
            user_id, novel_id, char_id = await _seed_novel(session)
            existing = ArtAsset(
                novel_id=novel_id,
                asset_type="portrait",
                entity_id=char_id,
                entity_type="character",
                prompt_used="original prompt",
                file_path="/tmp/v1.png",
                version=1,
                is_current=True,
            )
            session.add(existing)
            await session.flush()
            v1_id = existing.id
            await session.commit()

        with patch("aiwebnovel.images.evolution.os.makedirs"):
            with patch("aiwebnovel.images.evolution.Path.write_bytes"):
                await evolver.evolve_portrait(
                    session_factory, char_id, "hair turned white"
                )

        async with session_factory() as session:
            stmt = select(ArtAsset).where(ArtAsset.id == v1_id)
            result = await session.execute(stmt)
            old = result.scalar_one()
            assert old.is_current is False


class TestGenerateInitialAssets:
    """Tests for initial asset generation after world pipeline."""

    @pytest.mark.asyncio
    async def test_creates_protagonist_portrait_and_map(
        self, evolver: ImageEvolver, session_factory
    ) -> None:
        """generate_initial_assets should create portrait + world map."""
        async with session_factory() as session:
            user_id, novel_id, char_id = await _seed_novel(session)
            # Add a region for map generation
            region = Region(
                novel_id=novel_id,
                name="Crystal Mountains",
                description="Towering peaks of crystallized mana.",
            )
            session.add(region)
            await session.commit()

        with patch("aiwebnovel.images.evolution.os.makedirs"):
            with patch("aiwebnovel.images.evolution.Path.write_bytes"):
                asset_ids = await evolver.generate_initial_assets(
                    session_factory, novel_id
                )

        # Should have at least portrait + map
        assert len(asset_ids) >= 2


class TestExpandMap:
    """Tests for map expansion with new regions."""

    @pytest.mark.asyncio
    async def test_adds_new_regions(
        self, evolver: ImageEvolver, session_factory
    ) -> None:
        """expand_map should create a new map asset incorporating new regions."""
        async with session_factory() as session:
            user_id, novel_id, char_id = await _seed_novel(session)
            # Add existing map
            map_asset = ArtAsset(
                novel_id=novel_id,
                asset_type="world_map",
                prompt_used="initial map",
                file_path="/tmp/map_v1.png",
                version=1,
                is_current=True,
            )
            session.add(map_asset)
            # Add new region
            new_region = Region(
                novel_id=novel_id,
                name="Shadow Wastes",
                description="A desolate wasteland corrupted by dark energy.",
            )
            session.add(new_region)
            await session.flush()
            region_id = new_region.id
            await session.commit()

        with patch("aiwebnovel.images.evolution.os.makedirs"):
            with patch("aiwebnovel.images.evolution.Path.write_bytes"):
                new_id = await evolver.expand_map(
                    session_factory, novel_id, [region_id]
                )

        assert new_id is not None
