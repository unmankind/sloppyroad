"""Context assembly for chapter and world generation.

Builds prioritized context windows within token budgets using
priority-based truncation: P1 (never truncate) through P5 (first to drop).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    Chapter,
    ChapterSummary,
    Novel,
    NovelSeed,
    WorldBuildingStage,
)
from aiwebnovel.db.queries import (
    get_active_chekhov_guns,
    get_active_foreshadowing,
    get_chapter_context,
    get_escalation_state,
)
from aiwebnovel.llm.provider import LLMProvider

logger = structlog.get_logger(__name__)


@dataclass
class ContextSection:
    """A single section of assembled context."""

    name: str
    content: str
    priority: int  # 1 = never truncate, 5 = first to drop
    tokens: int = 0


@dataclass
class AssembledContext:
    """Result of context assembly with token budget management."""

    sections: dict[str, ContextSection] = field(default_factory=dict)
    total_tokens: int = 0
    budget: int = 0
    truncated_sections: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        """Render all sections into a single context string."""
        parts: list[str] = []
        # Sort by priority (lowest first = most important)
        for section in sorted(self.sections.values(), key=lambda s: s.priority):
            if section.content.strip():
                parts.append(section.content)
        return "\n\n".join(parts)

    def add_section(self, name: str, content: str, priority: int, tokens: int) -> None:
        """Add a context section."""
        self.sections[name] = ContextSection(
            name=name, content=content, priority=priority, tokens=tokens,
        )
        self.total_tokens += tokens


class ContextAssembler:
    """Assembles context for chapter generation within token budgets."""

    def __init__(
        self,
        llm: LLMProvider,
        settings: Settings,
        vector_store: Any | None = None,
    ) -> None:
        self.llm = llm
        self.settings = settings
        self._semantic_retriever: Any | None = None
        if vector_store is not None:
            from aiwebnovel.story.semantic import SemanticRetriever

            self._semantic_retriever = SemanticRetriever(
                llm, vector_store, settings,
            )

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for a string."""
        return self.llm.estimate_tokens(text)

    async def build_chapter_context(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        chapter_plan: Any | None = None,
        token_budget: int | None = None,
    ) -> AssembledContext:
        """Assemble context within token budget using priority-based truncation.

        Priority 1 (NEVER truncate): power system rules, escalation state,
            enhanced recap, perspective filter
        Priority 2 (high): chapter plan, character states, Chekhov directives
        Priority 3 (medium): recent summaries (2-5), top bible entries, foreshadowing
        Priority 4 (low): compressed world state, remaining bible entries
        Priority 5 (first to truncate): reader influence, historical summaries
        """
        budget = token_budget or self.settings.context_window_cap
        ctx = AssembledContext(budget=budget)

        # Fetch raw data
        raw = await get_chapter_context(session, novel_id, chapter_number)
        escalation_data = await get_escalation_state(session, novel_id)
        foreshadowing = await get_active_foreshadowing(session, novel_id)
        chekhov_guns = await get_active_chekhov_guns(session, novel_id)

        # --- Priority 1: Never truncate ---

        # World-building data from the 8-stage pipeline (THE canonical world)
        world_stages = raw.get("world_stages", [])
        world_building_text = self._format_world_building(world_stages)
        if world_building_text:
            ctx.add_section("world_building", world_building_text, priority=1,
                            tokens=self._estimate_tokens(world_building_text))

        # Name exclusion list (prevent cross-novel name reuse)
        name_exclusion_text = await self._build_name_exclusions(session, novel_id)
        if name_exclusion_text:
            ctx.add_section("name_exclusions", name_exclusion_text, priority=1,
                            tokens=self._estimate_tokens(name_exclusion_text))

        # Diversity seeds (creative constraints for variety across chapters)
        diversity_text = await self._load_diversity_seeds(session, novel_id)
        if diversity_text:
            ctx.add_section("diversity_seeds", diversity_text, priority=2,
                            tokens=self._estimate_tokens(diversity_text))

        # Power system rules
        ps = raw.get("power_system")
        if ps:
            power_text = (
                f"Power System: {ps.system_name}\n"
                f"Core Mechanic: {ps.core_mechanic}\n"
                f"Hard Limits: {', '.join(ps.hard_limits) if ps.hard_limits else 'None'}\n"
                f"Soft Limits: {', '.join(ps.soft_limits) if ps.soft_limits else 'None'}"
            )
            ctx.add_section("power_system", power_text, priority=1,
                            tokens=self._estimate_tokens(power_text))

        # Escalation state
        esc_state = escalation_data.get("state")
        scope_tier = escalation_data.get("scope_tier")
        if esc_state:
            esc_text = (
                f"Escalation Phase: {esc_state.current_phase}\n"
                f"Tension Level: {esc_state.tension_level}\n"
                f"Scope Tier: {scope_tier.tier_name if scope_tier else 'Unknown'}"
            )
            ctx.add_section("escalation", esc_text, priority=1,
                            tokens=self._estimate_tokens(esc_text))

        # Enhanced recap (previous chapter)
        recent_chapters: list[Chapter] = raw.get("recent_chapters", [])
        if recent_chapters:
            prev_ch = recent_chapters[0]
            recap_stmt = (
                select(ChapterSummary)
                .where(
                    ChapterSummary.chapter_id == prev_ch.id,
                    ChapterSummary.summary_type == "enhanced_recap",
                )
            )
            recap_result = await session.execute(recap_stmt)
            recap = recap_result.scalar_one_or_none()
            if recap:
                recap_text = f"Previous Chapter Recap:\n{recap.content}"
                ctx.add_section("enhanced_recap", recap_text, priority=1,
                                tokens=self._estimate_tokens(recap_text))

        # Protagonist identity (P1 — never truncate)
        chars = raw.get("active_characters", [])
        protagonist = None
        cast = []
        for c in chars:
            if c.role == "protagonist":
                protagonist = c
            else:
                cast.append(c)

        if protagonist:
            protag_parts = [
                "PROTAGONIST — this is the main character. Use ONLY this identity.",
                f"Name: {protagonist.name}",
            ]
            if protagonist.sex:
                protag_parts.append(
                    f"Sex: {protagonist.sex.title()} "
                    f"({protagonist.pronouns or ''})"
                )
            if protagonist.visual_appearance:
                protag_parts.append(
                    f"Appearance: {protagonist.visual_appearance}"
                )
            protag_parts.append(
                f"Background: {protagonist.background or protagonist.description[:300]}"
            )
            protag_parts.append(
                f"Motivation: {protagonist.motivation or 'Not yet revealed'}"
            )
            protag_text = "\n".join(protag_parts)
            ctx.add_section("protagonist", protag_text, priority=1,
                            tokens=self._estimate_tokens(protag_text))

        # --- Priority 2: High ---

        # Chapter plan
        if chapter_plan:
            plan_text = f"Chapter Plan: {chapter_plan.title or 'Untitled'}\n"
            if chapter_plan.scene_outline:
                for i, scene in enumerate(chapter_plan.scene_outline, 1):
                    if isinstance(scene, dict):
                        plan_text += f"Scene {i}: {scene.get('description', '')}\n"
                    else:
                        plan_text += f"Scene {i}: {scene}\n"
            if chapter_plan.target_tension is not None:
                plan_text += f"Target Tension: {chapter_plan.target_tension}"
            ctx.add_section("chapter_plan", plan_text, priority=2,
                            tokens=self._estimate_tokens(plan_text))

        # Cast (non-protagonist characters)
        if cast:
            cast_lines = []
            for c in cast[:10]:
                sex_info = f", {c.sex}" if c.sex else ""
                appearance = (
                    f" [{c.visual_appearance}]"
                    if c.visual_appearance else ""
                )
                desc = c.description[:150] if c.description else ""
                line = f"- {c.name} ({c.role}{sex_info}){appearance}: {desc}"
                cast_lines.append(line)
            cast_text = "Supporting Cast:\n" + "\n".join(cast_lines)
            ctx.add_section("cast", cast_text, priority=2,
                            tokens=self._estimate_tokens(cast_text))

        # Chekhov directives
        if chekhov_guns:
            gun_lines = []
            for g in chekhov_guns[:5]:
                gun_lines.append(
                    f"- [{g.status}, pressure={g.pressure_score:.2f}] {g.description[:150]}"
                )
            gun_text = "Chekhov Directives:\n" + "\n".join(gun_lines)
            ctx.add_section("chekhov", gun_text, priority=2,
                            tokens=self._estimate_tokens(gun_text))

        # --- Priority 3: Medium ---

        # Recent summaries (chapters 2-5)
        if len(recent_chapters) > 1:
            summary_parts = []
            for ch in recent_chapters[1:5]:
                sum_stmt = (
                    select(ChapterSummary)
                    .where(
                        ChapterSummary.chapter_id == ch.id,
                        ChapterSummary.summary_type == "standard",
                    )
                )
                sum_result = await session.execute(sum_stmt)
                summary = sum_result.scalar_one_or_none()
                if summary:
                    summary_parts.append(
                        f"Ch {ch.chapter_number}: {summary.content[:300]}"
                    )
            if summary_parts:
                sum_text = "Recent Summaries:\n" + "\n".join(summary_parts)
                ctx.add_section("recent_summaries", sum_text, priority=3,
                                tokens=self._estimate_tokens(sum_text))

        # Foreshadowing seeds
        if foreshadowing:
            seed_lines = []
            for s in foreshadowing[:5]:
                seed_lines.append(f"- [{s.seed_type}] {s.description[:150]}")
            seed_text = "Active Foreshadowing:\n" + "\n".join(seed_lines)
            ctx.add_section("foreshadowing", seed_text, priority=3,
                            tokens=self._estimate_tokens(seed_text))

        # Story bible (semantic vector search)
        if self._semantic_retriever is not None and chapter_plan is not None:
            try:
                semantic_ctx = (
                    await self._semantic_retriever.assemble_semantic_context(
                        session,
                        novel_id,
                        chapter_plan,
                        token_budget=3000,
                    )
                )
                if semantic_ctx and semantic_ctx.formatted_text:
                    ctx.add_section(
                        "story_bible",
                        semantic_ctx.formatted_text,
                        priority=3,
                        tokens=semantic_ctx.total_tokens,
                    )
            except Exception as exc:
                logger.warning(
                    "semantic_retrieval_failed",
                    novel_id=novel_id,
                    chapter_number=chapter_number,
                    error=str(exc),
                )

        # --- Priority 4: Low ---

        # World state (compressed)
        regions = raw.get("revealed_regions", [])
        if regions:
            region_lines = [f"- {r.name}: {r.description[:100]}" for r in regions[:8]]
            world_text = "World State:\n" + "\n".join(region_lines)
            ctx.add_section("world_state", world_text, priority=4,
                            tokens=self._estimate_tokens(world_text))

        # --- Priority 5: First to truncate ---

        # Reader influence (placeholder)
        ctx.add_section("reader_influence", "", priority=5, tokens=0)

        # Truncate if over budget
        self._truncate_to_budget(ctx)

        logger.info(
            "context_assembled",
            novel_id=novel_id,
            chapter_number=chapter_number,
            total_tokens=ctx.total_tokens,
            budget=budget,
            sections=len(ctx.sections),
            truncated=ctx.truncated_sections,
        )

        return ctx

    def _truncate_to_budget(self, ctx: AssembledContext) -> None:
        """Remove lowest-priority sections until within budget."""
        if ctx.total_tokens <= ctx.budget:
            return

        # Sort sections by priority descending (highest = lowest priority)
        sections_by_priority = sorted(
            ctx.sections.values(), key=lambda s: s.priority, reverse=True,
        )

        for section in sections_by_priority:
            if ctx.total_tokens <= ctx.budget:
                break
            if section.priority <= 1:
                # Never truncate P1
                break
            ctx.total_tokens -= section.tokens
            ctx.truncated_sections.append(section.name)
            del ctx.sections[section.name]

    def _format_world_building(self, stages: list[Any]) -> str:
        """Format world-building stages as comprehensive context.

        This is the PRIMARY source of world data for chapter generation.
        The world pipeline generates detailed data (cosmology, power system,
        geography, history, current state, protagonist, antagonists,
        supporting cast) that MUST be used by the chapter generator.
        """
        if not stages:
            return ""

        parts: list[str] = []
        for stage in stages:
            summary = self._summarize_stage(stage.stage_name, stage.parsed_data)
            if summary:
                parts.append(f"=== {stage.stage_name.upper()} ===\n{summary}")

        if not parts:
            return ""

        header = (
            "WORLD BUILDING DATA — This is the canonical world. You MUST use "
            "these names, places, systems, and characters exactly as defined. "
            "Do NOT invent alternative names, settings, or power systems."
        )
        return header + "\n\n" + "\n\n".join(parts)

    async def _build_name_exclusions(
        self,
        session: AsyncSession,
        novel_id: int,
    ) -> str:
        """Build a list of protagonist/character names from other novels by the
        same author. These names must NOT be reused in this novel (UNM-70)."""
        # Find this novel's author
        novel = await session.get(Novel, novel_id)
        if novel is None:
            return ""

        # Get protagonist names from OTHER novels by the same author
        other_protag_stmt = (
            select(WorldBuildingStage.parsed_data)
            .join(Novel, Novel.id == WorldBuildingStage.novel_id)
            .where(
                Novel.author_id == novel.author_id,
                WorldBuildingStage.novel_id != novel_id,
                WorldBuildingStage.stage_name == "protagonist",
                WorldBuildingStage.status == "complete",
            )
        )
        rows = (await session.execute(other_protag_stmt)).scalars().all()

        used_names: list[str] = []
        for parsed_data in rows:
            if isinstance(parsed_data, dict):
                name = parsed_data.get("name")
            elif isinstance(parsed_data, str):
                import json
                try:
                    data = json.loads(parsed_data)
                    name = data.get("name")
                except (json.JSONDecodeError, TypeError):
                    continue
            else:
                continue
            if name:
                used_names.append(name)

        if not used_names:
            return ""

        return (
            "NAME EXCLUSION — The following names are ALREADY USED in other "
            "novels by this author and must NOT be reused: "
            + ", ".join(used_names)
            + ". Choose completely different names."
        )

    async def _load_diversity_seeds(
        self,
        session: AsyncSession,
        novel_id: int,
    ) -> str:
        """Load confirmed diversity seeds for this novel.

        These creative constraints were selected during world setup and
        should guide chapter generation for structural variety.
        """
        stmt = (
            select(NovelSeed)
            .where(
                NovelSeed.novel_id == novel_id,
                NovelSeed.status == "confirmed",
            )
        )
        result = await session.execute(stmt)
        seeds = result.scalars().all()

        if not seeds:
            return ""

        seed_lines = [f"- {s.seed_text}" for s in seeds]
        return (
            "CREATIVE CONSTRAINTS — Follow these directives for narrative variety:\n"
            + "\n".join(seed_lines)
        )

    async def build_world_context(
        self,
        session: AsyncSession,
        novel_id: int,
        stage_order: int,
    ) -> dict[str, Any]:
        """Accumulate summarized prior stage outputs for world generation.

        Instead of passing raw JSON (which can be 10k+ tokens per stage),
        we extract key names and concepts to keep context under ~4k tokens.
        """
        stmt = (
            select(WorldBuildingStage)
            .where(
                WorldBuildingStage.novel_id == novel_id,
                WorldBuildingStage.stage_order < stage_order,
                WorldBuildingStage.status == "complete",
            )
            .order_by(WorldBuildingStage.stage_order.asc())
        )
        result = await session.execute(stmt)
        stages = result.scalars().all()

        context_parts: list[str] = []
        for stage in stages:
            summary = self._summarize_stage(stage.stage_name, stage.parsed_data)
            if summary:
                context_parts.append(
                    f"=== {stage.stage_name} ===\n{summary}"
                )

        return {
            "prior_context": "\n\n".join(context_parts) if context_parts else "",
            "stages_completed": [s.stage_name for s in stages],
        }

    @staticmethod
    def _summarize_stage(stage_name: str, data: dict[str, Any]) -> str:
        """Extract key names and concepts from a world stage for compact context."""
        import json

        if not data:
            return ""

        parts: list[str] = []

        if stage_name == "cosmology":
            forces = data.get("fundamental_forces", [])
            parts.append(f"Forces: {', '.join(f.get('name', '?') for f in forces)}")
            for f in forces:
                parts.append(f"  {f.get('name')}: {f.get('description', '')[:150]}")
            tiers = data.get("reality_tiers", [])
            tier_names = ', '.join(
                t.get('tier_name', '?') for t in tiers
            )
            parts.append(
                f"Reality Tiers ({len(tiers)}): {tier_names}"
            )
            energies = data.get("energy_types", [])
            parts.append(f"Energy Types: {', '.join(e.get('name', '?') for e in energies)}")
            laws = data.get("cosmic_laws", [])
            for law in laws:
                desc = law.get("description", str(law))
                parts.append(f"  Law: {desc[:120]}")
            planes = data.get("planes_of_existence", [])
            parts.append(f"Planes: {', '.join(p.get('name', '?') for p in planes)}")

        elif stage_name == "power_system":
            parts.append(f"System: {data.get('system_name', '?')}")
            parts.append(f"Core Mechanic: {data.get('core_mechanic', '')[:200]}")
            ranks = data.get("ranks", [])
            rank_names = ', '.join(
                r.get('rank_name', '?') for r in ranks
            )
            parts.append(
                f"Ranks ({len(ranks)}): {rank_names}"
            )
            discs = data.get("disciplines", [])
            for d in discs:
                dname = d.get('name', '?')
                dphil = d.get('philosophy', '')[:100]
                parts.append(
                    f"  Discipline: {dname} — {dphil}"
                )
            parts.append(f"Power Ceiling: {str(data.get('power_ceiling', ''))[:150]}")

        elif stage_name == "geography":
            regions = data.get("regions", [])
            for r in regions:
                parts.append(f"  Region: {r.get('name', '?')} — {r.get('description', '')[:100]}")
            factions = data.get("factions", [])
            for f in factions:
                parts.append(f"  Faction: {f.get('name', '?')} — {f.get('description', '')[:100]}")

        elif stage_name == "history":
            eras = data.get("eras", [])
            for e in eras:
                era_name = e.get('era_name', '?')
                dur = e.get('duration', '?')
                desc = e.get('description', '')[:100]
                parts.append(
                    f"  Era: {era_name} ({dur}) — {desc}"
                )
            figures = data.get("key_figures", [])
            names = ', '.join(
                fg.get('name', '?') for fg in figures
            )
            parts.append(f"Key Figures: {names}")

        elif stage_name == "current_state":
            conflicts = data.get("active_conflicts", [])
            for c in conflicts:
                cname = c.get('name', '?')
                cdesc = c.get('description', '')[:100]
                parts.append(
                    f"  Conflict: {cname} — {cdesc}"
                )
            parts.append(f"Power Balance: {data.get('power_balance', '')[:200]}")

        elif stage_name == "protagonist":
            parts.append(f"Name: {data.get('name', '?')}, Age: {data.get('age', '?')}")
            parts.append(f"Background: {data.get('background', '')[:200]}")
            sp = data.get("starting_power", {})
            rank = sp.get('current_rank', '?')
            disc = sp.get('discipline', 'none')
            parts.append(
                f"Starting Power: {rank}, Discipline: {disc}"
            )
            parts.append(f"Disadvantage: {data.get('disadvantage', '')[:150]}")
            parts.append(f"Unusual Trait: {data.get('unusual_trait', '')[:150]}")
            mot = data.get("motivation", {})
            if isinstance(mot, dict):
                parts.append(f"Surface Motivation: {mot.get('surface_motivation', '')[:100]}")
                parts.append(f"Deep Motivation: {mot.get('deep_motivation', '')[:100]}")

        elif stage_name == "antagonists":
            antags = data.get("antagonists", [])
            for a in antags:
                aname = a.get('name', '?')
                arole = a.get('role', '?')
                amot = a.get('motivation', '')[:100]
                parts.append(
                    f"  {aname} ({arole}): {amot}"
                )

        else:
            # Fallback: dump first 500 chars of JSON
            parts.append(json.dumps(data)[:500])

        return "\n".join(parts)
