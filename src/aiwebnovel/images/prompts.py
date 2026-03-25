"""Image prompt composition — narrative text to image generation prompts.

Transforms character descriptions, geography data, and scene descriptions
into well-structured prompts for image generation providers.  Uses LLM prompt
templates (CHARACTER_PORTRAIT, MAP_PROMPT, SCENE_ILLUSTRATION) when available,
falling back to simple string concatenation on failure.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArtAsset,
    ArtStyleGuide,
    Character,
    Novel,
    PowerSystem,
    Region,
    WorldBuildingStage,
)
from aiwebnovel.images.provider import ImageRequest
from aiwebnovel.llm.parsers import ImagePromptResult
from aiwebnovel.llm.prompts import (
    CHARACTER_PORTRAIT,
    COVER_ART,
    IMAGE_REGENERATION,
    MAP_PROMPT,
    SCENE_ILLUSTRATION,
)

logger = structlog.get_logger(__name__)

# Map aspect_ratio strings returned by the LLM to (width, height) in pixels.
_ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1024, 576),
    "9:16": (576, 1024),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "3:2": (1024, 683),
    "2:3": (683, 1024),
}

# Default style guide applied when no custom guide exists
_DEFAULT_STYLE: dict[str, Any] = {
    "style_description": "Dark fantasy illustration, highly detailed",
    "style_name": "default",
    "base_prompt_prefix": "dark fantasy, highly detailed, dramatic lighting, painterly",
    "base_negative_prompt": "blurry, low quality, watermark, text, deformed",
    "color_palette": [],
    "art_direction": "Progression fantasy aesthetic with emphasis on power visuals",
    "reference_asset_ids": [],
    "model_preference": None,
    "default_params": {},
}

# Genre → base art style presets
_GENRE_STYLES: dict[str, dict[str, str]] = {
    "progression_fantasy": {
        "base_prompt_prefix": "epic dark fantasy, dramatic lighting, painterly brushstrokes",
        "style_description": "Epic dark fantasy illustration with dramatic lighting",
        "art_direction": (
            "Progression fantasy aesthetic"
            " — epic scale, power visuals, dramatic atmosphere"
        ),
    },
    "cultivation": {
        "base_prompt_prefix": "eastern ink wash, ethereal, flowing energy, muted earth tones",
        "style_description": "Eastern-inspired ink wash illustration with ethereal energy",
        "art_direction": "Cultivation aesthetic — flowing qi, misty mountains, ethereal atmosphere",
    },
    "litrpg": {
        "base_prompt_prefix": "digital art, vibrant neon accents, game-like UI elements",
        "style_description": "Digital art with vibrant neon accents and game aesthetics",
        "art_direction": (
            "LitRPG aesthetic"
            " — digital overlays, vibrant colors, game-inspired visuals"
        ),
    },
}

_GENRE_STYLES_DEFAULT = {
    "base_prompt_prefix": "dark fantasy, highly detailed, dramatic lighting, painterly",
    "style_description": "Dark fantasy illustration, highly detailed",
    "art_direction": "Progression fantasy aesthetic with emphasis on power visuals",
}


async def derive_style_from_world(
    session_factory: async_sessionmaker[AsyncSession],
    novel_id: int,
) -> None:
    """Derive an ArtStyleGuide from generated world data.

    Called after world generation completes. Maps genre to a base art style
    preset and extracts visual motifs from world stages (cosmology, power
    system, geography). Creates or updates the ArtStyleGuide for the novel.
    """
    async with session_factory() as session:
        novel = (await session.execute(
            select(Novel).where(Novel.id == novel_id)
        )).scalar_one()
        genre = novel.genre or "progression_fantasy"

        # Pick genre preset
        preset = _GENRE_STYLES.get(genre, _GENRE_STYLES_DEFAULT)

        # Extract visual motifs from world stages
        motifs: list[str] = []
        color_hints: list[str] = []

        # Cosmology motifs
        cosmo_stmt = select(WorldBuildingStage).where(
            WorldBuildingStage.novel_id == novel_id,
            WorldBuildingStage.stage_name == "cosmology",
            WorldBuildingStage.status == "complete",
        )
        cosmo = (await session.execute(cosmo_stmt)).scalar_one_or_none()
        if cosmo and cosmo.parsed_data:
            tiers = cosmo.parsed_data.get("reality_tiers", [])
            for tier in tiers[:2]:
                if isinstance(tier, dict) and tier.get("description"):
                    motifs.append(tier["description"][:80])
            visual = cosmo.parsed_data.get("visual_manifestation", "")
            if visual:
                motifs.append(visual[:80])

        # Power system motifs
        ps = (await session.execute(
            select(PowerSystem).where(PowerSystem.novel_id == novel_id)
        )).scalar_one_or_none()
        if ps:
            if ps.visual_manifestation:
                motifs.append(ps.visual_manifestation[:80])
            elif ps.description:
                motifs.append(ps.description[:80])

        # Geography motifs — pick most distinctive region
        regions = (await session.execute(
            select(Region).where(Region.novel_id == novel_id).limit(3)
        )).scalars().all()
        for region in regions[:2]:
            if region.visual_description:
                motifs.append(region.visual_description[:60])

        # Build art direction from preset + motifs
        art_direction = preset["art_direction"]
        if motifs:
            art_direction += "\nVisual motifs: " + "; ".join(motifs[:4])

        # Check for existing guide
        existing = (await session.execute(
            select(ArtStyleGuide).where(ArtStyleGuide.novel_id == novel_id)
        )).scalar_one_or_none()

        if existing:
            existing.style_description = preset["style_description"]
            existing.base_prompt_prefix = preset["base_prompt_prefix"]
            existing.art_direction = art_direction
            if color_hints:
                existing.color_palette = color_hints
        else:
            guide = ArtStyleGuide(
                novel_id=novel_id,
                style_description=preset["style_description"],
                style_name="world_derived",
                base_prompt_prefix=preset["base_prompt_prefix"],
                base_negative_prompt=_DEFAULT_STYLE["base_negative_prompt"],
                color_palette=color_hints or [],
                art_direction=art_direction,
            )
            session.add(guide)

        await session.commit()

    logger.info("art_style_derived_from_world", novel_id=novel_id, genre=genre)


class ImagePromptComposer:
    """Composes image generation prompts from narrative elements."""

    def __init__(self, llm: Any, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    async def _load_reference_assets(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        asset_ids: list[int],
    ) -> list[str]:
        """Load file paths for reference assets by their IDs."""
        async with session_factory() as session:
            stmt = select(ArtAsset.file_path).where(
                ArtAsset.id.in_(asset_ids),
                ArtAsset.file_path.isnot(None),
            )
            result = await session.execute(stmt)
            return [row[0] for row in result.all() if row[0]]

    async def _apply_style_overrides(
        self,
        request: ImageRequest,
        style: dict[str, Any],
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ImageRequest:
        """Apply style guide overrides to a composed ImageRequest.

        Merges default_params (width, height, and provider-specific params),
        sets model_preference, and loads reference asset file paths.
        """
        # Merge default_params — width/height override request defaults,
        # everything else goes into extra_params for provider use
        default_params = style.get("default_params") or {}
        if default_params:
            if "width" in default_params:
                request.width = int(default_params["width"])
            if "height" in default_params:
                request.height = int(default_params["height"])
            extra = {
                k: v for k, v in default_params.items()
                if k not in ("width", "height")
            }
            if extra:
                request.extra_params = extra

        # Pass model preference for provider selection / model override
        model_pref = style.get("model_preference")
        if model_pref:
            request.model_preference = model_pref

        # Load reference assets as visual anchors
        ref_ids = style.get("reference_asset_ids") or []
        if ref_ids:
            paths = await self._load_reference_assets(session_factory, ref_ids)
            if paths:
                request.reference_image_paths = paths

        return request

    async def compose_portrait_prompt(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        character_id: int,
    ) -> ImageRequest:
        """Compose a portrait prompt from character description.

        Uses the CHARACTER_PORTRAIT LLM template to generate a rich,
        structured image prompt.  Falls back to simple concatenation if
        the LLM call fails.

        Args:
            session_factory: Async session factory.
            character_id: Character to generate portrait for.

        Returns:
            An ImageRequest ready for the provider.
        """
        async with session_factory() as session:
            stmt = select(Character).where(Character.id == character_id)
            result = await session.execute(stmt)
            character = result.scalar_one()
            novel_id = character.novel_id

        style = await self.get_style_guide(session_factory, novel_id)

        # Build a rich character description for the LLM template
        desc_parts = [f"Name: {character.name}"]
        if getattr(character, "sex", None):
            desc_parts.append(f"Sex: {character.sex}")
        if character.visual_appearance:
            desc_parts.append(f"Appearance: {character.visual_appearance}")
        desc_parts.append(f"Description: {character.description}")
        if character.personality_traits:
            traits = ", ".join(character.personality_traits[:5])
            desc_parts.append(f"Personality: {traits}")
        character_description = "\n".join(desc_parts)

        art_style = style.get("art_direction") or style.get("style_description", "")
        palette = style.get("color_palette", [])
        if palette:
            art_style += f"\nColor palette: {', '.join(palette)}"

        try:
            system, user = CHARACTER_PORTRAIT.render(
                character_description=character_description,
                art_style=art_style,
            )
            response = await self.llm.generate(
                system=system,
                user=user,
                temperature=CHARACTER_PORTRAIT.temperature,
                max_tokens=CHARACTER_PORTRAIT.max_tokens,
                response_format=ImagePromptResult,
                novel_id=novel_id,
                purpose="character_portrait_prompt",
            )
            result = ImagePromptResult.model_validate_json(response.content)
            w, h = _ASPECT_DIMENSIONS.get(result.aspect_ratio, (1024, 1024))
            request = ImageRequest(
                prompt=result.positive_prompt,
                negative_prompt=result.negative_prompt,
                width=w,
                height=h,
                style_tags=result.style_tags,
            )
            return await self._apply_style_overrides(request, style, session_factory)
        except Exception:  # Intentional broad catch: image prompt fallback to template
            logger.warning(
                "llm_portrait_prompt_failed",
                character_id=character_id,
                exc_info=True,
            )

        # ── Fallback: simple string concatenation ──
        prefix = style.get("base_prompt_prefix", "")
        negative = style.get("base_negative_prompt", "")

        prompt_parts = []
        if prefix:
            prompt_parts.append(prefix)
        prompt_parts.append(f"Character portrait of {character.name}")
        if character.visual_appearance:
            prompt_parts.append(character.visual_appearance)
        prompt_parts.append(character.description)
        if character.personality_traits:
            traits = ", ".join(character.personality_traits[:3])
            prompt_parts.append(f"personality: {traits}")
        if palette:
            prompt_parts.append(f"color palette: {', '.join(palette)}")

        request = ImageRequest(
            prompt=", ".join(prompt_parts),
            negative_prompt=negative,
            width=1024,
            height=1024,
            style_tags=palette or None,
        )
        return await self._apply_style_overrides(request, style, session_factory)

    async def compose_map_prompt(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        novel_id: int,
        region_ids: list[int] | None = None,
    ) -> ImageRequest:
        """Compose a world map prompt from geography data.

        Uses the MAP_PROMPT LLM template to generate a rich, structured
        image prompt.  Falls back to simple concatenation on failure.

        Args:
            session_factory: Async session factory.
            novel_id: Novel whose map to generate.
            region_ids: Optional specific regions to include. If None, includes all.

        Returns:
            An ImageRequest for map generation.
        """
        async with session_factory() as session:
            if region_ids:
                stmt = select(Region).where(Region.id.in_(region_ids))
            else:
                stmt = select(Region).where(Region.novel_id == novel_id)
            result = await session.execute(stmt)
            regions = result.scalars().all()

        style = await self.get_style_guide(session_factory, novel_id)

        # Build detailed region descriptions for the LLM template
        region_descriptions = []
        for region in regions:
            desc = f"{region.name}"
            if region.geography_type:
                desc += f" ({region.geography_type})"
            if region.visual_description:
                desc += f": {region.visual_description[:150]}"
            else:
                desc += f": {region.description[:100]}"
            region_descriptions.append(desc)

        region_text = (
            "\n".join(f"- {d}" for d in region_descriptions)
            if region_descriptions
            else "Unknown lands"
        )

        # Build a geography overview from all region descriptions
        geography_parts = []
        for region in regions:
            if region.visual_description:
                geography_parts.append(region.visual_description[:200])
            elif region.description:
                geography_parts.append(region.description[:150])
        geography_description = (
            " ".join(geography_parts)
            if geography_parts
            else "A fantastical world with diverse biomes"
        )

        art_style = style.get("art_direction") or style.get("style_description", "")
        palette = style.get("color_palette", [])
        if palette:
            art_style += f"\nColor palette: {', '.join(palette)}"

        try:
            system, user = MAP_PROMPT.render(
                geography_description=geography_description,
                regions=region_text,
                art_style=art_style,
            )
            response = await self.llm.generate(
                system=system,
                user=user,
                temperature=MAP_PROMPT.temperature,
                max_tokens=MAP_PROMPT.max_tokens,
                response_format=ImagePromptResult,
                novel_id=novel_id,
                purpose="map_prompt",
            )
            result = ImagePromptResult.model_validate_json(response.content)
            w, h = _ASPECT_DIMENSIONS.get(result.aspect_ratio, (1024, 768))
            request = ImageRequest(
                prompt=result.positive_prompt,
                negative_prompt=result.negative_prompt,
                width=w,
                height=h,
                style_tags=result.style_tags,
            )
            return await self._apply_style_overrides(request, style, session_factory)
        except Exception:  # Intentional broad catch: image prompt fallback to template
            logger.warning(
                "llm_map_prompt_failed",
                novel_id=novel_id,
                exc_info=True,
            )

        # ── Fallback: simple string concatenation ──
        prefix = style.get("base_prompt_prefix", "")
        negative = style.get("base_negative_prompt", "")

        fallback_region_text = "; ".join(
            f"{d}" for d in (
                f"{r.name} ({r.geography_type})" if r.geography_type else r.name
                for r in regions
            )
        ) if regions else "Unknown lands"

        prompt_parts = []
        if prefix:
            prompt_parts.append(prefix)
        prompt_parts.append("Fantasy world map, stylized cartography")
        prompt_parts.append(f"Regions: {fallback_region_text}")
        if palette:
            prompt_parts.append(f"color palette: {', '.join(palette)}")

        request = ImageRequest(
            prompt=", ".join(prompt_parts),
            negative_prompt=negative,
            width=1024,
            height=768,
            style_tags=palette or None,
        )
        return await self._apply_style_overrides(request, style, session_factory)

    async def compose_scene_prompt(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        novel_id: int,
        scene_description: str,
        characters: str = "",
        mood: str = "",
    ) -> ImageRequest:
        """Compose a scene illustration prompt from chapter scene description.

        Uses the SCENE_ILLUSTRATION LLM template to generate a rich,
        structured image prompt.  Falls back to simple concatenation on failure.

        Args:
            session_factory: Async session factory.
            novel_id: Novel context for style consistency.
            scene_description: Text description of the scene.
            characters: Optional description of characters present.
            mood: Optional mood/tone descriptor.

        Returns:
            An ImageRequest for scene illustration.
        """
        style = await self.get_style_guide(session_factory, novel_id)
        art_style = style.get("art_direction") or style.get("style_description", "")
        palette = style.get("color_palette", [])
        if palette:
            art_style += f"\nColor palette: {', '.join(palette)}"

        try:
            system, user = SCENE_ILLUSTRATION.render(
                scene_description=scene_description,
                characters=characters or "Not specified",
                mood=mood or "Not specified",
                art_style=art_style,
            )
            response = await self.llm.generate(
                system=system,
                user=user,
                temperature=SCENE_ILLUSTRATION.temperature,
                max_tokens=SCENE_ILLUSTRATION.max_tokens,
                response_format=ImagePromptResult,
                novel_id=novel_id,
                purpose="scene_illustration_prompt",
            )
            result = ImagePromptResult.model_validate_json(response.content)
            w, h = _ASPECT_DIMENSIONS.get(result.aspect_ratio, (1024, 768))
            request = ImageRequest(
                prompt=result.positive_prompt,
                negative_prompt=result.negative_prompt,
                width=w,
                height=h,
                style_tags=result.style_tags,
            )
            return await self._apply_style_overrides(request, style, session_factory)
        except Exception:  # Intentional broad catch: image prompt fallback to template
            logger.warning(
                "llm_scene_prompt_failed",
                novel_id=novel_id,
                exc_info=True,
            )

        # ── Fallback: simple string concatenation ──
        prefix = style.get("base_prompt_prefix", "")
        negative = style.get("base_negative_prompt", "")

        prompt_parts = []
        if prefix:
            prompt_parts.append(prefix)
        prompt_parts.append("Scene illustration")
        prompt_parts.append(scene_description)
        if palette:
            prompt_parts.append(f"color palette: {', '.join(palette)}")

        request = ImageRequest(
            prompt=", ".join(prompt_parts),
            negative_prompt=negative,
            width=1024,
            height=768,
            style_tags=palette or None,
        )
        return await self._apply_style_overrides(request, style, session_factory)

    async def compose_cover_prompt(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        novel_id: int,
    ) -> ImageRequest:
        """Compose a book cover art prompt from novel world data.

        Uses the COVER_ART LLM template to generate a dramatic, evocative
        cover image prompt. Falls back to simple concatenation on failure.

        Composition: protagonist in foreground, most distinctive world element
        in background, 2:3 portrait orientation, upper portion left clear for
        title overlay.

        Args:
            session_factory: Async session factory.
            novel_id: Novel to generate cover for.

        Returns:
            An ImageRequest for cover art generation (2:3 portrait).
        """
        async with session_factory() as session:
            # Load novel
            novel = (await session.execute(
                select(Novel).where(Novel.id == novel_id)
            )).scalar_one()
            genre = novel.genre or "progression_fantasy"

            # Load cosmology/world summary from world building stages
            cosmo_stmt = select(WorldBuildingStage).where(
                WorldBuildingStage.novel_id == novel_id,
                WorldBuildingStage.stage_name == "cosmology",
                WorldBuildingStage.status == "complete",
            )
            cosmo = (await session.execute(cosmo_stmt)).scalar_one_or_none()
            world_summary = ""
            if cosmo and cosmo.parsed_data:
                tiers = cosmo.parsed_data.get("reality_tiers", [])
                if tiers and isinstance(tiers[0], dict):
                    world_summary = tiers[0].get("description", "")
            if not world_summary:
                world_summary = novel.description or "A fantastical world of mystery and power"

            # Extract the most distinctive world element for background
            distinctive_element = ""
            # Try geography first — landmarks are visually striking
            geo_stmt = select(WorldBuildingStage).where(
                WorldBuildingStage.novel_id == novel_id,
                WorldBuildingStage.stage_name == "geography",
                WorldBuildingStage.status == "complete",
            )
            geo = (await session.execute(geo_stmt)).scalar_one_or_none()
            if geo and geo.parsed_data:
                landmarks = geo.parsed_data.get("notable_landmarks", [])
                if landmarks and isinstance(landmarks[0], dict):
                    distinctive_element = landmarks[0].get("description", "")[:150]
                elif landmarks and isinstance(landmarks[0], str):
                    distinctive_element = landmarks[0][:150]
            # Fallback to cosmology visual manifestation
            if not distinctive_element and cosmo and cosmo.parsed_data:
                distinctive_element = cosmo.parsed_data.get("visual_manifestation", "")[:150]
            # Fallback to most distinctive region
            if not distinctive_element:
                region = (await session.execute(
                    select(Region).where(Region.novel_id == novel_id).limit(1)
                )).scalar_one_or_none()
                if region and region.visual_description:
                    distinctive_element = region.visual_description[:150]

            # Load protagonist — prefer full visual from world stage parsed_data
            protag_desc = "Unknown protagonist"
            protag_stmt = select(WorldBuildingStage).where(
                WorldBuildingStage.novel_id == novel_id,
                WorldBuildingStage.stage_name == "protagonist",
                WorldBuildingStage.status == "complete",
            )
            protag_stage = (await session.execute(protag_stmt)).scalar_one_or_none()
            if protag_stage and protag_stage.parsed_data:
                pd = protag_stage.parsed_data
                parts = []
                if pd.get("name"):
                    parts.append(pd["name"])
                if pd.get("visual_description"):
                    parts.append(pd["visual_description"])
                elif pd.get("appearance"):
                    parts.append(pd["appearance"])
                if pd.get("distinctive_features"):
                    feats = pd["distinctive_features"]
                    if isinstance(feats, list):
                        parts.append("Distinctive: " + ", ".join(feats[:3]))
                    elif isinstance(feats, str):
                        parts.append("Distinctive: " + feats[:100])
                if parts:
                    protag_desc = ". ".join(p for p in parts if p)

            # Fallback to Character table
            if protag_desc == "Unknown protagonist":
                protag_char = (await session.execute(
                    select(Character).where(
                        Character.novel_id == novel_id,
                        Character.role == "protagonist",
                    )
                )).scalar_one_or_none()
                if protag_char:
                    parts = [protag_char.name]
                    if protag_char.visual_appearance:
                        parts.append(protag_char.visual_appearance)
                    elif protag_char.description:
                        parts.append(protag_char.description[:200])
                    protag_desc = ". ".join(p for p in parts if p)

            # Load power system
            ps_stmt = select(PowerSystem).where(PowerSystem.novel_id == novel_id)
            ps = (await session.execute(ps_stmt)).scalar_one_or_none()
            power_text = ""
            if ps:
                power_text = ps.system_name or ""
                if ps.visual_manifestation:
                    power_text += f" — {ps.visual_manifestation[:100]}"

        style = await self.get_style_guide(session_factory, novel_id)
        art_style = style.get("art_direction") or style.get("style_description", "")
        palette = style.get("color_palette", [])
        if palette:
            art_style += f"\nColor palette: {', '.join(palette)}"

        # Enrich world summary with distinctive element
        enriched_summary = world_summary
        if distinctive_element:
            enriched_summary += f"\n\nMost distinctive visual element: {distinctive_element}"

        try:
            system, user = COVER_ART.render(
                genre=genre.replace("_", " ").title(),
                world_summary=enriched_summary,
                protagonist_description=protag_desc,
                power_system=power_text or "Unknown power system",
                art_style=art_style,
            )
            response = await self.llm.generate(
                system=system,
                user=user,
                temperature=COVER_ART.temperature,
                max_tokens=COVER_ART.max_tokens,
                response_format=ImagePromptResult,
                novel_id=novel_id,
                purpose="cover_art_prompt",
            )
            result = ImagePromptResult.model_validate_json(response.content)
            # Force 2:3 for cover art regardless of LLM response
            request = ImageRequest(
                prompt=result.positive_prompt,
                negative_prompt=result.negative_prompt,
                width=683,
                height=1024,
                style_tags=result.style_tags,
            )
            return await self._apply_style_overrides(request, style, session_factory)
        except Exception:  # Intentional broad catch: image prompt fallback to template
            logger.warning(
                "llm_cover_prompt_failed",
                novel_id=novel_id,
                exc_info=True,
            )

        # ── Fallback: simple string concatenation ──
        prefix = style.get("base_prompt_prefix", "")
        negative = style.get("base_negative_prompt", "")
        if negative:
            negative += ", text, title, words, letters, watermark, signature"
        else:
            negative = "text, title, words, letters, watermark, signature, blurry, low quality"

        prompt_parts = []
        if prefix:
            prompt_parts.append(prefix)
        prompt_parts.append(
            "Book cover art, dramatic fantasy illustration,"
            " 2:3 portrait composition"
        )
        prompt_parts.append(f"Genre: {genre.replace('_', ' ')}")
        prompt_parts.append("Protagonist in foreground, world landmark in background")
        prompt_parts.append(f"Protagonist: {protag_desc[:200]}")
        if distinctive_element:
            prompt_parts.append(f"Background: {distinctive_element}")
        elif world_summary:
            prompt_parts.append(world_summary[:200])
        prompt_parts.append("Leave upper portion clear for title overlay")
        prompt_parts.append("dramatic lighting, atmospheric, epic scale")
        if palette:
            prompt_parts.append(f"color palette: {', '.join(palette)}")

        request = ImageRequest(
            prompt=", ".join(prompt_parts),
            negative_prompt=negative,
            width=683,
            height=1024,
            style_tags=palette or None,
        )
        return await self._apply_style_overrides(request, style, session_factory)

    async def compose_regeneration_prompt(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        asset_id: int,
        feedback: str,
    ) -> ImageRequest:
        """Compose a revised image prompt from author feedback on an existing asset.

        Loads original context based on asset type, calls IMAGE_REGENERATION
        template, and returns an ImageRequest. Falls back to appending feedback
        to the original prompt on LLM failure.
        """
        async with session_factory() as session:
            asset = await session.get(ArtAsset, asset_id)
            if asset is None:
                raise ValueError(f"ArtAsset {asset_id} not found")

            novel_id = asset.novel_id
            asset_type = asset.asset_type
            entity_id = asset.entity_id
            original_prompt = asset.prompt_used or ""

            # Build original context based on asset type
            original_context = ""
            if asset_type == "portrait" and entity_id:
                char = await session.get(Character, entity_id)
                if char:
                    parts = [f"Name: {char.name}"]
                    if getattr(char, "sex", None):
                        parts.append(f"Sex: {char.sex}")
                    if char.visual_appearance:
                        parts.append(f"Appearance: {char.visual_appearance}")
                    parts.append(f"Description: {char.description}")
                    original_context = "\n".join(parts)
            elif asset_type == "cover":
                novel = await session.get(Novel, novel_id)
                original_context = f"Novel: {novel.title}\n" if novel else ""
                if novel and novel.description:
                    original_context += f"Description: {novel.description[:300]}"
            elif asset_type == "world_map":
                regions = (await session.execute(
                    select(Region).where(Region.novel_id == novel_id).limit(5)
                )).scalars().all()
                if regions:
                    original_context = "Regions:\n" + "\n".join(
                        f"- {r.name}: {(r.visual_description or r.description or '')[:100]}"
                        for r in regions
                    )
            else:
                original_context = original_prompt[:300]

        # Determine correct aspect ratio and dimensions for asset type
        aspect_map = {
            "portrait": ("1:1", 1024, 1024),
            "cover": ("2:3", 683, 1024),
            "world_map": ("4:3", 1024, 768),
            "scene": ("16:9", 1024, 576),
        }
        default_ar, default_w, default_h = aspect_map.get(
            asset_type, ("1:1", 1024, 1024),
        )

        style = await self.get_style_guide(session_factory, novel_id)
        art_style = style.get("art_direction") or style.get("style_description", "")
        palette = style.get("color_palette", [])
        if palette:
            art_style += f"\nColor palette: {', '.join(palette)}"

        try:
            system, user = IMAGE_REGENERATION.render(
                asset_type=asset_type.replace("_", " "),
                original_context=original_context or "Not available",
                original_prompt=original_prompt or "Not available",
                feedback=feedback,
                art_style=art_style,
            )
            response = await self.llm.generate(
                system=system,
                user=user,
                temperature=IMAGE_REGENERATION.temperature,
                max_tokens=IMAGE_REGENERATION.max_tokens,
                response_format=ImagePromptResult,
                novel_id=novel_id,
                purpose="image_regeneration_prompt",
            )
            result = ImagePromptResult.model_validate_json(response.content)
            w, h = _ASPECT_DIMENSIONS.get(result.aspect_ratio, (default_w, default_h))
            request = ImageRequest(
                prompt=result.positive_prompt,
                negative_prompt=result.negative_prompt,
                width=w,
                height=h,
                style_tags=result.style_tags,
            )
            return await self._apply_style_overrides(request, style, session_factory)
        except Exception:
            logger.warning(
                "llm_regeneration_prompt_failed",
                asset_id=asset_id,
                exc_info=True,
            )

        # Fallback: append feedback to original prompt
        prefix = style.get("base_prompt_prefix", "")
        negative = style.get("base_negative_prompt", "")
        fallback_prompt = original_prompt
        if prefix and not fallback_prompt.startswith(prefix):
            fallback_prompt = f"{prefix}, {fallback_prompt}"
        fallback_prompt += f". Changes: {feedback}"

        request = ImageRequest(
            prompt=fallback_prompt,
            negative_prompt=negative,
            width=default_w,
            height=default_h,
        )
        return await self._apply_style_overrides(request, style, session_factory)

    async def get_style_guide(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        novel_id: int,
    ) -> dict[str, Any]:
        """Load or create the art style guide for consistent visual output.

        If no style guide exists for the novel, creates a default one.

        Args:
            session_factory: Async session factory.
            novel_id: Novel to get style guide for.

        Returns:
            Dict with style guide fields.
        """
        async with session_factory() as session:
            stmt = select(ArtStyleGuide).where(
                ArtStyleGuide.novel_id == novel_id
            )
            result = await session.execute(stmt)
            guide = result.scalar_one_or_none()

            if guide is not None:
                return {
                    "style_description": guide.style_description,
                    "style_name": guide.style_name or "default",
                    "base_prompt_prefix": guide.base_prompt_prefix or "",
                    "base_negative_prompt": guide.base_negative_prompt or "",
                    "color_palette": guide.color_palette or [],
                    "art_direction": guide.art_direction or "",
                    "reference_asset_ids": guide.reference_asset_ids or [],
                    "model_preference": guide.model_preference or None,
                    "default_params": guide.default_params or {},
                }

            # Create default style guide
            default_guide = ArtStyleGuide(
                novel_id=novel_id,
                style_description=_DEFAULT_STYLE["style_description"],
                style_name=_DEFAULT_STYLE["style_name"],
                base_prompt_prefix=_DEFAULT_STYLE["base_prompt_prefix"],
                base_negative_prompt=_DEFAULT_STYLE["base_negative_prompt"],
                color_palette=_DEFAULT_STYLE["color_palette"],
                art_direction=_DEFAULT_STYLE["art_direction"],
            )
            session.add(default_guide)
            await session.commit()

            logger.info(
                "default_style_guide_created",
                novel_id=novel_id,
            )

            return dict(_DEFAULT_STYLE)
