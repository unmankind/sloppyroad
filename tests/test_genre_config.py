"""Tests for genre configuration registry and genre-aware pipeline components."""

from __future__ import annotations

import pytest

from aiwebnovel.llm.prompts import (
    CHAPTER_GENERATION,
    COSMOLOGY,
    NARRATIVE_ANALYSIS,
    POWER_SYSTEM,
    PROTAGONIST,
    SYSTEM_ANALYSIS,
)
from aiwebnovel.story.genre_config import (
    DEFAULT_GENRE,
    GENRE_REGISTRY,
    GenreConfig,
    get_all_genre_choices,
    get_genre_config,
)
from aiwebnovel.story.seeds import assemble_genre_conventions, select_seeds
from aiwebnovel.story.tags import get_tags_for_genre

# ═══════════════════════════════════════════════════════════════════════════
# GenreConfig Registry
# ═══════════════════════════════════════════════════════════════════════════


class TestGenreRegistry:
    """Tests for the genre config registry."""

    def test_registry_has_four_genres(self):
        assert len(GENRE_REGISTRY) == 4
        assert set(GENRE_REGISTRY.keys()) == {
            "progression_fantasy",
            "epic_fantasy",
            "sci_fi",
            "romantasy",
        }

    def test_all_configs_are_frozen(self):
        for slug, config in GENRE_REGISTRY.items():
            assert isinstance(config, GenreConfig)
            with pytest.raises(AttributeError):
                config.slug = "modified"  # type: ignore[misc]

    def test_all_configs_have_required_fields(self):
        for slug, config in GENRE_REGISTRY.items():
            assert config.slug == slug
            assert config.display_name
            assert config.genre_label
            assert config.base_conventions
            assert config.anti_patterns
            assert config.validation_strategy in ("earned_power", "consistency_only")

    def test_only_progression_fantasy_uses_earned_power(self):
        assert GENRE_REGISTRY["progression_fantasy"].validation_strategy == "earned_power"
        for slug in ["epic_fantasy", "sci_fi", "romantasy"]:
            assert GENRE_REGISTRY[slug].validation_strategy == "consistency_only"

    def test_non_prog_fantasy_have_validation_addendum(self):
        for slug in ["epic_fantasy", "sci_fi", "romantasy"]:
            config = GENRE_REGISTRY[slug]
            assert config.system_analysis_addendum, (
                f"{slug} should have system_analysis_addendum"
            )

    def test_get_genre_config_returns_correct(self):
        config = get_genre_config("sci_fi")
        assert config.slug == "sci_fi"
        assert config.genre_label == "science fiction"

    def test_get_genre_config_falls_back_to_default(self):
        config = get_genre_config("unknown_genre")
        assert config.slug == DEFAULT_GENRE

    def test_get_all_genre_choices(self):
        choices = get_all_genre_choices()
        assert len(choices) == 4
        slugs = [c[0] for c in choices]
        assert "progression_fantasy" in slugs
        assert "romantasy" in slugs


# ═══════════════════════════════════════════════════════════════════════════
# Genre Conventions Assembly
# ═══════════════════════════════════════════════════════════════════════════


class TestGenreConventions:
    """Tests for assemble_genre_conventions with genre param."""

    def test_progression_fantasy_uses_prog_conventions(self):
        conv = assemble_genre_conventions([], [], genre="progression_fantasy")
        assert "earned power growth" in conv.lower()

    def test_epic_fantasy_uses_epic_conventions(self):
        conv = assemble_genre_conventions([], [], genre="epic_fantasy")
        assert "sweeping scope" in conv.lower()
        assert "earned power growth" not in conv.lower()

    def test_sci_fi_uses_sci_fi_conventions(self):
        conv = assemble_genre_conventions([], [], genre="sci_fi")
        assert "technology and science" in conv.lower()

    def test_romantasy_uses_romantasy_conventions(self):
        conv = assemble_genre_conventions([], [], genre="romantasy")
        assert "romantic relationship" in conv.lower()

    def test_unknown_genre_falls_back_to_prog_fantasy(self):
        conv = assemble_genre_conventions([], [], genre="nonexistent")
        assert "earned power growth" in conv.lower()


# ═══════════════════════════════════════════════════════════════════════════
# Prompt Template Genre Label Substitution
# ═══════════════════════════════════════════════════════════════════════════


class TestPromptGenreLabel:
    """Tests that {genre_label} is substituted in prompt templates."""

    @pytest.mark.parametrize("template", [COSMOLOGY, POWER_SYSTEM, PROTAGONIST])
    def test_world_stage_templates_use_genre_label(self, template):
        system, user = template.render(
            genre_label="epic fantasy",
            genre_conventions="test",
            prior_context="test",
            character_identities="",
            novel_title_context="",
        )
        assert "epic fantasy" in system or "epic fantasy" in user

    def test_chapter_generation_uses_genre_label(self):
        system, user = CHAPTER_GENERATION.render(
            genre_label="science fiction",
            chapter_number="1",
            chapter_title="Test",
        )
        assert "science fiction" in system

    def test_narrative_analysis_uses_genre_label(self):
        system, user = NARRATIVE_ANALYSIS.render(
            genre_label="romance fantasy",
            chapter_number="1",
            novel_title="Test",
            chapter_text="Test text",
        )
        assert "romance fantasy" in system

    def test_system_analysis_uses_genre_label_and_addendum(self):
        system, user = SYSTEM_ANALYSIS.render(
            genre_label="epic fantasy",
            genre_validation_addendum="CHECK QUEST CONSISTENCY",
            chapter_number="1",
            novel_title="Test",
            chapter_text="Test text",
        )
        assert "epic fantasy" in system
        assert "CHECK QUEST CONSISTENCY" in user

    def test_no_hardcoded_progression_fantasy_in_rendered_output(self):
        """Ensure 'progression fantasy' doesn't appear when a different
        genre_label is provided."""
        for template in [COSMOLOGY, CHAPTER_GENERATION, NARRATIVE_ANALYSIS, SYSTEM_ANALYSIS]:
            system, user = template.render(
                genre_label="science fiction",
                genre_conventions="test",
                prior_context="test",
                character_identities="",
                novel_title_context="",
                chapter_number="1",
                chapter_title="Test",
                novel_title="Test",
                chapter_text="Test",
                genre_validation_addendum="",
            )
            assert "progression fantasy" not in system.lower(), (
                f"Hardcoded 'progression fantasy' in {template.name} system prompt"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Validator Genre-Aware Behavior
# ═══════════════════════════════════════════════════════════════════════════


class TestValidatorGenre:
    """Tests that the validator skips earned power for non-prog-fantasy."""

    @pytest.fixture()
    def failing_earned_power_analysis(self):
        from aiwebnovel.llm.parsers import EarnedPowerEval, SystemAnalysisResult
        from aiwebnovel.story.analyzer import AnalysisResult

        mock_ep = EarnedPowerEval(
            character_name="Test",
            event_description="Instant power-up",
            struggle_score=0.05,
            struggle_reasoning="None",
            foundation_score=0.05,
            foundation_reasoning="None",
            cost_score=0.05,
            cost_reasoning="None",
            buildup_score=0.05,
            buildup_reasoning="None",
            total_score=0.2,
            approved=False,
            reasoning="Unearned",
        )
        mock_system = SystemAnalysisResult(
            power_events=[],
            earned_power_evaluations=[mock_ep],
            ability_usages=[],
            consistency_issues=[],
            chekhov_interactions=[],
            has_critical_violations=True,
        )
        return AnalysisResult(
            system=mock_system,
            system_success=True,
            narrative_success=True,
        )

    @pytest.mark.asyncio()
    async def test_progression_fantasy_rejects_unearned_power(
        self, failing_earned_power_analysis,
    ):
        from aiwebnovel.story.validator import ChapterValidator

        validator = ChapterValidator()
        result = await validator.validate(
            failing_earned_power_analysis, genre="progression_fantasy",
        )
        assert not result.passed
        assert len(result.issues) == 1
        assert result.issues[0].issue_type == "earned_power"

    @pytest.mark.asyncio()
    @pytest.mark.parametrize("genre", ["epic_fantasy", "sci_fi", "romantasy"])
    async def test_non_prog_fantasy_skips_earned_power(
        self, failing_earned_power_analysis, genre,
    ):
        from aiwebnovel.story.validator import ChapterValidator

        validator = ChapterValidator()
        result = await validator.validate(
            failing_earned_power_analysis, genre=genre,
        )
        assert result.passed
        assert len(result.issues) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Seed Selection Genre Filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestSeedGenreFiltering:
    """Tests that select_seeds respects genre affinity."""

    def test_select_seeds_returns_seeds_for_all_genres(self):
        import random

        for genre in GENRE_REGISTRY:
            seeds = select_seeds([], genre=genre, rng=random.Random(42))
            assert len(seeds) > 0, f"No seeds selected for {genre}"

    def test_select_seeds_default_genre_is_progression_fantasy(self):
        import random

        seeds_default = select_seeds([], rng=random.Random(42))
        seeds_explicit = select_seeds(
            [], genre="progression_fantasy", rng=random.Random(42),
        )
        assert [s.id for s in seeds_default] == [s.id for s in seeds_explicit]


# ═══════════════════════════════════════════════════════════════════════════
# Tag Genre Filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestTagGenreFiltering:
    """Tests for get_tags_for_genre."""

    def test_progression_fantasy_gets_all_tags(self):
        """Prog fantasy should get all tags (it's the broadest genre)."""
        from aiwebnovel.story.tags import TAG_CATEGORIES

        prog_tags = get_tags_for_genre("progression_fantasy")
        total_prog = sum(len(t) for t in prog_tags.values())
        total_all = sum(len(t) for t in TAG_CATEGORIES.values())
        assert total_prog == total_all

    def test_sci_fi_excludes_cultivation(self):
        sci_fi_tags = get_tags_for_genre("sci_fi")
        all_slugs = [t.slug for tags in sci_fi_tags.values() for t in tags]
        assert "cultivation" not in all_slugs

    def test_epic_fantasy_excludes_litrpg(self):
        epic_tags = get_tags_for_genre("epic_fantasy")
        all_slugs = [t.slug for tags in epic_tags.values() for t in tags]
        assert "litrpg" not in all_slugs

    def test_all_genres_get_universal_tags(self):
        """Tags without genre_affinity should appear in all genres."""
        for genre in GENRE_REGISTRY:
            tags = get_tags_for_genre(genre)
            all_slugs = [t.slug for ts in tags.values() for t in ts]
            # 'dark' (tone) has no genre_affinity, should be in all
            assert "dark" in all_slugs, f"'dark' tag missing for {genre}"
