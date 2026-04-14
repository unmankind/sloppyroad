"""Chapter generation via LLM.

Thin wrapper that takes assembled context, formats the prompt template,
calls the LLM, and returns raw chapter text. Supports streaming.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog

from aiwebnovel.config import Settings
from aiwebnovel.llm.prompts import CHAPTER_GENERATION
from aiwebnovel.llm.provider import LLMProvider
from aiwebnovel.story.context import AssembledContext

if TYPE_CHECKING:
    from aiwebnovel.story.gen_context import GenerationContext

logger = structlog.get_logger(__name__)


class ChapterGenerator:
    """Generates chapter text from assembled context via LLM."""

    def __init__(self, llm: LLMProvider, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    def _build_prompt_context(
        self,
        context: AssembledContext,
        chapter_plan: Any,
        chapter_number: int,
        novel_settings: Any | None = None,
        genre_label: str = "progression fantasy",
        genre_slug: str = "progression_fantasy",
    ) -> dict[str, str]:
        """Build template context dict from AssembledContext and chapter plan."""
        sections = context.sections

        # World building from the 8-stage pipeline is the PRIMARY world source.
        # The old "world_state" (region list) is supplementary.
        world_building = sections.get("world_building", _empty_section()).content
        world_state = sections.get("world_state", _empty_section()).content
        # Combine: world building first, then any additional revealed regions
        if world_building and world_state:
            full_world = world_building + "\n\n" + world_state
        else:
            full_world = world_building or world_state

        return {
            "genre_label": genre_label,
            "chapter_number": str(chapter_number),
            "chapter_title": getattr(chapter_plan, "title", None) or f"Chapter {chapter_number}",
            "world_context": full_world,
            "power_context": sections.get("power_system", _empty_section()).content,
            "escalation_context": sections.get("escalation", _empty_section()).content,
            "enhanced_recap": sections.get("enhanced_recap", _empty_section()).content,
            "story_bible_entries": sections.get("story_bible", _empty_section()).content,
            "chapter_plan": sections.get("chapter_plan", _empty_section()).content,
            "perspective_filter": "",
            "reader_influence": sections.get("reader_influence", _empty_section()).content,
            "protagonist_context": sections.get("protagonist", _empty_section()).content,
            "cast_context": sections.get("cast", _empty_section()).content,
            "chekhov_directives": sections.get("chekhov", _empty_section()).content,
            "name_exclusions": sections.get("name_exclusions", _empty_section()).content,
            "diversity_seeds": sections.get("diversity_seeds", _empty_section()).content,
            "voice_style_directives": "",
            "target_word_count": str(
                novel_settings.target_chapter_length
                if novel_settings and hasattr(novel_settings, "target_chapter_length")
                else self.settings.max_chapter_tokens
            ),
            "target_tension": str(
                getattr(chapter_plan, "target_tension", None) or "0.5"
            ),
            "content_rating_directive": self._content_rating_directive(
                novel_settings, genre=genre_slug,
            ),
        }

    @staticmethod
    def _content_rating_directive(
        novel_settings: Any | None,
        genre: str = "progression_fantasy",
    ) -> str:
        """Build content rating directive for the LLM.

        Romantasy gets genre-specific directives that explicitly address
        sexual content at each rating level.
        """
        if not novel_settings or not hasattr(novel_settings, "content_rating"):
            return ""
        rating = novel_settings.content_rating

        # Genre-specific overrides for romantasy
        if genre == "romantasy":
            romantasy_directives = {
                "everyone": (
                    "CONTENT RATING: Everyone — No graphic violence, no "
                    "romance beyond friendship, no dark themes. Keep it "
                    "suitable for all ages."
                ),
                "teen": (
                    "CONTENT RATING: Teen — Romantic tension and longing "
                    "are encouraged. Kissing and emotional intimacy are "
                    "fine. Fade to black before anything physical beyond "
                    "that. Mild peril and dark themes acceptable."
                ),
                "mature": (
                    "CONTENT RATING: Mature — Sexual content is permitted. "
                    "Intimate scenes can be depicted with sensory detail — "
                    "bodies, sensation, desire. Keep it tasteful but do not "
                    "fade to black. Limit to 1-2 intimate scenes per "
                    "chapter. Graphic violence, dark themes, and complex "
                    "moral situations are acceptable."
                ),
                "adult": (
                    "CONTENT RATING: Adult — Frequent, graphic sexual "
                    "content is expected and encouraged. Depictions of "
                    "kink, BDSM, and fetish content are fair game. Write "
                    "sex scenes with the same craft as any other scene — "
                    "sensory, emotionally grounded, character-revealing. "
                    "Explicit consent must be present or clearly implied. "
                    "Do NOT depict rape or sexual assault graphically. "
                    "Violence, dark themes, and mature situations are all "
                    "acceptable."
                ),
            }
            return romantasy_directives.get(rating, "")

        directives = {
            "everyone": (
                "CONTENT RATING: Everyone — No graphic violence, no romance beyond "
                "friendship, no dark themes. Keep it suitable for all ages."
            ),
            "teen": (
                "CONTENT RATING: Teen — Moderate action violence is fine. Romance "
                "limited to emotional tension, no explicit content. Mild peril and "
                "dark themes acceptable."
            ),
            "mature": (
                "CONTENT RATING: Mature — Graphic violence, dark themes, and "
                "complex moral situations are acceptable. Romance can include "
                "tension and implied intimacy but not explicit scenes."
            ),
            "adult": (
                "CONTENT RATING: Adult — Unrestricted content. Violence, dark "
                "themes, and mature situations are all acceptable."
            ),
        }
        return directives.get(rating, "")

    async def generate(
        self,
        context: AssembledContext,
        chapter_plan: Any,
        novel_id: int,
        user_id: int,
        chapter_number: int = 1,
        retry_guidance: str | None = None,
        gen_ctx: GenerationContext | None = None,
        novel_settings: Any | None = None,
        genre_label: str = "progression fantasy",
        genre_slug: str = "progression_fantasy",
    ) -> str:
        """Generate chapter text via LLM. Returns the raw prose."""
        prompt_ctx = self._build_prompt_context(
            context, chapter_plan, chapter_number, novel_settings,
            genre_label=genre_label,
            genre_slug=genre_slug,
        )

        system, user = CHAPTER_GENERATION.render(**prompt_ctx)

        if retry_guidance:
            user += f"\n\n=== REVISION GUIDANCE ===\n{retry_guidance}"

        # Use gen_ctx for model/key if available
        llm_kwargs: dict[str, Any] = {}
        if gen_ctx is not None:
            llm_kwargs["model"] = gen_ctx.model
            llm_kwargs["api_key"] = gen_ctx.api_key
            llm_kwargs["is_platform_key"] = gen_ctx.is_platform_key

        # Use novel's configured temperature if set, else prompt default
        temperature = CHAPTER_GENERATION.temperature
        if (
            novel_settings
            and hasattr(novel_settings, "default_temperature")
            and novel_settings.default_temperature is not None
        ):
            temperature = novel_settings.default_temperature

        response = await self.llm.generate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=CHAPTER_GENERATION.max_tokens,
            novel_id=novel_id,
            user_id=user_id,
            purpose="chapter_generation",
            **llm_kwargs,
        )

        logger.info(
            "chapter_generated",
            novel_id=novel_id,
            chapter_number=chapter_number,
            tokens=response.prompt_tokens + response.completion_tokens,
            cost_cents=response.cost_cents,
        )

        return response.content

    async def generate_stream(
        self,
        context: AssembledContext,
        chapter_plan: Any,
        novel_id: int,
        user_id: int,
        chapter_number: int = 1,
        publish_callback: Callable[[str], Any] | None = None,
        novel_settings: Any | None = None,
        genre_label: str = "progression fantasy",
        genre_slug: str = "progression_fantasy",
    ) -> str:
        """Stream chapter generation, calling publish_callback with each token."""
        prompt_ctx = self._build_prompt_context(
            context, chapter_plan, chapter_number, novel_settings,
            genre_label=genre_label,
            genre_slug=genre_slug,
        )

        system, user = CHAPTER_GENERATION.render(**prompt_ctx)

        collected: list[str] = []
        async for token in self.llm.generate_stream(
            system=system,
            user=user,
            temperature=CHAPTER_GENERATION.temperature,
            max_tokens=CHAPTER_GENERATION.max_tokens,
            novel_id=novel_id,
            user_id=user_id,
            purpose="chapter_generation_stream",
        ):
            collected.append(token)
            if publish_callback:
                await publish_callback(token)

        full_text = "".join(collected)

        logger.info(
            "chapter_streamed",
            novel_id=novel_id,
            chapter_number=chapter_number,
            word_count=len(full_text.split()),
        )

        return full_text


class _EmptySection:
    """Placeholder for missing context sections."""

    content: str = ""


def _empty_section() -> _EmptySection:
    return _EmptySection()
