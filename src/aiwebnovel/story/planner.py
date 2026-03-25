"""Arc and chapter planning system.

Handles arc proposal/revision/approval, chapter plan decomposition,
bridge chapters, plot thread management, and final arc planning.
"""

from __future__ import annotations

import json
import re

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import (
    ArcPlan,
    Chapter,
    ChapterPlan,
    ChapterSummary,
    Character,
    NovelSettings,
    NovelTag,
    PlotThread,
)
from aiwebnovel.db.queries import (
    get_active_chekhov_guns,
    get_active_plot_threads,
    get_current_arc,
    get_escalation_state,
)
from aiwebnovel.llm.parsers import ArcPlanResult, ChapterPlanResult, PlotThreadResult
from aiwebnovel.llm.prompts import (
    ARC_PLANNING,
    ARC_REVISION,
    CHAPTER_PLANNING,
    FINAL_ARC_PLANNING,
    PLOT_THREAD_EXTRACTION,
)
from aiwebnovel.llm.provider import LLMProvider
from aiwebnovel.story.analyzer import AnalysisResult
from aiwebnovel.story.tags import ALL_TAGS

logger = structlog.get_logger(__name__)

# Match markdown fences and trailing text after JSON
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _clean_json(text: str) -> str:
    """Extract clean JSON from LLM output.

    Handles markdown fences and trailing commentary after the JSON object.
    """
    stripped = text.strip()
    # Strip markdown fences
    m = _FENCE_RE.search(stripped)
    if m:
        stripped = m.group(1).strip()
    # Find the last closing brace — truncate trailing commentary
    last_brace = stripped.rfind("}")
    if last_brace != -1:
        stripped = stripped[: last_brace + 1]
    return stripped


def _format_arc_summary(arc: ArcPlan) -> str:
    """Format a previous arc's full plan for LLM context."""
    lines = [
        f"{arc.title} (chapters {arc.target_chapter_start}-{arc.target_chapter_end})",
        f"Status: {arc.status}",
        f"Description: {arc.description[:400]}",
    ]
    if arc.key_events:
        lines.append("Key Events:")
        for event in arc.key_events[:8]:
            if isinstance(event, dict):
                desc = event.get("description", "")[:100]
                ch = event.get("chapter_target", "?")
                lines.append(f"  - [Ch {ch}] {desc}")
    if arc.character_arcs:
        lines.append("Character Arcs:")
        for ca in arc.character_arcs[:6]:
            if isinstance(ca, dict):
                name = ca.get("character_name", "?")
                goal = ca.get("arc_goal", "")[:80]
                lines.append(f"  - {name}: {goal}")
    if arc.themes:
        themes = ", ".join(
            t.get("theme", "") if isinstance(t, dict) else str(t)
            for t in arc.themes[:5]
        )
        lines.append(f"Themes: {themes}")
    return "\n".join(lines)


async def approve_arc_plans(
    session: AsyncSession,
    arc_id: int,
) -> list[ChapterPlan]:
    """Standalone arc approval: set status and create chapter plans.

    Extracted so routes can call it without constructing a full StoryPlanner.
    The StoryPlanner.approve_arc method delegates to this.
    """
    stmt = select(ArcPlan).where(ArcPlan.id == arc_id)
    result = await session.execute(stmt)
    arc = result.scalar_one()

    arc.status = "approved"

    start = arc.target_chapter_start or 1
    end = arc.target_chapter_end or (start + 5)

    existing_stmt = (
        select(ChapterPlan.chapter_number)
        .where(
            ChapterPlan.novel_id == arc.novel_id,
            ChapterPlan.chapter_number >= start,
            ChapterPlan.chapter_number <= end,
        )
    )
    existing_nums = set(
        (await session.execute(existing_stmt)).scalars().all()
    )

    plans: list[ChapterPlan] = []
    for ch_num in range(start, end + 1):
        if ch_num in existing_nums:
            continue

        target_beats = []
        if arc.key_events:
            for event in arc.key_events:
                if isinstance(event, dict) and event.get("chapter_target") == ch_num:
                    target_beats.append(event)

        plan = ChapterPlan(
            arc_plan_id=arc.id,
            novel_id=arc.novel_id,
            chapter_number=ch_num,
            title=None,
            target_beats=target_beats or None,
            status="planned",
        )
        session.add(plan)
        plans.append(plan)

    await session.flush()

    logger.info(
        "arc_approved",
        arc_id=arc.id,
        chapter_count=len(plans),
        skipped_existing=len(existing_nums),
    )

    return plans


class StoryPlanner:
    """Arc and chapter planning intelligence."""

    def __init__(self, llm: LLMProvider, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    async def _planning_model(
        self, session: AsyncSession, novel_id: int,
    ) -> str:
        """Resolve the model to use for planning calls.

        Checks NovelSettings.analysis_model (planning is structural,
        closer to analysis than prose generation). Falls back to Haiku.
        """
        ns = (await session.execute(
            select(NovelSettings).where(NovelSettings.novel_id == novel_id)
        )).scalar_one_or_none()
        if ns and ns.analysis_model:
            return ns.analysis_model
        return self.settings.free_tier_model

    async def plan_next_arc(
        self,
        session: AsyncSession,
        novel_id: int,
        user_id: int,
    ) -> ArcPlan:
        """Gather state, call LLM, create proposed arc plan."""
        context = await self._gather_arc_context(session, novel_id)
        planning_model = await self._planning_model(session, novel_id)

        system, user = ARC_PLANNING.render(**context)
        response = await self.llm.generate(
            system=system,
            user=user,
            model=planning_model,
            temperature=ARC_PLANNING.temperature,
            max_tokens=ARC_PLANNING.max_tokens,
            response_format=ArcPlanResult,
            novel_id=novel_id,
            user_id=user_id,
            purpose="arc_planning",
        )

        parsed = ArcPlanResult.model_validate_json(_clean_json(response.content))

        # Get next arc number
        arc_count_stmt = (
            select(func.count(ArcPlan.id))
            .where(ArcPlan.novel_id == novel_id)
        )
        arc_count_result = await session.execute(arc_count_stmt)
        next_arc_number = (arc_count_result.scalar_one() or 0) + 1

        arc = ArcPlan(
            novel_id=novel_id,
            arc_number=next_arc_number,
            title=parsed.title,
            description=parsed.description,
            target_chapter_start=parsed.target_chapter_start,
            target_chapter_end=parsed.target_chapter_end,
            planned_chapters=parsed.target_chapter_end - parsed.target_chapter_start + 1,
            key_events=[e.model_dump() for e in parsed.key_events],
            character_arcs=[c.model_dump() for c in parsed.character_arcs],
            themes=[t.model_dump() for t in parsed.themes],
            status="proposed",
        )
        session.add(arc)
        await session.flush()

        logger.info(
            "arc_planned",
            novel_id=novel_id,
            arc_id=arc.id,
            title=arc.title,
        )

        return arc

    async def plan_final_arc(
        self,
        session: AsyncSession,
        novel_id: int,
        user_id: int,
    ) -> ArcPlan:
        """Plan final arc with mandatory resolution targets."""
        context = await self._gather_arc_context(session, novel_id, final=True)

        planning_model = await self._planning_model(session, novel_id)
        system, user = FINAL_ARC_PLANNING.render(**context)
        response = await self.llm.generate(
            system=system,
            user=user,
            model=planning_model,
            temperature=FINAL_ARC_PLANNING.temperature,
            max_tokens=FINAL_ARC_PLANNING.max_tokens,
            response_format=ArcPlanResult,
            novel_id=novel_id,
            user_id=user_id,
            purpose="final_arc_planning",
        )

        parsed = ArcPlanResult.model_validate_json(_clean_json(response.content))

        arc_count_stmt = (
            select(func.count(ArcPlan.id))
            .where(ArcPlan.novel_id == novel_id)
        )
        arc_count_result = await session.execute(arc_count_stmt)
        next_arc_number = (arc_count_result.scalar_one() or 0) + 1

        # Get all open threads + guns for resolution_targets
        threads = await get_active_plot_threads(session, novel_id)
        guns = await get_active_chekhov_guns(session, novel_id)
        resolution_targets = (
            [{"type": "thread", "name": t.name} for t in threads]
            + [{"type": "gun", "description": g.description[:100]} for g in guns]
        )

        arc = ArcPlan(
            novel_id=novel_id,
            arc_number=next_arc_number,
            title=parsed.title,
            description=parsed.description,
            target_chapter_start=parsed.target_chapter_start,
            target_chapter_end=parsed.target_chapter_end,
            planned_chapters=parsed.target_chapter_end - parsed.target_chapter_start + 1,
            key_events=[e.model_dump() for e in parsed.key_events],
            character_arcs=[c.model_dump() for c in parsed.character_arcs],
            themes=[t.model_dump() for t in parsed.themes],
            status="proposed",
            is_final_arc=True,
            resolution_targets=resolution_targets,
        )
        session.add(arc)
        await session.flush()

        logger.info(
            "final_arc_planned",
            novel_id=novel_id,
            arc_id=arc.id,
            resolution_count=len(resolution_targets),
        )

        return arc

    async def revise_arc(
        self,
        session: AsyncSession,
        arc_id: int,
        author_notes: str,
        user_id: int,
    ) -> ArcPlan:
        """Revise arc plan based on author feedback."""
        stmt = select(ArcPlan).where(ArcPlan.id == arc_id)
        result = await session.execute(stmt)
        arc = result.scalar_one()

        current_plan = json.dumps({
            "title": arc.title,
            "description": arc.description,
            "target_chapter_start": arc.target_chapter_start,
            "target_chapter_end": arc.target_chapter_end,
            "key_events": arc.key_events,
            "character_arcs": arc.character_arcs,
            "themes": arc.themes,
        })

        system, user = ARC_REVISION.render(
            current_arc_plan=current_plan,
            author_notes=author_notes,
        )

        planning_model = await self._planning_model(session, arc.novel_id)
        response = await self.llm.generate(
            system=system,
            user=user,
            model=planning_model,
            temperature=ARC_REVISION.temperature,
            max_tokens=ARC_REVISION.max_tokens,
            response_format=ArcPlanResult,
            novel_id=arc.novel_id,
            user_id=user_id,
            purpose="arc_revision",
        )

        parsed = ArcPlanResult.model_validate_json(_clean_json(response.content))

        arc.title = parsed.title
        arc.description = parsed.description
        arc.target_chapter_start = parsed.target_chapter_start
        arc.target_chapter_end = parsed.target_chapter_end
        arc.key_events = [e.model_dump() for e in parsed.key_events]
        arc.character_arcs = [c.model_dump() for c in parsed.character_arcs]
        arc.themes = [t.model_dump() for t in parsed.themes]
        arc.author_notes = author_notes
        arc.system_revision_count += 1

        await session.flush()

        logger.info("arc_revised", arc_id=arc.id, revision=arc.system_revision_count)

        return arc

    async def approve_arc(
        self,
        session: AsyncSession,
        arc_id: int,
    ) -> list[ChapterPlan]:
        """Approve arc and decompose into chapter plans."""
        return await approve_arc_plans(session, arc_id)

    async def plan_chapter(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        user_id: int = 0,
    ) -> ChapterPlan:
        """Create detailed chapter plan with scenes, beats, tension target."""
        # Get arc context
        arc = await get_current_arc(session, novel_id)
        guns = await get_active_chekhov_guns(session, novel_id)
        threads = await get_active_plot_threads(session, novel_id)
        escalation = await get_escalation_state(session, novel_id)

        arc_title = arc.title if arc else "No Arc"
        arc_description = arc.description if arc else ""

        # Position in arc
        arc_start = arc.target_chapter_start if arc else chapter_number
        arc_end = arc.target_chapter_end if arc else chapter_number + 5
        ch_in_arc = chapter_number - (arc_start or 1) + 1
        arc_len = (arc_end or arc_start or 1) - (arc_start or 1) + 1
        arc_position = f"Chapter {ch_in_arc} of {arc_len}"

        # Relevant events
        relevant_events = ""
        if arc and arc.key_events:
            for event in arc.key_events:
                if isinstance(event, dict) and event.get("chapter_target") == chapter_number:
                    relevant_events += f"- {event.get('description', '')}\n"

        gun_text = "\n".join(
            f"- [pressure={g.pressure_score:.2f}] {g.description[:100]}"
            for g in guns[:5]
        ) or "None"

        thread_text = "\n".join(
            f"- [{t.status}] {t.name}: {t.description[:100]}"
            for t in threads[:5]
        ) or "None"

        esc_state = escalation.get("state")
        tension_target = str(esc_state.tension_level if esc_state else 0.5)

        context = {
            "chapter_number": str(chapter_number),
            "arc_title": arc_title,
            "arc_description": arc_description,
            "arc_position": arc_position,
            "relevant_arc_events": relevant_events or "None",
            "pov_character": "Protagonist",
            "tension_target": tension_target,
            "chekhov_directives": gun_text,
            "active_threads": thread_text,
            "reader_signals": "",
        }

        planning_model = await self._planning_model(session, novel_id)
        system, user = CHAPTER_PLANNING.render(**context)
        response = await self.llm.generate(
            system=system,
            user=user,
            model=planning_model,
            temperature=CHAPTER_PLANNING.temperature,
            max_tokens=CHAPTER_PLANNING.max_tokens,
            response_format=ChapterPlanResult,
            novel_id=novel_id,
            user_id=user_id,
            purpose="chapter_planning",
        )

        parsed = ChapterPlanResult.model_validate_json(_clean_json(response.content))

        # Update or create ChapterPlan
        plan_stmt = (
            select(ChapterPlan)
            .where(
                ChapterPlan.novel_id == novel_id,
                ChapterPlan.chapter_number == chapter_number,
            )
        )
        plan_result = await session.execute(plan_stmt)
        plan = plan_result.scalar_one_or_none()

        if plan is None:
            plan = ChapterPlan(
                novel_id=novel_id,
                chapter_number=chapter_number,
                arc_plan_id=arc.id if arc else None,
            )
            session.add(plan)

        plan.title = parsed.title
        plan.scene_outline = [s.model_dump() for s in parsed.scenes]
        plan.target_tension = parsed.target_tension
        plan.chekhov_directives = [g.description[:100] for g in guns[:5]] if guns else None
        plan.status = "planned"

        await session.flush()

        logger.info(
            "chapter_planned",
            novel_id=novel_id,
            chapter_number=chapter_number,
            scenes=len(parsed.scenes),
        )

        return plan

    async def create_bridge_chapter(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        completed_arc: ArcPlan | None = None,
    ) -> ChapterPlan:
        """Create a bridge chapter between arcs (max 3 consecutive).

        Bridge chapters give the protagonist time to consolidate after
        an arc's events and set the scene for the next arc.
        """
        # Check recent consecutive bridges
        last_plans_stmt = (
            select(ChapterPlan)
            .where(ChapterPlan.novel_id == novel_id)
            .order_by(ChapterPlan.chapter_number.desc())
            .limit(3)
        )
        last_result = await session.execute(last_plans_stmt)
        last_plans = last_result.scalars().all()

        consecutive_bridges = 0
        for p in last_plans:
            if p.is_bridge:
                consecutive_bridges += 1
            else:
                break

        if consecutive_bridges >= 3:
            msg = "Maximum 3 consecutive bridge chapters reached"
            raise ValueError(msg)

        # Derive bridge theme and title from completed arc
        bridge_theme = "character_development"
        bridge_title = f"Interlude: Chapter {chapter_number}"
        if completed_arc:
            # Use the arc's themes to inform the bridge
            if completed_arc.themes:
                first_theme = completed_arc.themes[0]
                theme_name = (
                    first_theme.get("theme", "")
                    if isinstance(first_theme, dict)
                    else str(first_theme)
                )
                if theme_name:
                    bridge_theme = f"reflection on {theme_name}"
            bridge_title = f"Interlude: After {completed_arc.title}"

        plan = ChapterPlan(
            novel_id=novel_id,
            chapter_number=chapter_number,
            arc_plan_id=None,
            is_bridge=True,
            bridge_theme=bridge_theme,
            title=bridge_title,
            target_tension=0.3,
            status="planned",
        )
        session.add(plan)
        await session.flush()

        logger.info(
            "bridge_chapter_created",
            novel_id=novel_id,
            chapter_number=chapter_number,
            bridge_theme=bridge_theme,
        )

        return plan

    async def extract_plot_threads(
        self,
        session: AsyncSession,
        novel_id: int,
        chapter_number: int,
        analysis: AnalysisResult,
        user_id: int = 0,
    ) -> list[PlotThread]:
        """Extract and track plot threads from analysis."""
        if not analysis.narrative_success or not analysis.narrative:
            return []

        # Get existing threads
        existing = await get_active_plot_threads(session, novel_id)
        existing_text = "\n".join(
            f"- [{t.status}] {t.name}: {t.description[:100]}"
            for t in existing
        ) or "None"

        # Key events from analysis
        key_events = "\n".join(
            f"- {e.description}" for e in analysis.narrative.key_events
        ) or "None"

        # Call LLM for thread extraction
        context = {
            "chapter_summary": analysis.narrative.overall_emotional_arc,
            "key_events": key_events,
            "existing_threads": existing_text,
        }

        planning_model = await self._planning_model(session, novel_id)
        system, user = PLOT_THREAD_EXTRACTION.render(**context)
        response = await self.llm.generate(
            system=system,
            user=user,
            model=planning_model,
            temperature=PLOT_THREAD_EXTRACTION.temperature,
            max_tokens=PLOT_THREAD_EXTRACTION.max_tokens,
            response_format=PlotThreadResult,
            novel_id=novel_id,
            user_id=user_id,
            purpose="plot_thread_extraction",
        )

        parsed = PlotThreadResult.model_validate_json(_clean_json(response.content))

        new_threads: list[PlotThread] = []
        for thread_data in parsed.threads:
            # Check if this thread already exists
            existing_match = next(
                (t for t in existing if t.name.lower() == thread_data.name.lower()),
                None,
            )
            if existing_match:
                # Update existing
                existing_match.description = thread_data.description
                continue

            thread = PlotThread(
                novel_id=novel_id,
                name=thread_data.name,
                description=thread_data.description,
                thread_type=thread_data.thread_type,
                introduced_at_chapter=chapter_number,
                status="active",
                related_character_ids=[],
            )
            session.add(thread)
            new_threads.append(thread)

        await session.flush()

        logger.info(
            "plot_threads_extracted",
            novel_id=novel_id,
            new_count=len(new_threads),
        )

        return new_threads

    async def _gather_arc_context(
        self,
        session: AsyncSession,
        novel_id: int,
        final: bool = False,
    ) -> dict[str, str]:
        """Gather state for arc planning prompts."""
        escalation = await get_escalation_state(session, novel_id)
        threads = await get_active_plot_threads(session, novel_id)
        guns = await get_active_chekhov_guns(session, novel_id)

        esc_state = escalation.get("state")
        scope_tier = escalation.get("scope_tier")

        # Get current chapter number
        ch_stmt = (
            select(func.max(Chapter.chapter_number))
            .where(Chapter.novel_id == novel_id)
        )
        ch_result = await session.execute(ch_stmt)
        current_ch = ch_result.scalar_one() or 0

        # All arcs with real history (approved, in_progress, completed) for context
        all_arcs_stmt = (
            select(ArcPlan)
            .where(
                ArcPlan.novel_id == novel_id,
                ArcPlan.status.in_(["approved", "in_progress", "completed"]),
            )
            .order_by(ArcPlan.arc_number.desc())
        )
        all_arcs = (await session.execute(all_arcs_stmt)).scalars().all()

        # Find the highest claimed chapter_end across ALL arcs (any status)
        # to prevent chapter range overlap
        max_end_result = await session.execute(
            select(func.max(ArcPlan.target_chapter_end))
            .where(
                ArcPlan.novel_id == novel_id,
                ArcPlan.target_chapter_end.isnot(None),
            )
        )
        max_claimed_end = max_end_result.scalar_one() or 0

        thread_text = "\n".join(
            f"- [{t.status}] {t.name}: {t.description[:150]}"
            for t in threads
        ) or "None"

        gun_text = "\n".join(
            f"- [pressure={g.pressure_score:.2f}] {g.description[:150]}"
            for g in guns
        ) or "None"

        # Load story tags for arc planning context
        tag_rows = (await session.execute(
            select(NovelTag.tag_name).where(NovelTag.novel_id == novel_id)
        )).scalars().all()
        tag_names = [
            ALL_TAGS[slug].name for slug in tag_rows if slug in ALL_TAGS
        ]
        story_tags_text = ", ".join(tag_names) if tag_names else "None specified"

        # Load custom direction from NovelSettings
        ns_row = (await session.execute(
            select(NovelSettings).where(NovelSettings.novel_id == novel_id)
        )).scalar_one_or_none()
        if ns_row and ns_row.custom_genre_conventions:
            story_tags_text += f"\nAuthor direction: {ns_row.custom_genre_conventions}"

        # Build layered arc history + chapter summaries
        arc_history_parts: list[str] = []
        outstanding_promises = "None"

        for i, past_arc in enumerate(all_arcs):
            start = past_arc.target_chapter_start or 1
            end = past_arc.target_chapter_end or start

            if i == 0:
                # Most recent arc — full detail
                if past_arc.arc_summary:
                    part = (
                        f"ARC {past_arc.arc_number}: {past_arc.title} "
                        f"(Ch {start}-{end})\n{past_arc.arc_summary}"
                    )
                else:
                    part = _format_arc_summary(past_arc)

                # Chapter summaries from this arc's range
                ch_sum_stmt = (
                    select(Chapter.chapter_number, ChapterSummary.content)
                    .join(Chapter, Chapter.id == ChapterSummary.chapter_id)
                    .where(
                        Chapter.novel_id == novel_id,
                        ChapterSummary.summary_type == "standard",
                        Chapter.chapter_number.between(start, end),
                    )
                    .order_by(Chapter.chapter_number.asc())
                )
                ch_sums = (await session.execute(ch_sum_stmt)).all()
                if ch_sums:
                    part += "\nChapter Summaries:"
                    for ch_num, content in ch_sums:
                        part += f"\n  Ch {ch_num}: {content[:500]}"

                # Outstanding promises from this arc
                if past_arc.arc_promises_outstanding:
                    promises = past_arc.arc_promises_outstanding
                    outstanding_promises = "\n".join(
                        f"- {p}" for p in promises
                    )

                arc_history_parts.append(part)

            elif i <= 2:
                # Recent arcs — summary only
                summary = past_arc.arc_summary or past_arc.description[:300]
                arc_history_parts.append(
                    f"ARC {past_arc.arc_number}: {past_arc.title} "
                    f"(Ch {start}-{end}): {summary}"
                )

            else:
                # Deep history — skeleton
                themes = ", ".join(
                    t.get("theme", "") if isinstance(t, dict) else str(t)
                    for t in (past_arc.themes or [])[:3]
                )
                arc_history_parts.append(
                    f"ARC {past_arc.arc_number}: {past_arc.title} "
                    f"(Ch {start}-{end}) — {themes}"
                )

        arc_history_text = "\n\n".join(arc_history_parts) or "No previous arcs"

        # Recent chapter summaries (fallback for mid-arc / no completed arcs)
        recent_summaries_text = "None"
        if current_ch > 0:
            sum_stmt = (
                select(Chapter.chapter_number, ChapterSummary.content)
                .join(Chapter, Chapter.id == ChapterSummary.chapter_id)
                .where(
                    Chapter.novel_id == novel_id,
                    ChapterSummary.summary_type == "standard",
                )
                .order_by(Chapter.chapter_number.desc())
                .limit(5)
            )
            summary_rows = (await session.execute(sum_stmt)).all()
            if summary_rows:
                summary_lines = []
                for ch_num, content in reversed(summary_rows):
                    summary_lines.append(f"- Ch {ch_num}: {content[:500]}")
                recent_summaries_text = "\n".join(summary_lines)

        # Load character states
        char_stmt = (
            select(Character)
            .where(Character.novel_id == novel_id)
            .order_by(Character.id)
            .limit(15)
        )
        chars = (await session.execute(char_stmt)).scalars().all()
        if chars:
            char_lines = []
            for c in chars:
                goal = c.current_goal or c.motivation or ""
                char_lines.append(
                    f"- {c.name} ({c.role}): {goal[:120]}"
                )
            character_states_text = "\n".join(char_lines)
        else:
            character_states_text = "No characters yet"

        context: dict[str, str] = {
            "current_chapter": str(current_ch),
            "escalation_phase": esc_state.current_phase if esc_state else "introduction",
            "scope_tier": scope_tier.tier_name if scope_tier else "Local",
            "active_threads": thread_text,
            "character_states": character_states_text,
            "chekhov_guns": gun_text,
            "reader_signals": "None",
            "recent_summaries": recent_summaries_text,
            "arc_history": arc_history_text,
            "outstanding_promises": outstanding_promises,
            "next_chapter_start": str(
                max(max_claimed_end + 1, current_ch + 1)
            ),
            "story_tags": story_tags_text,
            "author_guidance": "None",
        }

        if final:
            context["open_threads"] = thread_text
            context["character_arcs"] = character_states_text
            context["story_summary"] = recent_summaries_text

        return context
