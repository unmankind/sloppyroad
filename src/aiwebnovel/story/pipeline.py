"""Story pipeline orchestrator.

Coordinates world generation, chapter generation lifecycle, and
regeneration. Uses Redis lock to prevent concurrent generation.

This module is the public API surface. It delegates to focused sub-modules:
- world_generator.py — wave execution, stage storage, world context assembly
- chapter_pipeline.py — planning, context, generation, analysis, saving
- pipeline_jobs.py — job creation, heartbeat, completion, Redis locking
- character_seeder.py — character row seeding from world data
- title_generator.py — title and synopsis generation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.llm.provider import LLMProvider
from aiwebnovel.story.analyzer import AnalysisResult
from aiwebnovel.story.chapter_pipeline import ChapterPipelineRunner
from aiwebnovel.story.character_seeder import CharacterSeeder
from aiwebnovel.story.context import ContextAssembler
from aiwebnovel.story.extractor import DataExtractor
from aiwebnovel.story.generator import ChapterGenerator
from aiwebnovel.story.pipeline_jobs import PipelineJobManager
from aiwebnovel.story.scene_markers import SceneMarker

# Re-export symbols that tests and other modules import from this path
from aiwebnovel.story.seeds import (  # noqa: F401
    DiversitySeed,
    assemble_genre_conventions,
    get_seed_by_id,
    select_seeds,
)
from aiwebnovel.story.title_generator import TitleGenerator
from aiwebnovel.story.validator import ChapterValidator, ValidationResult
from aiwebnovel.story.world_generator import (
    WORLD_STAGES,  # noqa: F401 — re-exported for backward compat
    WORLD_WAVES,  # noqa: F401 — re-exported for backward compat
    WorldGenerator,
)


@dataclass
class WorldResult:
    """Result of world generation pipeline."""

    stages_completed: list[str] = field(default_factory=list)
    stage_data: dict[str, Any] = field(default_factory=dict)
    success: bool = False
    error: str | None = None


@dataclass
class ChapterResult:
    """Result of chapter generation lifecycle."""

    chapter_text: str = ""
    chapter_id: int | None = None
    draft_number: int = 1
    analysis: AnalysisResult | None = None
    validation: ValidationResult | None = None
    scene_markers: list[SceneMarker] = field(default_factory=list)
    bible_entry_ids: list[int] = field(default_factory=list)
    success: bool = False
    error: str | None = None
    flagged_for_review: bool = False


class StoryPipeline:
    """Master orchestrator for world and chapter generation.

    Public API:
        - generate_world(novel_id, user_id, ...)
        - generate_chapter(novel_id, chapter_number, user_id, ...)
        - regenerate_chapter(novel_id, chapter_number, guidance, user_id)

    Construction signature is unchanged:
        StoryPipeline(llm, session_factory, settings, redis=None, vector_store=None)
    """

    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        redis: Any | None = None,
        vector_store: Any | None = None,
    ) -> None:
        self.llm = llm
        self.session_factory = session_factory
        self.settings = settings
        self.redis = redis

        # Sub-components (public — tests mock these directly)
        self.context_assembler = ContextAssembler(
            llm, settings, vector_store=vector_store,
        )
        self.generator = ChapterGenerator(llm, settings)
        self.analyzer = ChapterAnalyzer(llm, settings)
        self.validator = ChapterValidator()
        self.extractor = DataExtractor()

        # Internal delegates
        self._job_manager = PipelineJobManager(redis)
        self._character_seeder = CharacterSeeder()
        self._title_generator = TitleGenerator(llm, settings)
        self._world_gen = WorldGenerator(
            llm=llm,
            session_factory=session_factory,
            settings=settings,
            context_assembler=self.context_assembler,
            job_manager=self._job_manager,
            title_generator=self._title_generator,
            character_seeder=self._character_seeder,
        )
        self._chapter_pipeline = ChapterPipelineRunner(
            llm=llm,
            session_factory=session_factory,
            settings=settings,
            context_assembler=self.context_assembler,
            generator=self.generator,
            analyzer=self.analyzer,
            validator=self.validator,
            extractor=self.extractor,
            job_manager=self._job_manager,
        )

    # ------------------------------------------------------------------
    # Backward-compatible delegate methods used by tests
    # ------------------------------------------------------------------

    async def _acquire_lock(self, novel_id: int) -> bool:
        return await self._job_manager.acquire_lock(novel_id)

    async def _release_lock(self, novel_id: int) -> None:
        await self._job_manager.release_lock(novel_id)

    async def _create_job(self, session, novel_id, job_type, chapter_number=None):
        return await self._job_manager.create_job(session, novel_id, job_type, chapter_number)

    async def _update_heartbeat(self, session, job):
        await self._job_manager.update_heartbeat(session, job)

    async def _update_stage(self, session, job, stage_name):
        await self._job_manager.update_stage(session, job, stage_name)

    async def _complete_job(self, session, job, status="completed", error=None):
        await self._job_manager.complete_job(session, job, status, error)

    async def _seed_characters_from_world(self, session, novel_id, stage_data,
                                          char_identities=None,
                                          has_custom_direction=False):
        """Backward-compatible delegate — tests call this directly."""
        await self._character_seeder.seed_characters_from_world(
            session, novel_id, stage_data,
            char_identities=char_identities,
            has_custom_direction=has_custom_direction,
        )

    def _build_world_summary(self, stage_data):
        """Backward-compatible delegate."""
        return self._title_generator.build_world_summary(stage_data)

    async def _generate_title_and_synopsis(self, session, novel_id, user_id,
                                           stage_data, seeds=None, anti_rep=""):
        """Backward-compatible delegate."""
        await self._title_generator.generate_title_and_synopsis(
            session, novel_id, user_id, stage_data, seeds=seeds, anti_rep=anti_rep,
        )

    async def _save_draft(self, session, novel_id, chapter_number,
                          chapter_text, draft_number):
        """Backward-compatible delegate."""
        return await self._chapter_pipeline._save_draft(
            session, novel_id, chapter_number, chapter_text, draft_number,
        )

    @staticmethod
    def _parse_stage_data(data):
        """Backward-compatible delegate."""
        return CharacterSeeder._parse_stage_data(data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_world(
        self,
        novel_id: int,
        user_id: int = 0,
        tag_overrides: list[str] | None = None,
        gen_ctx: Any | None = None,
    ) -> WorldResult:
        """Run 8-stage world generation pipeline."""
        raw = await self._world_gen.generate_world(
            novel_id, user_id, tag_overrides=tag_overrides, gen_ctx=gen_ctx,
        )
        result = WorldResult(
            stages_completed=raw["stages_completed"],
            stage_data=raw["stage_data"],
            success=raw["success"],
            error=raw.get("error"),
        )
        return result

    async def generate_chapter(
        self,
        novel_id: int,
        chapter_number: int,
        user_id: int,
        guidance: str | None = None,
        job_id: int | None = None,
        gen_ctx: Any | None = None,
    ) -> ChapterResult:
        """Full chapter lifecycle: budget -> plan -> context -> generate ->
        analyze -> validate -> retry? -> extract -> store -> summarize.
        """
        # 1. Acquire lock
        if not await self._job_manager.acquire_lock(novel_id):
            result = ChapterResult()
            result.error = "Generation already in progress for this novel"
            return result

        try:
            raw = await self._chapter_pipeline.generate_chapter(
                novel_id, chapter_number, user_id,
                guidance=guidance, job_id=job_id, gen_ctx=gen_ctx,
            )
        finally:
            await self._job_manager.release_lock(novel_id)

        return ChapterResult(
            chapter_text=raw["chapter_text"],
            chapter_id=raw["chapter_id"],
            draft_number=raw["draft_number"],
            analysis=raw["analysis"],
            validation=raw["validation"],
            scene_markers=raw["scene_markers"],
            bible_entry_ids=raw["bible_entry_ids"],
            success=raw["success"],
            error=raw["error"],
            flagged_for_review=raw["flagged_for_review"],
        )

    async def regenerate_chapter(
        self,
        novel_id: int,
        chapter_number: int,
        guidance: str,
        user_id: int,
    ) -> ChapterResult:
        """Re-generate chapter with author guidance, creates new draft."""
        if not await self._job_manager.acquire_lock(novel_id):
            result = ChapterResult()
            result.error = "Generation already in progress for this novel"
            return result

        try:
            raw = await self._chapter_pipeline.regenerate_chapter(
                novel_id, chapter_number, guidance, user_id,
            )
        finally:
            await self._job_manager.release_lock(novel_id)

        return ChapterResult(
            chapter_text=raw["chapter_text"],
            chapter_id=raw["chapter_id"],
            draft_number=raw["draft_number"],
            analysis=raw["analysis"],
            validation=raw["validation"],
            scene_markers=raw["scene_markers"],
            bible_entry_ids=raw["bible_entry_ids"],
            success=raw["success"],
            error=raw["error"],
            flagged_for_review=raw["flagged_for_review"],
        )


# Keep ChapterAnalyzer importable from here for analyzer reference
from aiwebnovel.story.analyzer import ChapterAnalyzer  # noqa: E402, F401
