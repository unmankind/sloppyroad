"""Image evolution system — portrait evolution, map expansion, initial assets.

Manages the lifecycle of visual assets as the story progresses:
- Character portraits evolve when characters change
- World maps expand as new regions are revealed
- Initial assets are generated after the world pipeline completes
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import ArtAsset, Character, Region
from aiwebnovel.images.prompts import ImagePromptComposer
from aiwebnovel.images.provider import ImageProvider, ImageRequest, Img2ImgRequest
from aiwebnovel.llm.provider import LLMProvider

logger = structlog.get_logger(__name__)


class ImageEvolver:
    """Handles image evolution chains and initial asset generation."""

    def __init__(
        self,
        image_provider: ImageProvider,
        llm: LLMProvider,
        settings: Settings,
    ) -> None:
        self.image_provider = image_provider
        self.llm = llm
        self.settings = settings
        self.composer = ImagePromptComposer(llm, settings)

    def _asset_path(
        self, novel_id: int, asset_type: str, version: int
    ) -> str:
        """Build the file path for an image asset."""
        base = self.settings.image_asset_path
        return f"{base}/{novel_id}/{asset_type}/v{version}.png"

    async def _save_image(
        self,
        novel_id: int,
        asset_type: str,
        version: int,
        image_data: bytes,
    ) -> str:
        """Save image data to disk, creating directories as needed."""
        path = self._asset_path(novel_id, asset_type, version)
        dir_path = os.path.dirname(path)
        os.makedirs(dir_path, exist_ok=True)
        Path(path).write_bytes(image_data)
        return path

    async def evolve_portrait(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        character_id: int,
        change_description: str,
    ) -> int:
        """Generate an evolved portrait for a character.

        1. Load character + current portrait
        2. Compose evolution prompt (describe visual changes)
        3. Use img2img if provider supports, else generate fresh
        4. Store new ArtAsset with version+1, mark as current
        5. Mark previous version as not current
        6. Return new asset ID

        Args:
            session_factory: Async session factory for DB access.
            character_id: The character to evolve.
            change_description: What changed (e.g., "gained a scar").

        Returns:
            The new ArtAsset.id.
        """
        async with session_factory() as session:
            # Load character
            char_stmt = select(Character).where(Character.id == character_id)
            char_result = await session.execute(char_stmt)
            character = char_result.scalar_one()

            # Find current portrait
            portrait_stmt = (
                select(ArtAsset)
                .where(
                    ArtAsset.entity_id == character_id,
                    ArtAsset.entity_type == "character",
                    ArtAsset.asset_type == "portrait",
                    ArtAsset.is_current.is_(True),
                )
                .order_by(ArtAsset.version.desc())
            )
            portrait_result = await session.execute(portrait_stmt)
            current_portrait = portrait_result.scalar_one_or_none()

            current_version = current_portrait.version if current_portrait else 0
            new_version = current_version + 1
            novel_id = character.novel_id
            current_portrait_id = current_portrait.id if current_portrait else None
            current_portrait_path = current_portrait.file_path if current_portrait else None

        # Load style guide for consistent visuals
        style = await self.composer.get_style_guide(session_factory, novel_id)
        prefix = style.get("base_prompt_prefix", "")
        palette = style.get("color_palette", [])

        # Compose prompt with style context
        prompt_parts = []
        if prefix:
            prompt_parts.append(prefix)
        prompt_parts.append(
            f"Character portrait of {character.name}: {character.description}. "
            f"Change: {change_description}"
        )
        if palette:
            prompt_parts.append(f"color palette: {', '.join(palette)}")
        base_prompt = ", ".join(prompt_parts)

        # Try img2img if we have a source image and provider supports it
        if (
            current_portrait_path
            and self.image_provider.supports_img2img
        ):
            request = Img2ImgRequest(
                prompt=base_prompt,
                source_image_path=current_portrait_path,
                strength=0.7,
            )
            await self.composer._apply_style_overrides(request, style, session_factory)
            generated = await self.image_provider.img2img(request)
        else:
            request = ImageRequest(prompt=base_prompt)
            await self.composer._apply_style_overrides(request, style, session_factory)
            generated = await self.image_provider.generate(request)

        # Save image to disk
        file_path = await self._save_image(
            novel_id, f"portrait_{character_id}", new_version, generated.image_data
        )

        async with session_factory() as session:
            # Mark old portrait as not current
            if current_portrait_id:
                old_stmt = select(ArtAsset).where(ArtAsset.id == current_portrait_id)
                old_result = await session.execute(old_stmt)
                old_portrait = old_result.scalar_one_or_none()
                if old_portrait:
                    old_portrait.is_current = False

            # Create new asset
            new_asset = ArtAsset(
                novel_id=novel_id,
                asset_type="portrait",
                entity_id=character_id,
                entity_type="character",
                prompt_used=base_prompt,
                file_path=file_path,
                provider=generated.provider,
                model_used=generated.model,
                width=generated.width,
                height=generated.height,
                seed_value=generated.seed,
                version=new_version,
                is_current=True,
                parent_asset_id=current_portrait_id,
                description=change_description,
            )
            session.add(new_asset)
            await session.flush()
            new_id = new_asset.id
            await session.commit()

        logger.info(
            "portrait_evolved",
            character_id=character_id,
            new_version=new_version,
            asset_id=new_id,
        )
        return new_id

    async def expand_map(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        novel_id: int,
        new_region_ids: list[int],
    ) -> int:
        """Expand world map with newly revealed regions.

        Args:
            session_factory: Async session factory for DB access.
            novel_id: The novel's world map to expand.
            new_region_ids: IDs of newly revealed regions to add.

        Returns:
            The new ArtAsset.id for the updated map.
        """
        async with session_factory() as session:
            # Find current map
            map_stmt = (
                select(ArtAsset)
                .where(
                    ArtAsset.novel_id == novel_id,
                    ArtAsset.asset_type == "world_map",
                    ArtAsset.is_current.is_(True),
                )
                .order_by(ArtAsset.version.desc())
            )
            map_result = await session.execute(map_stmt)
            current_map = map_result.scalar_one_or_none()

            current_version = current_map.version if current_map else 0
            new_version = current_version + 1
            current_map_id = current_map.id if current_map else None
            current_map_path = current_map.file_path if current_map else None

            # Load new regions
            region_stmt = select(Region).where(Region.id.in_(new_region_ids))
            region_result = await session.execute(region_stmt)
            regions = region_result.scalars().all()

            region_desc = ", ".join(
                f"{r.name}: {r.description}" for r in regions
            )
            region_names = [r.name for r in regions]

        # Load style guide for consistent visuals
        style = await self.composer.get_style_guide(session_factory, novel_id)
        prefix = style.get("base_prompt_prefix", "")
        palette = style.get("color_palette", [])

        prompt_parts = []
        if prefix:
            prompt_parts.append(prefix)
        prompt_parts.append(
            f"Fantasy world map showing newly revealed regions: {region_desc}. "
            f"Stylized cartography, dark fantasy aesthetic."
        )
        if palette:
            prompt_parts.append(f"color palette: {', '.join(palette)}")
        prompt = ", ".join(prompt_parts)

        # Generate new map
        if (
            current_map_path
            and self.image_provider.supports_img2img
        ):
            request = Img2ImgRequest(
                prompt=prompt,
                source_image_path=current_map_path,
                strength=0.5,
            )
            await self.composer._apply_style_overrides(request, style, session_factory)
            generated = await self.image_provider.img2img(request)
        else:
            request = ImageRequest(prompt=prompt)
            await self.composer._apply_style_overrides(request, style, session_factory)
            generated = await self.image_provider.generate(request)

        # Save
        file_path = await self._save_image(
            novel_id, "world_map", new_version, generated.image_data
        )

        async with session_factory() as session:
            # Mark old map as not current
            if current_map_id:
                old_stmt = select(ArtAsset).where(ArtAsset.id == current_map_id)
                old_result = await session.execute(old_stmt)
                old_map = old_result.scalar_one_or_none()
                if old_map:
                    old_map.is_current = False

            new_asset = ArtAsset(
                novel_id=novel_id,
                asset_type="world_map",
                prompt_used=prompt,
                file_path=file_path,
                provider=generated.provider,
                model_used=generated.model,
                width=generated.width,
                height=generated.height,
                seed_value=generated.seed,
                version=new_version,
                is_current=True,
                parent_asset_id=current_map_id,
                description=f"Map expanded with: {', '.join(region_names)}",
            )
            session.add(new_asset)
            await session.flush()
            new_id = new_asset.id
            await session.commit()

        logger.info(
            "map_expanded",
            novel_id=novel_id,
            new_regions=len(new_region_ids),
            asset_id=new_id,
        )
        return new_id

    async def generate_initial_assets(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        novel_id: int,
    ) -> list[int]:
        """Generate initial visual assets after world pipeline completes.

        Creates:
        - Protagonist portrait
        - World map
        - Key location art (optional)

        Args:
            session_factory: Async session factory for DB access.
            novel_id: The novel to generate assets for.

        Returns:
            List of new ArtAsset IDs.
        """
        asset_ids: list[int] = []

        async with session_factory() as session:
            # Find protagonist
            char_stmt = (
                select(Character)
                .where(
                    Character.novel_id == novel_id,
                    Character.role == "protagonist",
                )
            )
            char_result = await session.execute(char_stmt)
            protagonist = char_result.scalar_one_or_none()

            # Get regions for map
            region_stmt = select(Region).where(Region.novel_id == novel_id)
            region_result = await session.execute(region_stmt)
            regions = region_result.scalars().all()

        # Load style guide for consistent visuals
        style = await self.composer.get_style_guide(session_factory, novel_id)
        prefix = style.get("base_prompt_prefix", "")
        palette = style.get("color_palette", [])

        # Generate protagonist portrait
        if protagonist is not None:
            prompt_parts = []
            if prefix:
                prompt_parts.append(prefix)
            prompt_parts.append(
                f"Character portrait of {protagonist.name}: {protagonist.description}"
            )
            if palette:
                prompt_parts.append(f"color palette: {', '.join(palette)}")
            prompt = ", ".join(prompt_parts)

            request = ImageRequest(prompt=prompt)
            await self.composer._apply_style_overrides(request, style, session_factory)
            generated = await self.image_provider.generate(request)

            file_path = await self._save_image(
                novel_id, f"portrait_{protagonist.id}", 1, generated.image_data
            )

            async with session_factory() as session:
                asset = ArtAsset(
                    novel_id=novel_id,
                    asset_type="portrait",
                    entity_id=protagonist.id,
                    entity_type="character",
                    prompt_used=prompt,
                    file_path=file_path,
                    provider=generated.provider,
                    model_used=generated.model,
                    width=generated.width,
                    height=generated.height,
                    seed_value=generated.seed,
                    version=1,
                    is_current=True,
                )
                session.add(asset)
                await session.flush()
                asset_ids.append(asset.id)
                await session.commit()

        # Generate world map
        if regions:
            region_desc = ", ".join(f"{r.name}: {r.description}" for r in regions)
            map_parts = []
            if prefix:
                map_parts.append(prefix)
            map_parts.append(
                f"Fantasy world map showing: {region_desc}. "
                f"Stylized cartography, dark fantasy aesthetic."
            )
            if palette:
                map_parts.append(f"color palette: {', '.join(palette)}")
            map_prompt = ", ".join(map_parts)

            map_request = ImageRequest(prompt=map_prompt)
            await self.composer._apply_style_overrides(map_request, style, session_factory)
            map_generated = await self.image_provider.generate(map_request)

            map_path = await self._save_image(
                novel_id, "world_map", 1, map_generated.image_data
            )

            async with session_factory() as session:
                map_asset = ArtAsset(
                    novel_id=novel_id,
                    asset_type="world_map",
                    prompt_used=map_prompt,
                    file_path=map_path,
                    provider=map_generated.provider,
                    model_used=map_generated.model,
                    width=map_generated.width,
                    height=map_generated.height,
                    seed_value=map_generated.seed,
                    version=1,
                    is_current=True,
                )
                session.add(map_asset)
                await session.flush()
                asset_ids.append(map_asset.id)
                await session.commit()

        logger.info(
            "initial_assets_generated",
            novel_id=novel_id,
            asset_count=len(asset_ids),
        )
        return asset_ids
