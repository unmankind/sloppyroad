"""World generation pipeline: wave execution, stage storage, context assembly.

Extracted from pipeline.py to reduce module size.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import litellm.exceptions
import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    Novel,
    NovelSeed,
    NovelSettings,
    NovelTag,
    WorldBuildingStage,
)
from aiwebnovel.llm.prompts import (
    ANTAGONISTS,
    COSMOLOGY,
    CURRENT_STATE,
    GEOGRAPHY,
    HISTORY,
    POWER_SYSTEM,
    PROTAGONIST,
    SUPPORTING_CAST,
)
from aiwebnovel.llm.provider import LLMProvider, strip_json_fences
from aiwebnovel.story.anti_repetition import build_anti_repetition_directives
from aiwebnovel.story.character_seeder import CharacterSeeder
from aiwebnovel.story.context import ContextAssembler
from aiwebnovel.story.pipeline_jobs import PipelineJobManager
from aiwebnovel.story.seeds import (
    DiversitySeed,
    assemble_genre_conventions,
    get_seed_by_id,
    select_seeds,
)
from aiwebnovel.story.title_generator import TitleGenerator

logger = structlog.get_logger(__name__)

# World pipeline stages in order (kept for reference / iteration)
WORLD_STAGES = [
    ("cosmology", COSMOLOGY),
    ("power_system", POWER_SYSTEM),
    ("geography", GEOGRAPHY),
    ("history", HISTORY),
    ("current_state", CURRENT_STATE),
    ("protagonist", PROTAGONIST),
    ("antagonists", ANTAGONISTS),
    ("supporting_cast", SUPPORTING_CAST),
]

# Parallel execution waves — stages within a wave run concurrently.
# Each tuple: (stage_name, template, stage_order)
WORLD_WAVES: list[list[tuple[str, Any, int]]] = [
    # Wave 1: Foundation (no cross-dependencies)
    [
        ("cosmology", COSMOLOGY, 0),
        ("power_system", POWER_SYSTEM, 1),
        ("geography", GEOGRAPHY, 2),
    ],
    # Wave 2: Context (needs foundation)
    [("history", HISTORY, 3), ("current_state", CURRENT_STATE, 4)],
    # Wave 3: Characters (needs everything above)
    [
        ("protagonist", PROTAGONIST, 5),
        ("antagonists", ANTAGONISTS, 6),
        ("supporting_cast", SUPPORTING_CAST, 7),
    ],
]


class WorldGenerator:
    """Handles the 8-stage world generation pipeline."""

    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        context_assembler: ContextAssembler,
        job_manager: PipelineJobManager,
        title_generator: TitleGenerator,
        character_seeder: CharacterSeeder,
    ) -> None:
        self.llm = llm
        self.session_factory = session_factory
        self.settings = settings
        self.context_assembler = context_assembler
        self.job_manager = job_manager
        self.title_generator = title_generator
        self.character_seeder = character_seeder

    async def _run_world_stage(
        self,
        stage_name: str,
        template: Any,
        stage_order: int,
        prior_context: str,
        genre_conventions: str,
        novel_id: int,
        user_id: int,
        model: str,
        character_identities: str = "",
        novel_title_context: str = "",
        gen_ctx: Any | None = None,
    ) -> tuple[str, int, Any, dict, int, str]:
        """Run a single world-building stage.

        Returns (name, order, response, parsed, duration_ms, prompt_used).
        """
        system, user = template.render(
            prior_context=prior_context,
            genre_conventions=genre_conventions,
            character_identities=character_identities,
            novel_title_context=novel_title_context,
        )

        # Pass BYOK key if available
        llm_kwargs: dict[str, Any] = {}
        if gen_ctx is not None:
            llm_kwargs["api_key"] = gen_ctx.api_key
            llm_kwargs["is_platform_key"] = gen_ctx.is_platform_key

        t0 = time.monotonic()
        response = await self.llm.generate(
            system=system,
            user=user,
            model=model,
            temperature=template.temperature,
            max_tokens=template.max_tokens,
            response_format=template.response_parser,
            novel_id=novel_id,
            user_id=user_id,
            purpose=f"world_{stage_name}",
            **llm_kwargs,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)

        parsed_data: dict = {}
        if template.response_parser:
            try:
                parsed = template.response_parser.model_validate_json(
                    strip_json_fences(response.content),
                )
                parsed_data = parsed.model_dump()
            except Exception as parse_exc:
                # Retry once with explicit guidance about the constraint
                logger.warning(
                    "world_stage_parse_retry",
                    stage=stage_name,
                    error=str(parse_exc)[:200],
                )
                retry_response = await self.llm.generate(
                    system=system,
                    user=user + (
                        "\n\nIMPORTANT: Your previous response had a "
                        "formatting error. Please follow the JSON schema "
                        "exactly. Keep all arrays within reasonable bounds."
                    ),
                    model=model,
                    temperature=min(template.temperature + 0.1, 1.0),
                    max_tokens=template.max_tokens,
                    response_format=template.response_parser,
                    novel_id=novel_id,
                    user_id=user_id,
                    purpose=f"world_{stage_name}_retry",
                    **llm_kwargs,
                )
                duration_ms += int((time.monotonic() - t0) * 1000)
                parsed = template.response_parser.model_validate_json(
                    strip_json_fences(retry_response.content),
                )
                parsed_data = parsed.model_dump()

        prompt_used = f"SYSTEM:\n{system}\n\nUSER:\n{user}"
        return stage_name, stage_order, response, parsed_data, duration_ms, prompt_used

    async def generate_world(
        self,
        novel_id: int,
        user_id: int = 0,
        tag_overrides: list[str] | None = None,
        gen_ctx: Any | None = None,
    ) -> dict[str, Any]:
        """Run 8-stage world generation pipeline.

        Returns a dict with keys: stages_completed, stage_data, success, error.
        (The caller wraps this into a WorldResult dataclass.)
        """
        result_stages: list[str] = []
        result_data: dict[str, Any] = {}

        async with self.session_factory() as session:
            job = await self.job_manager.create_job(session, novel_id, "world_generation")
            novel = await session.get(Novel, novel_id)
            if novel is not None:
                novel.status = "skeleton_in_progress"
            await session.commit()

            # --- Assemble dynamic genre conventions ---
            if tag_overrides is not None:
                author_tags = tag_overrides
            else:
                tag_rows = (await session.execute(
                    select(NovelTag.tag_name)
                    .where(NovelTag.novel_id == novel_id)
                )).scalars().all()
                author_tags = list(tag_rows)

            # Load custom conventions from NovelSettings
            settings_row = (await session.execute(
                select(NovelSettings.custom_genre_conventions)
                .where(NovelSettings.novel_id == novel_id)
            )).scalar_one_or_none()
            custom_conventions = settings_row if isinstance(settings_row, str) else None

            # Load author-confirmed diversity seeds from DB
            seed_rows = (await session.execute(
                select(NovelSeed)
                .where(
                    NovelSeed.novel_id == novel_id,
                    NovelSeed.status == "confirmed",
                )
            )).scalars().all()

            if seed_rows:
                seeds = []
                for row in seed_rows:
                    bank_seed = get_seed_by_id(row.seed_id)
                    if bank_seed is not None:
                        seeds.append(bank_seed)
                    else:
                        # Seed removed from bank — reconstruct from stored fields
                        seeds.append(DiversitySeed(
                            id=row.seed_id,
                            category=row.seed_category,
                            text=row.seed_text,
                        ))
            else:
                # Fallback for legacy novels with no persisted seeds
                seeds = select_seeds(author_tags, num_seeds=3)

            # Build anti-repetition directives from prior novels
            anti_rep = await build_anti_repetition_directives(session, novel_id)

            # Assemble the full conventions string
            genre_conventions = assemble_genre_conventions(
                author_tags=author_tags,
                selected_seeds=seeds,
                custom_conventions=custom_conventions,
                anti_repetition=anti_rep,
            )

            logger.info(
                "world_gen_conventions_assembled",
                novel_id=novel_id,
                tags=author_tags,
                seed_ids=[s.id for s in seeds],
                convention_tokens=len(genre_conventions.split()),
            )

            try:
                world_gen_model = self.settings.litellm_world_gen_model
                pipeline_t0 = time.monotonic()

                # Build title context if the author set a real title
                _placeholder_titles = {
                    "untitled novel", "untitled", "new novel",
                    "untitled world", "",
                }
                novel_title_context = ""
                if (
                    novel is not None
                    and novel.title.strip().lower() not in _placeholder_titles
                ):
                    novel_title_context = (
                        f'The author has titled this novel "{novel.title}". '
                        f"Let the world's themes, atmosphere, and flavor "
                        f"resonate with this title.\n\n"
                    )

                # Pre-roll character identities for wave 3
                from aiwebnovel.story.names import (
                    format_identities_for_prompt,
                    generate_character_identities_with_db,
                )

                char_identities = await generate_character_identities_with_db(
                    session, novel_id,
                    protagonist_count=1,
                    antagonist_count=3,
                    supporting_count=4,
                )
                # Map stage names to their identity prompt strings
                _has_custom = bool(custom_conventions)
                _identity_map = {
                    "protagonist": format_identities_for_prompt(
                        char_identities, "protagonist",
                        has_custom_direction=_has_custom,
                    ),
                    "antagonists": format_identities_for_prompt(
                        char_identities, "antagonist",
                        has_custom_direction=_has_custom,
                    ),
                    "supporting_cast": format_identities_for_prompt(
                        char_identities, "supporting",
                        has_custom_direction=_has_custom,
                    ),
                }

                logger.info(
                    "character_identities_prerolled",
                    novel_id=novel_id,
                    protagonist=char_identities["protagonist"][0].full_name
                    if char_identities["protagonist"] else "none",
                    antagonist_count=len(char_identities["antagonist"]),
                    supporting_count=len(char_identities["supporting"]),
                )

                for wave_idx, wave in enumerate(WORLD_WAVES):
                    # Check if all stages in this wave already exist (retry skip)
                    existing_stages: dict[str, WorldBuildingStage] = {}
                    for stage_name, _, stage_order in wave:
                        existing = (await session.execute(
                            select(WorldBuildingStage).where(
                                WorldBuildingStage.novel_id == novel_id,
                                WorldBuildingStage.stage_order == stage_order,
                                WorldBuildingStage.status == "complete",
                            )
                        )).scalar_one_or_none()
                        if existing:
                            existing_stages[stage_name] = existing

                    if len(existing_stages) == len(wave):
                        for stage_name, _, stage_order in wave:
                            result_stages.append(stage_name)
                            result_data[stage_name] = (
                                existing_stages[stage_name].parsed_data
                            )
                            logger.info(
                                "world_stage_skipped_existing",
                                novel_id=novel_id,
                                stage=stage_name,
                                stage_order=stage_order,
                            )
                        await self.job_manager.update_heartbeat(session, job)
                        logger.info(
                            "world_wave_skipped",
                            novel_id=novel_id,
                            wave=wave_idx + 1,
                        )
                        continue

                    # Build context once per wave — all stages in the wave
                    # share the same prior context (from completed waves).
                    min_order = wave[0][2]  # lowest stage_order in this wave
                    world_ctx = await self.context_assembler.build_world_context(
                        session, novel_id, min_order,
                    )
                    prior_context = world_ctx["prior_context"]

                    # Fire all stages in this wave concurrently
                    tasks = [
                        self._run_world_stage(
                            stage_name, template, stage_order,
                            prior_context, genre_conventions,
                            novel_id, user_id, world_gen_model,
                            character_identities=_identity_map.get(
                                stage_name, "",
                            ),
                            novel_title_context=novel_title_context,
                            gen_ctx=gen_ctx,
                        )
                        for stage_name, template, stage_order in wave
                    ]
                    stage_results = await asyncio.gather(*tasks)

                    # Store results and commit (upsert — safe for retries)
                    for (
                        stage_name, stage_order, response,
                        parsed_data, duration_ms, prompt_used,
                    ) in stage_results:
                        existing = (await session.execute(
                            select(WorldBuildingStage).where(
                                WorldBuildingStage.novel_id == novel_id,
                                WorldBuildingStage.stage_order == stage_order,
                            )
                        )).scalar_one_or_none()

                        if existing:
                            existing.raw_response = response.content
                            existing.parsed_data = parsed_data
                            existing.model_used = response.model
                            existing.token_count = (
                                response.prompt_tokens + response.completion_tokens
                            )
                            existing.prompt_used = prompt_used
                            existing.status = "complete"
                        else:
                            stage = WorldBuildingStage(
                                novel_id=novel_id,
                                stage_order=stage_order,
                                stage_name=stage_name,
                                prompt_used=prompt_used,
                                raw_response=response.content,
                                parsed_data=parsed_data,
                                model_used=response.model,
                                token_count=(
                                    response.prompt_tokens + response.completion_tokens
                                ),
                                status="complete",
                            )
                            session.add(stage)

                        result_stages.append(stage_name)
                        result_data[stage_name] = parsed_data

                        logger.info(
                            "world_stage_complete",
                            novel_id=novel_id,
                            stage=stage_name,
                            stage_order=stage_order,
                            duration_ms=duration_ms,
                            model=response.model,
                            tokens=response.prompt_tokens + response.completion_tokens,
                        )

                    await self.job_manager.update_heartbeat(session, job)
                    await session.commit()

                    logger.info(
                        "world_wave_complete",
                        novel_id=novel_id,
                        wave=wave_idx + 1,
                        stages=[s[0] for s in wave],
                    )

                pipeline_duration = int((time.monotonic() - pipeline_t0) * 1000)
                logger.info(
                    "world_generation_complete",
                    novel_id=novel_id,
                    total_duration_ms=pipeline_duration,
                    model=world_gen_model,
                )

                # --- Post-world: generate title + synopsis ---
                await self.title_generator.generate_title_and_synopsis(
                    session, novel_id, user_id, result_data,
                    seeds=seeds, anti_rep=anti_rep,
                )

                # --- Seed Character rows from world data ---
                try:
                    await self.character_seeder.seed_characters_from_world(
                        session, novel_id, result_data,
                        char_identities=char_identities,
                        has_custom_direction=_has_custom,
                    )
                    await session.commit()
                except Exception as exc:
                    logger.warning(
                        "character_seeding_failed",
                        novel_id=novel_id,
                        error=str(exc),
                    )
                    await session.rollback()

                novel = await session.get(Novel, novel_id)
                if novel is not None:
                    novel.status = "skeleton_complete"
                await self.job_manager.complete_job(session, job)
                await session.commit()

                return {
                    "stages_completed": result_stages,
                    "stage_data": result_data,
                    "success": True,
                    "error": None,
                }

            except (
                SQLAlchemyError,
                RuntimeError,
                litellm.exceptions.APIError,
                litellm.exceptions.Timeout,
                litellm.exceptions.APIConnectionError,
            ) as exc:
                await self.job_manager.complete_job(
                    session, job, "failed", str(exc),
                )
                # Reset novel so the user can retry from seed review
                novel = await session.get(Novel, novel_id)
                if novel is not None:
                    novel.status = "seed_review"
                await session.commit()
                logger.error(
                    "world_generation_failed",
                    novel_id=novel_id,
                    error=str(exc),
                )
                raise

            except Exception as exc:
                # Catch-all for unexpected errors (e.g. ValidationError)
                from aiwebnovel.llm.sanitize import friendly_generation_error

                friendly = friendly_generation_error(exc)
                await self.job_manager.complete_job(
                    session, job, "failed", friendly,
                )
                novel = await session.get(Novel, novel_id)
                if novel is not None:
                    novel.status = "seed_review"
                await session.commit()
                logger.error(
                    "world_generation_failed_unexpected",
                    novel_id=novel_id,
                    error=str(exc),
                    exc_type=type(exc).__name__,
                )
                raise

        # Should not reach here, but just in case
        return {
            "stages_completed": result_stages,
            "stage_data": result_data,
            "success": False,
            "error": "Unexpected exit",
        }
