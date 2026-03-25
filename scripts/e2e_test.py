#!/usr/bin/env python3
"""End-to-end test: world generation → chapter 1 → analysis → chapter 2.

Usage:
    # Full run (new world + 2 chapters):
    .venv/bin/python scripts/e2e_test.py --label run2

    # Resume from cached world, generate chapters only:
    .venv/bin/python scripts/e2e_test.py --resume 8 --label run1_ch2

    # Skip chapter 2 (world + ch1 only):
    .venv/bin/python scripts/e2e_test.py --chapters 1

Requires: AIWN_LITELLM_API_KEY env var.
Uses in-memory SQLite. Does NOT require Redis.

Output goes to output/<label>/ (default label: "default").
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import structlog

structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
)
log = structlog.get_logger()

BASE_OUTPUT = Path(__file__).parent.parent / "output"


# ══════════════════════════════════════════════════════════════════════════
# File I/O helpers
# ══════════════════════════════════════════════════════════════════════════


def get_output_dir(label: str) -> Path:
    d = BASE_OUTPUT / label
    d.mkdir(parents=True, exist_ok=True)
    return d


def dump_json(out_dir: Path, filename: str, data: dict) -> Path:
    path = out_dir / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def dump_text(out_dir: Path, filename: str, text: str) -> Path:
    path = out_dir / filename
    with open(path, "w") as f:
        f.write(text)
    return path


def load_cached_stage(out_dir: Path, stage_order: int, stage_name: str) -> dict | None:
    path = out_dir / f"stage_{stage_order}_{stage_name}.json"
    if not path.exists():
        # Also check the legacy flat output dir
        legacy = BASE_OUTPUT / f"stage_{stage_order}_{stage_name}.json"
        if legacy.exists():
            path = legacy
        else:
            return None
    with open(path) as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════
# Chapter generation + post-chapter pipeline
# ══════════════════════════════════════════════════════════════════════════


async def generate_and_process_chapter(
    *,
    chapter_number: int,
    novel_id: int,
    user_id: int,
    session_factory,
    llm,
    settings,
    out_dir: Path,
    protag_name: str = "Protagonist",
) -> str:
    """Generate a chapter, then run analysis → validation → extraction → summarization.

    Returns the chapter text.
    """
    from sqlalchemy import select as sa_select

    from aiwebnovel.db.models import (
        Chapter,
        ChapterSummary,
        ChekhovGun,
        ForeshadowingSeed,
        StoryBibleEntry,
        TensionTracker,
    )
    from aiwebnovel.llm.provider import strip_json_fences
    from aiwebnovel.story.analyzer import ChapterAnalyzer
    from aiwebnovel.story.context import ContextAssembler
    from aiwebnovel.story.extractor import DataExtractor
    from aiwebnovel.story.generator import ChapterGenerator
    from aiwebnovel.story.validator import ChapterValidator
    from aiwebnovel.summarization.chapter_summary import ChapterSummarizer

    gen = ChapterGenerator(llm, settings)
    ctx_asm = ContextAssembler(llm, settings)
    analyzer = ChapterAnalyzer(llm, settings)
    validator = ChapterValidator()
    extractor = DataExtractor()
    summarizer = ChapterSummarizer(llm, settings)

    ch_start = time.monotonic()

    # ── 1. Assemble context ──────────────────────────────────────────
    async with session_factory() as session:
        print("  Assembling context...", end="", flush=True)
        context = await ctx_asm.build_chapter_context(
            session, novel_id, chapter_number=chapter_number,
        )
        print(f" done ({context.total_tokens} tokens, {len(context.sections)} sections)")
        for name, sec in sorted(context.sections.items(), key=lambda x: x[1].priority):
            print(f"    P{sec.priority} {name}: {sec.tokens} tokens")
        if context.truncated_sections:
            print(f"    Truncated: {context.truncated_sections}")

    # ── 2. Generate chapter ──────────────────────────────────────────
    print(f"  Generating chapter {chapter_number}...", end="", flush=True)
    chapter_text = await gen.generate(
        context=context,
        chapter_plan=None,
        novel_id=novel_id,
        user_id=user_id,
        chapter_number=chapter_number,
    )
    gen_elapsed = time.monotonic() - ch_start
    word_count = len(chapter_text.split())
    print(f" done ({gen_elapsed:.1f}s, {word_count} words)")

    # Save chapter text
    ch_path = dump_text(out_dir, f"chapter_{chapter_number}.txt", chapter_text)
    print(f"  Chapter saved to: {ch_path}")

    # ── 3. Store Chapter row in DB ───────────────────────────────────
    async with session_factory() as session:
        chapter_row = Chapter(
            novel_id=novel_id,
            chapter_number=chapter_number,
            title=f"Chapter {chapter_number}",
            chapter_text=chapter_text,
            word_count=word_count,
            status="published",
        )
        session.add(chapter_row)
        await session.flush()
        chapter_id = chapter_row.id
        await session.commit()
    print(f"  Chapter row saved (id={chapter_id})")

    # ── 4. Post-chapter analysis (narrative + system, concurrent) ────
    print("  Running post-chapter analysis...", end="", flush=True)
    analysis_start = time.monotonic()
    async with session_factory() as session:
        analysis = await analyzer.analyze(
            session, novel_id, chapter_number, chapter_text, user_id,
        )
    analysis_elapsed = time.monotonic() - analysis_start
    print(f" done ({analysis_elapsed:.1f}s)")
    print(f"    Narrative: {'OK' if analysis.narrative_success else f'FAILED: {analysis.narrative_error}'}")
    print(f"    System:    {'OK' if analysis.system_success else f'FAILED: {analysis.system_error}'}")

    # Dump analysis results
    analysis_dump = {}
    if analysis.narrative_success and analysis.narrative:
        narr = analysis.narrative
        analysis_dump["narrative"] = {
            "key_events": [e.model_dump() for e in narr.key_events],
            "tension_level": narr.tension_level,
            "tension_phase": narr.tension_phase,
            "overall_emotional_arc": narr.overall_emotional_arc,
            "new_foreshadowing_seeds": [s.model_dump() for s in narr.new_foreshadowing_seeds],
            "foreshadowing_references": [r.model_dump() for r in narr.foreshadowing_references],
            "bible_entries_to_extract": [b.model_dump() for b in narr.bible_entries_to_extract],
        }
        print(f"    Key events: {len(narr.key_events)}")
        print(f"    Tension: {narr.tension_level} ({narr.tension_phase})")
        print(f"    Foreshadowing seeds planted: {len(narr.new_foreshadowing_seeds)}")
        print(f"    Bible entries: {len(narr.bible_entries_to_extract)}")

    if analysis.system_success and analysis.system:
        sys_a = analysis.system
        analysis_dump["system"] = {
            "power_events": [e.model_dump() for e in sys_a.power_events],
            "earned_power_evaluations": [e.model_dump() for e in sys_a.earned_power_evaluations],
            "consistency_issues": [i.model_dump() for i in sys_a.consistency_issues],
            "chekhov_interactions": [c.model_dump() for c in sys_a.chekhov_interactions],
        }
        print(f"    Power events: {len(sys_a.power_events)}")
        print(f"    Earned power evals: {len(sys_a.earned_power_evaluations)}")
        print(f"    Consistency issues: {len(sys_a.consistency_issues)}")
        print(f"    Chekhov interactions: {len(sys_a.chekhov_interactions)}")

    dump_json(out_dir, f"analysis_ch{chapter_number}.json", analysis_dump)

    # ── 5. Validation ────────────────────────────────────────────────
    print("  Validating...", end="", flush=True)
    validation = await validator.validate(analysis)
    print(f" {'PASSED' if validation.passed else 'FAILED'}")
    if not validation.passed:
        for issue in validation.issues:
            print(f"    [{issue.severity}] {issue.issue_type}: {issue.description}")

    # ── 6. Extract to DB ─────────────────────────────────────────────
    print("  Extracting analysis to DB...", end="", flush=True)
    async with session_factory() as session:
        await extractor.extract_from_analysis(
            session, novel_id, chapter_number, analysis,
        )
        await session.commit()

        # Count what was extracted
        fs_count = (await session.execute(
            sa_select(ForeshadowingSeed).where(ForeshadowingSeed.novel_id == novel_id)
        )).scalars().all()
        bible_count = (await session.execute(
            sa_select(StoryBibleEntry).where(StoryBibleEntry.novel_id == novel_id)
        )).scalars().all()
        gun_count = (await session.execute(
            sa_select(ChekhovGun).where(ChekhovGun.novel_id == novel_id)
        )).scalars().all()
        tension_count = (await session.execute(
            sa_select(TensionTracker).where(TensionTracker.novel_id == novel_id)
        )).scalars().all()

    print(" done")
    print(f"    Foreshadowing seeds (total): {len(fs_count)}")
    print(f"    Story bible entries (total): {len(bible_count)}")
    print(f"    Chekhov guns (total):        {len(gun_count)}")
    print(f"    Tension entries (total):     {len(tension_count)}")

    # ── 7. Generate summaries (standard + enhanced recap) ────────────
    print("  Generating summaries...", end="", flush=True)
    summary_start = time.monotonic()
    async with session_factory() as session:
        std_summary = await summarizer.generate_standard_summary(
            session, novel_id, chapter_id, chapter_text, user_id,
            chapter_number=chapter_number,
        )
        recap = await summarizer.generate_enhanced_recap(
            session, novel_id, chapter_id, chapter_text, user_id,
            chapter_number=chapter_number,
            pov_character_name=protag_name,
        )
        await session.commit()
    summary_elapsed = time.monotonic() - summary_start
    print(f" done ({summary_elapsed:.1f}s)")
    print(f"    Standard summary: {len(std_summary.content)} chars")
    print(f"    Enhanced recap:   {len(recap.content)} chars")

    # Dump summaries
    dump_json(out_dir, f"summaries_ch{chapter_number}.json", {
        "standard_summary": std_summary.content,
        "enhanced_recap": recap.content,
    })

    total_elapsed = time.monotonic() - ch_start
    print(f"  Total chapter {chapter_number} pipeline: {total_elapsed:.1f}s")

    return chapter_text


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════


async def main() -> None:
    parser = argparse.ArgumentParser(description="AIWN 2.0 E2E Test")
    parser.add_argument(
        "--resume", type=int, default=0,
        help="Resume from stage N (load stages 0..N-1 from cached files)",
    )
    parser.add_argument(
        "--label", type=str, default="default",
        help="Output sub-directory label (e.g., run1, run2)",
    )
    parser.add_argument(
        "--chapters", type=int, default=2,
        help="Number of chapters to generate (default 2)",
    )
    parser.add_argument(
        "--tags", type=str, default="",
        help="Comma-separated tag slugs (e.g., 'cultivation,dark,female_lead')",
    )
    args = parser.parse_args()
    resume_from = args.resume
    out_dir = get_output_dir(args.label)
    author_tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    from sqlalchemy import select as sa_select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from aiwebnovel.config import Settings
    from aiwebnovel.db.models import (
        AuthorProfile,
        Base,
        Chapter,
        LLMUsageLog,
        Novel,
        NovelSettings,
        User,
        WorldBuildingStage,
    )
    from aiwebnovel.llm.provider import LLMProvider, strip_json_fences
    from aiwebnovel.story.context import ContextAssembler
    from aiwebnovel.story.pipeline import WORLD_STAGES
    from aiwebnovel.story.seeds import assemble_genre_conventions, select_seeds
    from aiwebnovel.story.tags import ALL_TAGS, validate_tags

    # ── Settings ──────────────────────────────────────────────────────
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="e2e-test-secret-key-not-for-prod",
        litellm_fallback_model="",
    )

    if not settings.litellm_api_key:
        print("ERROR: Set AIWN_LITELLM_API_KEY environment variable")
        print("  export AIWN_LITELLM_API_KEY=your-api-key-here")
        sys.exit(1)

    log.info("settings_loaded", model=settings.litellm_default_model, label=args.label)

    # ── Validate tags ──────────────────────────────────────────────
    if author_tags:
        bad = validate_tags(author_tags)
        if bad:
            print(f"ERROR: Unknown tags: {', '.join(bad)}")
            print(f"  Valid tags: {', '.join(sorted(ALL_TAGS.keys()))}")
            sys.exit(1)
        print(f"Tags: {', '.join(author_tags)}")
    else:
        print("Tags: none (random diversity seeds will be selected)")

    # ── Database ──────────────────────────────────────────────────────
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    log.info("database_ready", tables=len(Base.metadata.tables))

    # ── LLM Provider ─────────────────────────────────────────────────
    llm = LLMProvider(settings, session_factory)
    context_assembler = ContextAssembler(llm, settings)

    # ── Create test user + novel ─────────────────────────────────────
    async with session_factory() as session:
        user = User(
            email="e2e@test.com",
            username="e2e_author",
            role="author",
            is_anonymous=False,
        )
        session.add(user)
        await session.flush()

        profile = AuthorProfile(
            user_id=user.id,
            display_name="E2E Author",
            api_budget_cents=5000,
            api_spent_cents=0,
        )
        session.add(profile)

        novel = Novel(
            author_id=user.id,
            title="The Shattered Meridian",
            genre="progression_fantasy",
            status="skeleton_pending",
        )
        session.add(novel)
        await session.flush()

        novel_settings = NovelSettings(
            novel_id=novel.id,
            planning_mode="autonomous",
            pov_mode="single",
        )
        session.add(novel_settings)
        await session.commit()

        novel_id = novel.id
        user_id = user.id
        log.info("test_data_created", user_id=user_id, novel_id=novel_id)

    # ══════════════════════════════════════════════════════════════════
    # WORLD GENERATION
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    if resume_from > 0:
        print(f"WORLD GENERATION — resuming from stage {resume_from}")
    else:
        print("WORLD GENERATION (8 stages) — live output per stage")
    print(f"Output: {out_dir}")
    print("=" * 70)

    total_start = time.monotonic()
    stages_completed: list[str] = []
    stage_data: dict[str, dict] = {}

    # ── Assemble genre conventions with diversity seeds ─────────
    selected_seeds = select_seeds(author_tags, num_seeds=3)
    genre_conventions = assemble_genre_conventions(
        author_tags=author_tags,
        selected_seeds=selected_seeds,
    )
    print(f"\nDiversity seeds selected: {[s.id for s in selected_seeds]}")
    print(f"Convention string: {len(genre_conventions)} chars (~{len(genre_conventions)//4} tokens)")
    conv_path = dump_json(out_dir, "genre_conventions.json", {
        "author_tags": author_tags,
        "seed_ids": [s.id for s in selected_seeds],
        "seed_texts": [s.text for s in selected_seeds],
        "full_conventions": genre_conventions,
    })
    print(f"Conventions dumped to: {conv_path}\n")

    async with session_factory() as session:
        # ── Load cached stages if resuming ────────────────────────────
        if resume_from > 0:
            for i, (sname, stemplate) in enumerate(WORLD_STAGES[:resume_from]):
                cached = load_cached_stage(out_dir, i, sname)
                if cached is None:
                    print(f"ERROR: Cannot resume — missing stage_{i}_{sname}.json in {out_dir} or output/")
                    sys.exit(1)

                parsed_data = cached["parsed_data"]

                stage_record = WorldBuildingStage(
                    novel_id=novel_id,
                    stage_order=i,
                    stage_name=sname,
                    prompt_used="(loaded from cache)",
                    raw_response=cached.get("raw_response", ""),
                    parsed_data=parsed_data,
                    model_used=cached.get("model_used", "cached"),
                    token_count=cached.get("token_count", 0),
                    status="complete",
                )
                session.add(stage_record)
                stages_completed.append(sname)
                stage_data[sname] = parsed_data
                print(f"  [cached] Stage {i}: {sname} ({cached.get('token_count', '?')} tokens)")

            await session.flush()
            await session.commit()
            print()

        # ── Generate remaining stages ─────────────────────────────────
        for stage_order, (stage_name, template) in enumerate(WORLD_STAGES):
            if stage_order < resume_from:
                continue

            print(f"{'─' * 70}")
            print(f"Stage {stage_order}/{len(WORLD_STAGES)-1}: {stage_name}")
            print(f"{'─' * 70}")

            stage_start = time.monotonic()

            try:
                world_ctx = await context_assembler.build_world_context(
                    session, novel_id, stage_order,
                )
                prior_context = world_ctx["prior_context"]
                prior_tokens = len(prior_context) // 4
                print(f"  Prior context: ~{prior_tokens} tokens")

                system_prompt, user_prompt = template.render(
                    prior_context=prior_context,
                    genre_conventions=genre_conventions,
                )
                prompt_tokens_est = (len(system_prompt) + len(user_prompt)) // 4
                print(f"  Prompt size: ~{prompt_tokens_est} tokens (system+user)")
                print(f"  Max tokens: {template.max_tokens}")
                print(f"  Calling LLM...", end="", flush=True)

                response = await llm.generate(
                    system=system_prompt,
                    user=user_prompt,
                    temperature=template.temperature,
                    max_tokens=template.max_tokens,
                    response_format=template.response_parser,
                    novel_id=novel_id,
                    user_id=user_id,
                    purpose=f"world_{stage_name}",
                )

                stage_elapsed = time.monotonic() - stage_start
                total_tokens = response.prompt_tokens + response.completion_tokens
                print(f" done ({stage_elapsed:.1f}s)")
                print(f"  Tokens: {response.prompt_tokens} prompt + {response.completion_tokens} completion = {total_tokens}")
                print(f"  Cost: {response.cost_cents:.4f} cents")
                print(f"  Model: {response.model}")

                parsed_data = {}
                if template.response_parser:
                    parsed = template.response_parser.model_validate_json(
                        strip_json_fences(response.content),
                    )
                    parsed_data = parsed.model_dump()

                stage_record = WorldBuildingStage(
                    novel_id=novel_id,
                    stage_order=stage_order,
                    stage_name=stage_name,
                    prompt_used=user_prompt,
                    raw_response=response.content,
                    parsed_data=parsed_data,
                    model_used=response.model,
                    token_count=total_tokens,
                    status="complete",
                )
                session.add(stage_record)
                await session.flush()
                await session.commit()

                stage_dump = {
                    "stage_name": stage_name,
                    "stage_order": stage_order,
                    "token_count": total_tokens,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "cost_cents": response.cost_cents,
                    "model_used": response.model,
                    "elapsed_seconds": round(stage_elapsed, 1),
                    "parsed_data": parsed_data,
                    "raw_response": response.content,
                }
                out_path = dump_json(out_dir, f"stage_{stage_order}_{stage_name}.json", stage_dump)
                print(f"  Output: {out_path}")

                stages_completed.append(stage_name)
                stage_data[stage_name] = parsed_data

                _print_stage_highlights(stage_name, parsed_data)

            except Exception as exc:
                stage_elapsed = time.monotonic() - stage_start
                print(f" FAILED ({stage_elapsed:.1f}s)")
                print(f"  Error: {exc}")
                import traceback
                traceback.print_exc()

                if "response" in dir():
                    err_dump = {
                        "stage_name": stage_name,
                        "stage_order": stage_order,
                        "error": str(exc),
                        "raw_response": getattr(response, "content", None),
                    }
                    dump_json(out_dir, f"stage_{stage_order}_{stage_name}_ERROR.json", err_dump)

                print(f"\nCompleted {len(stages_completed)}/8 stages before failure.")
                break

    # ── World summary ─────────────────────────────────────────────────
    total_elapsed = time.monotonic() - total_start
    print(f"\n{'=' * 70}")
    print(f"WORLD GENERATION {'COMPLETE' if len(stages_completed) == 8 else 'INCOMPLETE'}")
    print(f"{'=' * 70}")
    print(f"Stages: {len(stages_completed)}/8 in {total_elapsed:.1f}s")
    print(f"Completed: {', '.join(stages_completed)}")

    async with session_factory() as session:
        logs = (await session.execute(
            sa_select(LLMUsageLog).where(LLMUsageLog.novel_id == novel_id)
        )).scalars().all()

        total_cost_cents = sum(l.cost_cents for l in logs)
        total_prompt = sum(l.prompt_tokens for l in logs)
        total_completion = sum(l.completion_tokens for l in logs)
        print(f"\nTotal cost: {total_cost_cents:.2f} cents (${total_cost_cents/100:.4f})")
        print(f"Total tokens: {total_prompt} prompt + {total_completion} completion = {total_prompt + total_completion}")

        author = (await session.execute(
            sa_select(AuthorProfile).where(AuthorProfile.user_id == user_id)
        )).scalar_one()
        print(f"Budget spent: {author.api_spent_cents:.2f} / {author.api_budget_cents} cents")

    dump_json(out_dir, "e2e_world.json", stage_data)
    print(f"\nCombined world: {out_dir / 'e2e_world.json'}")

    if len(stages_completed) < 8:
        sys.exit(1)

    print(f"\nALL 8 WORLD STAGES PASSED")

    # ══════════════════════════════════════════════════════════════════
    # SEED RELATIONAL DATA
    # ══════════════════════════════════════════════════════════════════
    from aiwebnovel.db.models import (
        Character,
        EscalationState,
        PowerSystem,
        Region,
        ScopeTier,
    )

    print("\n" + "=" * 70)
    print("SEEDING RELATIONAL DATA FROM WORLD STAGES")
    print("=" * 70)

    protag_name = "Protagonist"
    async with session_factory() as session:
        ps_data = stage_data.get("power_system", {})
        if ps_data:
            ps = PowerSystem(
                novel_id=novel_id,
                system_name=ps_data.get("system_name", "Unknown"),
                core_mechanic=ps_data.get("core_mechanic", ""),
                energy_source=ps_data.get("energy_source", ""),
                advancement_mechanics=ps_data.get("advancement_mechanics", {}),
                hard_limits=[str(x) for x in ps_data.get("hard_limits", [])],
                soft_limits=[str(x) for x in ps_data.get("soft_limits", [])],
                power_ceiling=str(ps_data.get("power_ceiling", "")),
            )
            session.add(ps)
            print(f"  PowerSystem: {ps.system_name}")

        cosmo = stage_data.get("cosmology", {})
        tiers = cosmo.get("reality_tiers", [])
        if tiers:
            tier_obj = ScopeTier(
                novel_id=novel_id,
                tier_order=1,
                tier_name=tiers[0].get("tier_name", "Local"),
                description=tiers[0].get("description", "Starting tier"),
            )
            session.add(tier_obj)
            await session.flush()

            esc = EscalationState(
                novel_id=novel_id,
                current_tier_id=tier_obj.id,
                current_phase="introduction",
                tension_level=0.3,
                activated_at_chapter=1,
            )
            session.add(esc)
            print(f"  ScopeTier: {tier_obj.tier_name}, EscalationState: introduction")

        geo = stage_data.get("geography", {})
        for r in geo.get("regions", [])[:5]:
            region = Region(
                novel_id=novel_id,
                name=r.get("name", "Unknown"),
                description=r.get("description", "")[:500],
                revealed_at_chapter=1,
            )
            session.add(region)
        region_count = min(len(geo.get("regions", [])), 5)
        print(f"  Regions: {region_count}")

        protag = stage_data.get("protagonist", {})
        if protag:
            protag_name = protag.get("name", "Protagonist")
            motivation = protag.get("motivation", {})
            motivation_str = ""
            if isinstance(motivation, dict):
                motivation_str = motivation.get("surface_motivation", "")
            elif isinstance(motivation, str):
                motivation_str = motivation

            char = Character(
                novel_id=novel_id,
                name=protag_name,
                role="protagonist",
                description=protag.get("background", "")[:500],
                personality_traits=protag.get("personality", {}).get("core_traits", []),
                motivation=motivation_str,
                background=protag.get("background", "")[:500],
                introduced_at_chapter=1,
                is_alive=True,
            )
            session.add(char)
            print(f"  Protagonist: {char.name}")

        antag_data = stage_data.get("antagonists", {})
        for a in antag_data.get("antagonists", []):
            char = Character(
                novel_id=novel_id,
                name=a.get("name", "Unknown"),
                role="antagonist",
                description=str(a.get("motivation", ""))[:500],
                introduced_at_chapter=1,
                is_alive=True,
            )
            session.add(char)
        antag_count = len(antag_data.get("antagonists", []))
        print(f"  Antagonists: {antag_count}")

        cast_data = stage_data.get("supporting_cast", {})
        for c in cast_data.get("characters", []):
            char = Character(
                novel_id=novel_id,
                name=c.get("name", "Unknown"),
                role=c.get("role", "supporting"),
                description=str(c.get("narrative_purpose", ""))[:500],
                introduced_at_chapter=1,
                is_alive=True,
            )
            session.add(char)
        cast_count = len(cast_data.get("characters", []))
        print(f"  Supporting cast: {cast_count}")

        await session.commit()
        print("  Relational data seeded.")

    # ══════════════════════════════════════════════════════════════════
    # CHAPTER GENERATION LOOP
    # ══════════════════════════════════════════════════════════════════
    num_chapters = args.chapters

    for ch_num in range(1, num_chapters + 1):
        print("\n" + "=" * 70)
        print(f"CHAPTER {ch_num} — FULL PIPELINE")
        print("=" * 70)

        await generate_and_process_chapter(
            chapter_number=ch_num,
            novel_id=novel_id,
            user_id=user_id,
            session_factory=session_factory,
            llm=llm,
            settings=settings,
            out_dir=out_dir,
            protag_name=protag_name,
        )

    # ══════════════════════════════════════════════════════════════════
    # FINAL COST SUMMARY
    # ══════════════════════════════════════════════════════════════════
    async with session_factory() as session:
        logs = (await session.execute(
            sa_select(LLMUsageLog).where(LLMUsageLog.novel_id == novel_id)
        )).scalars().all()

        total_cost_cents = sum(l.cost_cents for l in logs)
        total_prompt = sum(l.prompt_tokens for l in logs)
        total_completion = sum(l.completion_tokens for l in logs)

        author = (await session.execute(
            sa_select(AuthorProfile).where(AuthorProfile.user_id == user_id)
        )).scalar_one()

    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"  Label: {args.label}")
    print(f"  Output: {out_dir}")
    print(f"  World stages: {len(stages_completed)}/8")
    print(f"  Chapters generated: {num_chapters}")
    print(f"  Total cost: {total_cost_cents:.2f} cents (${total_cost_cents/100:.4f})")
    print(f"  Total tokens: {total_prompt} prompt + {total_completion} completion = {total_prompt + total_completion}")
    print(f"  Budget spent: {author.api_spent_cents:.2f} / {author.api_budget_cents} cents")

    print("\n" + "=" * 70)
    print("ALL E2E TESTS PASSED")
    print("=" * 70)

    await engine.dispose()


def _print_stage_highlights(stage_name: str, data: dict) -> None:
    """Print a few interesting bits from the parsed data."""
    if stage_name == "cosmology":
        forces = data.get("fundamental_forces", [])
        if forces:
            print(f"  Highlights: Forces={[f.get('name', '?') for f in forces]}")
        tiers = data.get("reality_tiers", [])
        if tiers:
            print(f"             Tiers={[t.get('tier_name', '?') for t in tiers]}")

    elif stage_name == "power_system":
        print(f"  Highlights: System={data.get('system_name', '?')}")
        ranks = data.get("ranks", [])
        if ranks:
            print(f"             Ranks({len(ranks)})={[r.get('rank_name', '?') for r in ranks]}")
        disciplines = data.get("disciplines", [])
        if disciplines:
            print(f"             Disciplines={[d.get('name', '?') for d in disciplines]}")

    elif stage_name == "geography":
        regions = data.get("regions", [])
        if regions:
            detailed = [r.get("name", "?") for r in regions if not r.get("stub")]
            stubs = [r.get("name", "?") for r in regions if r.get("stub")]
            print(f"  Highlights: Detailed={detailed}")
            if stubs:
                print(f"             Stubs={stubs}")

    elif stage_name == "protagonist":
        print(f"  Highlights: {data.get('name', '?')}, age {data.get('age', '?')}")
        motivation = data.get("motivation", {})
        if isinstance(motivation, dict):
            print(f"             Surface: {motivation.get('surface_motivation', '?')}")

    elif stage_name == "antagonists":
        antags = data.get("antagonists", [])
        if antags:
            print(f"  Highlights: {[a.get('name', '?') for a in antags]}")

    elif stage_name == "supporting_cast":
        cast = data.get("characters", [])
        if cast:
            print(f"  Highlights: {[c.get('name', '?') for c in cast]}")


if __name__ == "__main__":
    asyncio.run(main())
