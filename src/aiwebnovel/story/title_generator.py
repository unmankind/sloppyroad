"""Title and synopsis generation after world building.

Extracted from pipeline.py to reduce module size.
"""

from __future__ import annotations

from typing import Any

import litellm.exceptions
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import Novel, NovelSettings
from aiwebnovel.llm.prompts import NOVEL_SYNOPSIS, NOVEL_TITLE
from aiwebnovel.llm.provider import LLMProvider

logger = structlog.get_logger(__name__)


class TitleGenerator:
    """Generates novel title and synopsis from world data."""

    def __init__(self, llm: LLMProvider, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    def build_world_summary(self, stage_data: dict[str, Any]) -> str:
        """Build a compact world summary from stage data for title/synopsis prompts."""
        parts: list[str] = []

        cosmo = stage_data.get("cosmology", {})
        if cosmo.get("cosmic_laws"):
            laws = [
                law.get("description", law)
                if isinstance(law, dict) else str(law)
                for law in cosmo["cosmic_laws"][:3]
            ]
            parts.append(f"Cosmic laws: {'; '.join(laws)}")
        if cosmo.get("energy_types"):
            names = [e.get("name", str(e)) if isinstance(e, dict) else str(e)
                     for e in cosmo["energy_types"][:4]]
            parts.append(f"Energy types: {', '.join(names)}")

        ps = stage_data.get("power_system", {})
        if ps.get("system_name"):
            parts.append(f"Power system: {ps['system_name']}")
        if ps.get("core_mechanic"):
            parts.append(f"Core mechanic: {ps['core_mechanic'][:200]}")

        geo = stage_data.get("geography", {})
        if geo.get("regions"):
            names = [r.get("name", str(r)) if isinstance(r, dict) else str(r)
                     for r in geo["regions"][:4]]
            parts.append(f"Regions: {', '.join(names)}")

        cs = stage_data.get("current_state", {})
        if cs.get("active_conflicts"):
            conflicts = [c.get("name", str(c)) if isinstance(c, dict) else str(c)
                         for c in cs["active_conflicts"][:3]]
            parts.append(f"Active conflicts: {', '.join(conflicts)}")

        return "\n".join(parts)

    async def generate_title_and_synopsis(
        self,
        session: AsyncSession,
        novel_id: int,
        user_id: int,
        stage_data: dict[str, Any],
        seeds: list[Any] | None = None,
        anti_rep: str = "",
    ) -> None:
        """Generate novel title (if placeholder) and synopsis after world gen."""
        logger.info(
            "title_synopsis_generation_started",
            novel_id=novel_id,
            stage_data_keys=list(stage_data.keys()),
        )

        novel = (await session.execute(
            select(Novel).where(Novel.id == novel_id)
        )).scalar_one_or_none()
        if novel is None:
            logger.warning("title_synopsis_novel_not_found", novel_id=novel_id)
            return

        world_summary = self.build_world_summary(stage_data)
        model = self.settings.litellm_world_gen_model

        logger.info(
            "title_synopsis_context",
            novel_id=novel_id,
            current_title=novel.title,
            has_description=bool(novel.description),
            world_summary_length=len(world_summary),
            model=model,
        )

        # --- Title generation ---
        # Build creative identity from seeds for title context
        creative_lines: list[str] = []
        if seeds:
            for seed in seeds:
                creative_lines.append(f"- {seed.text[:120]}")
        creative_identity = "\n".join(creative_lines) if creative_lines else "N/A"

        # Build title constraints from anti-repetition
        title_constraints = ""
        if anti_rep:
            title_constraints = (
                "TITLE AVOIDANCE (CRITICAL):\n" + anti_rep
            )

        placeholder_titles = {"untitled novel", "untitled", "new novel", "untitled world", ""}
        if novel.title.strip().lower() in placeholder_titles:
            try:
                system, user_prompt = NOVEL_TITLE.render(
                    world_summary=world_summary,
                    creative_identity=creative_identity,
                    title_constraints=title_constraints,
                )
                response = await self.llm.generate(
                    system=system,
                    user=user_prompt,
                    model=model,
                    temperature=NOVEL_TITLE.temperature,
                    max_tokens=NOVEL_TITLE.max_tokens,
                    novel_id=novel_id,
                    user_id=user_id,
                    purpose="novel_title",
                )
                new_title = response.content.strip().strip('"\'')

                # Validate: check for overused words from existing titles
                if new_title:
                    existing_stmt = (
                        select(Novel.title)
                        .where(Novel.id != novel_id, Novel.title.isnot(None))
                    )
                    existing = (await session.execute(existing_stmt)).scalars().all()
                    existing_words = set()
                    for t in existing:
                        for w in (t or "").lower().split():
                            if len(w) >= 4:
                                existing_words.add(w)

                    new_words = {
                        w for w in new_title.lower().split() if len(w) >= 4
                    }
                    overlap = new_words & existing_words
                    if overlap:
                        # Retry once with explicit avoidance
                        avoid_csv = ", ".join(f'"{w}"' for w in overlap)
                        retry_constraints = (
                            f"{title_constraints}\n"
                            f"ABSOLUTELY DO NOT use these words: {avoid_csv}"
                        )
                        system2, user2 = NOVEL_TITLE.render(
                            world_summary=world_summary,
                            creative_identity=creative_identity,
                            title_constraints=retry_constraints,
                        )
                        retry = await self.llm.generate(
                            system=system2, user=user2,
                            model=model,
                            temperature=1.0,
                            max_tokens=NOVEL_TITLE.max_tokens,
                            novel_id=novel_id, user_id=user_id,
                            purpose="novel_title_retry",
                        )
                        retry_title = retry.content.strip().strip('"\'')
                        if retry_title:
                            new_title = retry_title
                            logger.info(
                                "novel_title_retried",
                                novel_id=novel_id,
                                original_overlap=list(overlap),
                                new_title=retry_title,
                            )

                if new_title:
                    novel.title = new_title
                    await session.commit()
                    logger.info(
                        "novel_title_generated",
                        novel_id=novel_id,
                        title=new_title,
                    )
            except (
                RuntimeError,
                litellm.exceptions.APIError,
                litellm.exceptions.Timeout,
                litellm.exceptions.APIConnectionError,
            ) as exc:
                logger.warning(
                    "novel_title_generation_failed",
                    novel_id=novel_id,
                    error=str(exc),
                )
        else:
            logger.info(
                "novel_title_skipped_not_placeholder",
                novel_id=novel_id,
                current_title=novel.title,
            )

        # --- Synopsis generation ---
        protagonist = stage_data.get("protagonist", {})
        protagonist_summary = ""
        if protagonist.get("name"):
            protagonist_summary = f"{protagonist['name']}"
            if protagonist.get("background"):
                protagonist_summary += f": {protagonist['background'][:300]}"
            if protagonist.get("motivation"):
                mot = protagonist["motivation"]
                if isinstance(mot, dict):
                    protagonist_summary += f"\nMotivation: {mot.get('surface_motivation', '')}"
                else:
                    protagonist_summary += f"\nMotivation: {str(mot)[:200]}"

        # Condensed world + conflict context (not fed as separate blocks)
        world_ctx_parts: list[str] = []
        if world_summary:
            world_ctx_parts.append(world_summary)
        cs = stage_data.get("current_state", {})
        if cs.get("active_conflicts"):
            for c in cs["active_conflicts"][:2]:
                if isinstance(c, dict):
                    world_ctx_parts.append(c.get("name", ""))

        # Include author direction so synopsis reflects custom conventions
        custom_dir = (await session.execute(
            select(NovelSettings.custom_genre_conventions)
            .where(NovelSettings.novel_id == novel_id)
        )).scalar_one_or_none()
        if custom_dir and isinstance(custom_dir, str) and custom_dir.strip():
            world_ctx_parts.append(
                f"AUTHOR DIRECTION (must be reflected): {custom_dir.strip()}"
            )

        world_context = "\n".join(world_ctx_parts)

        try:
            system, user_prompt = NOVEL_SYNOPSIS.render(
                protagonist_summary=protagonist_summary,
                world_context=world_context,
            )
            response = await self.llm.generate(
                system=system,
                user=user_prompt,
                model=model,
                temperature=NOVEL_SYNOPSIS.temperature,
                max_tokens=NOVEL_SYNOPSIS.max_tokens,
                novel_id=novel_id,
                user_id=user_id,
                purpose="novel_synopsis",
            )
            synopsis = response.content.strip()
            if synopsis:
                novel.description = synopsis
                await session.commit()
                logger.info(
                    "novel_synopsis_generated",
                    novel_id=novel_id,
                    length=len(synopsis),
                )
        except (
            RuntimeError,
            litellm.exceptions.APIError,
            litellm.exceptions.Timeout,
            litellm.exceptions.APIConnectionError,
        ) as exc:
            logger.warning(
                "novel_synopsis_generation_failed",
                novel_id=novel_id,
                error=str(exc),
            )

        logger.info(
            "title_synopsis_generation_complete",
            novel_id=novel_id,
            title=novel.title,
            has_synopsis=bool(novel.description),
        )
