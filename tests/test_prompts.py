"""Tests for prompt templates.

Verifies that all templates render correctly, have required fields,
and encode genre-specific content.
"""

from __future__ import annotations

import pytest

from aiwebnovel.llm.prompts import (
    ALL_TEMPLATES,
    ANTAGONISTS,
    ARC_PLANNING,
    CHAPTER_GENERATION,
    COSMOLOGY,
    CURRENT_STATE,
    FINAL_ARC_PLANNING,
    GEOGRAPHY,
    HISTORY,
    NARRATIVE_ANALYSIS,
    POWER_SYSTEM,
    PROTAGONIST,
    SUPPORTING_CAST,
    SYSTEM_ANALYSIS,
    PromptTemplate,
)

# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


EXPECTED_TEMPLATE_NAMES = [
    "cosmology",
    "power_system",
    "geography",
    "history",
    "current_state",
    "protagonist",
    "antagonists",
    "supporting_cast",
    "arc_planning",
    "arc_revision",
    "chapter_planning",
    "plot_thread_extraction",
    "chapter_generation",
    "narrative_analysis",
    "system_analysis",
    "standard_summary",
    "arc_summary",
    "enhanced_recap",
    "final_arc_planning",
    "character_portrait",
    "cover_art",
    "map_prompt",
    "novel_synopsis",
    "novel_title",
    "scene_illustration",
    "oracle_question_filter",
    "butterfly_choice_generator",
]


class TestAllTemplatesRegistry:
    def test_all_templates_registered(self) -> None:
        for name in EXPECTED_TEMPLATE_NAMES:
            assert name in ALL_TEMPLATES, f"Template {name!r} not in ALL_TEMPLATES"

    def test_no_extra_templates(self) -> None:
        for name in ALL_TEMPLATES:
            assert name in EXPECTED_TEMPLATE_NAMES, f"Unexpected template {name!r}"

    def test_count(self) -> None:
        assert len(ALL_TEMPLATES) == 27


# ═══════════════════════════════════════════════════════════════════════════
# STRUCTURE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestTemplateStructure:
    @pytest.mark.parametrize("name", EXPECTED_TEMPLATE_NAMES)
    def test_has_required_fields(self, name: str) -> None:
        t = ALL_TEMPLATES[name]
        assert isinstance(t, PromptTemplate)
        assert t.name == name
        assert t.system_prompt, f"{name} has empty system_prompt"
        assert t.user_template, f"{name} has empty user_template"
        assert t.temperature > 0
        assert t.max_tokens > 0

    @pytest.mark.parametrize("name", EXPECTED_TEMPLATE_NAMES)
    def test_renders_without_error(self, name: str) -> None:
        t = ALL_TEMPLATES[name]
        # Render with dummy context for all possible placeholders
        system, user = t.render(
            prior_context="Test context",
            genre_conventions="Test conventions",
            chapter_number="1",
            novel_title="Test Novel",
            chapter_text="Chapter text here",
            chapter_plan_summary="Plan summary",
            current_tier_name="Local",
            tier_order="1",
            current_phase="buildup",
            target_tension_range="0.5-0.7",
            planted_seeds="None yet",
            power_system_name="Qi",
            core_mechanic="Absorb qi",
            hard_limits="None",
            protagonist_name="Kael",
            current_rank="Rank 1",
            rank_order="1",
            total_ranks="10",
            primary_discipline="Water",
            advancement_progress="30%",
            bottleneck_description="Qi deviation",
            abilities_with_proficiency="Qi Shield (novice)",
            recent_summaries="None",
            bible_entries="None",
            active_guns="None",
            chapter_title="The Beginning",
            world_context="Fantasy world",
            power_context="Power system",
            escalation_context="Rising tension",
            enhanced_recap="Last chapter recap",
            story_bible_entries="Bible entries",
            chapter_plan="Chapter plan",
            perspective_filter="POV filter",
            reader_influence="Reader signals",
            chekhov_directives="Gun directives",
            target_word_count="4000",
            target_tension="0.6",
            current_chapter="10",
            escalation_phase="buildup",
            scope_tier="Local",
            active_threads="Thread list",
            character_states="Character states",
            chekhov_guns="Gun list",
            reader_signals="Signals",
            previous_arc_summary="Previous arc",
            current_arc_plan="Arc plan",
            author_notes="Notes",
            arc_title="The Trial",
            arc_description="Description",
            arc_position="50%",
            relevant_arc_events="Events",
            pov_character="Kael",
            tension_target="0.6",
            chapter_summary="Summary",
            key_events="Events",
            existing_threads="Threads",
            arc_plan="Plan",
            chapter_summaries="Summaries",
            pov_character_name="Kael",
            scene_character_names="Kael, Mira",
            open_threads="Open threads",
            character_arcs="Arcs",
            story_summary="Story so far",
            character_description="Young warrior",
            art_style="Fantasy",
            geography_description="Mountain region",
            regions="Region list",
            scene_description="Battle scene",
            characters="Kael, enemy",
            mood="Tense",
            question="What is the crystal?",
            story_state="Mid-story",
            narrative_state="Rising action",
            active_themes="Power, sacrifice",
            protagonist_state="Exhausted but determined",
            protagonist_context="Kael, 19, warrior from the eastern wastes",
            cast_context="Mira (ally): healer, Voss (rival): swordsman",
        )
        assert isinstance(system, str)
        assert isinstance(user, str)
        assert len(system) > 0
        assert len(user) > 0


# ═══════════════════════════════════════════════════════════════════════════
# WORLD PIPELINE TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════


class TestWorldPipelineTemplates:
    def test_cosmology_config(self) -> None:
        assert COSMOLOGY.temperature == 0.95
        assert COSMOLOGY.max_tokens == 8000
        assert COSMOLOGY.response_parser is not None

    def test_power_system_config(self) -> None:
        assert POWER_SYSTEM.temperature == 0.95
        assert POWER_SYSTEM.max_tokens == 8000

    def test_geography_config(self) -> None:
        assert GEOGRAPHY.temperature == 0.7
        assert GEOGRAPHY.max_tokens == 8000

    def test_history_config(self) -> None:
        assert HISTORY.temperature == 0.7
        assert HISTORY.max_tokens == 8000

    def test_current_state_config(self) -> None:
        assert CURRENT_STATE.temperature == 0.7
        assert CURRENT_STATE.max_tokens == 8000

    def test_protagonist_config(self) -> None:
        assert PROTAGONIST.temperature == 0.95
        assert PROTAGONIST.max_tokens == 8000

    def test_antagonists_config(self) -> None:
        assert ANTAGONISTS.temperature == 0.8
        assert ANTAGONISTS.max_tokens == 8000

    def test_supporting_cast_config(self) -> None:
        assert SUPPORTING_CAST.temperature == 0.8
        assert SUPPORTING_CAST.max_tokens == 8000

    def test_world_templates_have_json_system_prompt(self) -> None:
        world_templates = [
            COSMOLOGY, POWER_SYSTEM, GEOGRAPHY, HISTORY,
            CURRENT_STATE, PROTAGONIST, ANTAGONISTS, SUPPORTING_CAST,
        ]
        for t in world_templates:
            assert "JSON" in t.system_prompt or "json" in t.system_prompt.lower(), (
                f"{t.name} system prompt should mention JSON"
            )


# ═══════════════════════════════════════════════════════════════════════════
# CHAPTER GENERATION
# ═══════════════════════════════════════════════════════════════════════════


class TestChapterGenerationTemplate:
    def test_includes_anti_patterns(self) -> None:
        assert "DO NOT" in CHAPTER_GENERATION.system_prompt
        assert "unearned power" in CHAPTER_GENERATION.system_prompt.lower()
        assert "info-dump" in CHAPTER_GENERATION.system_prompt.lower()

    def test_includes_key_context_sections(self) -> None:
        assert "WORLD CONTEXT" in CHAPTER_GENERATION.user_template
        assert "POWER SYSTEM CONTEXT" in CHAPTER_GENERATION.user_template
        assert "ESCALATION CONTEXT" in CHAPTER_GENERATION.user_template
        assert "RECAP" in CHAPTER_GENERATION.user_template
        assert "STORY BIBLE" in CHAPTER_GENERATION.user_template
        assert "CHAPTER PLAN" in CHAPTER_GENERATION.user_template
        assert "PERSPECTIVE" in CHAPTER_GENERATION.user_template
        assert "READER INFLUENCE" in CHAPTER_GENERATION.user_template
        assert "PROTAGONIST" in CHAPTER_GENERATION.user_template
        assert "CAST" in CHAPTER_GENERATION.user_template
        assert "CHEKHOV" in CHAPTER_GENERATION.user_template

    def test_no_response_parser(self) -> None:
        assert CHAPTER_GENERATION.response_parser is None

    def test_max_tokens(self) -> None:
        assert CHAPTER_GENERATION.max_tokens == 12000


# ═══════════════════════════════════════════════════════════════════════════
# ANALYSIS TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════


class TestSceneMarkerInstruction:
    """Test that chapter generation prompt includes scene marker instruction."""

    def test_scene_marker_instruction_present(self) -> None:
        assert "SCENE ILLUSTRATIONS" in CHAPTER_GENERATION.system_prompt

    def test_scene_marker_format_documented(self) -> None:
        assert "[SCENE:" in CHAPTER_GENERATION.system_prompt

    def test_scene_marker_cap_mentioned(self) -> None:
        assert "up to 3" in CHAPTER_GENERATION.system_prompt


class TestAnalysisTemplates:
    def test_narrative_analysis_has_parser(self) -> None:
        from aiwebnovel.llm.parsers import NarrativeAnalysisResult
        assert NARRATIVE_ANALYSIS.response_parser is NarrativeAnalysisResult

    def test_system_analysis_has_parser(self) -> None:
        from aiwebnovel.llm.parsers import SystemAnalysisResult
        assert SYSTEM_ANALYSIS.response_parser is SystemAnalysisResult

    def test_system_analysis_mentions_earned_power(self) -> None:
        assert (
            "Earned Power" in SYSTEM_ANALYSIS.system_prompt
            or "earned power" in SYSTEM_ANALYSIS.system_prompt.lower()
        )

    def test_system_analysis_mentions_four_rules(self) -> None:
        prompt_text = SYSTEM_ANALYSIS.system_prompt + SYSTEM_ANALYSIS.user_template
        for rule in ("Struggle", "Foundation", "Cost", "Buildup"):
            assert rule.lower() in prompt_text.lower(), f"Missing rule: {rule}"


# ═══════════════════════════════════════════════════════════════════════════
# PLANNING TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════


class TestPlanningTemplates:
    def test_arc_planning_mentions_chekhov(self) -> None:
        assert (
            "Chekhov" in ARC_PLANNING.user_template
            or "chekhov" in ARC_PLANNING.user_template.lower()
        )

    def test_final_arc_mentions_mandatory(self) -> None:
        assert "MUST" in FINAL_ARC_PLANNING.user_template
        assert "Climax" in FINAL_ARC_PLANNING.user_template
        assert "Resolution" in FINAL_ARC_PLANNING.user_template
        assert "Epilogue" in FINAL_ARC_PLANNING.user_template


# ═══════════════════════════════════════════════════════════════════════════
# RENDER
# ═══════════════════════════════════════════════════════════════════════════


class TestPromptRender:
    def test_render_fills_placeholders(self) -> None:
        system, user = COSMOLOGY.render(
            genre_conventions="Hard magic, earned growth",
            prior_context="No prior context",
        )
        assert "Hard magic, earned growth" in user
        assert "No prior context" in user

    def test_render_missing_key_uses_empty(self) -> None:
        """Missing context keys should not raise, just become empty."""
        system, user = COSMOLOGY.render(genre_conventions="Test")
        # prior_context was not provided, should be replaced with empty string
        assert isinstance(user, str)

    def test_render_returns_tuple(self) -> None:
        result = COSMOLOGY.render(genre_conventions="Test")
        assert isinstance(result, tuple)
        assert len(result) == 2
