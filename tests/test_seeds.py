"""Tests for the diversity seed bank and convention assembly."""

import random

from aiwebnovel.story.seeds import (
    SEED_BANK,
    DiversitySeed,
    assemble_genre_conventions,
    select_seeds,
)


class TestSeedBank:
    """Tests for the seed bank data integrity."""

    def test_all_seed_ids_unique(self):
        """Every seed ID must be unique across all categories."""
        seen: set[str] = set()
        for cat_name, seeds in SEED_BANK.items():
            for seed in seeds:
                assert seed.id not in seen, (
                    f"Duplicate seed ID '{seed.id}' in category '{cat_name}'"
                )
                seen.add(seed.id)

    def test_all_categories_non_empty(self):
        """Every seed category must have at least 3 seeds."""
        for cat_name, seeds in SEED_BANK.items():
            assert len(seeds) >= 3, (
                f"Category '{cat_name}' has only {len(seeds)} seeds (need 3+)"
            )

    def test_seed_text_is_substantial(self):
        """Each seed text should be meaningful (50+ chars)."""
        for cat_name, seeds in SEED_BANK.items():
            for seed in seeds:
                assert len(seed.text) >= 50, (
                    f"Seed '{seed.id}' text is too short ({len(seed.text)} chars)"
                )

    def test_seed_categories_match_bank_keys(self):
        """Each seed's category field matches the bank key it's stored under."""
        for cat_name, seeds in SEED_BANK.items():
            for seed in seeds:
                assert seed.category == cat_name, (
                    f"Seed '{seed.id}' has category '{seed.category}' "
                    f"but is in bank key '{cat_name}'"
                )

    def test_total_seed_count(self):
        """We should have 100+ seeds total."""
        total = sum(len(seeds) for seeds in SEED_BANK.values())
        assert total >= 100, f"Only {total} seeds — need 100+"

    def test_twelve_categories_exist(self):
        """We should have exactly 12 seed categories."""
        assert len(SEED_BANK) == 12
        assert "chaos_modifier" in SEED_BANK
        assert "naming_palette" in SEED_BANK
        assert "romance_dynamic" in SEED_BANK
        assert "magic_romance_interaction" in SEED_BANK


class TestSelectSeeds:
    """Tests for the seed selection algorithm."""

    def test_returns_requested_count(self):
        seeds = select_seeds([], num_seeds=3)
        assert len(seeds) == 3

    def test_returns_fewer_if_limited(self):
        """If num_seeds exceeds available, returns what's available."""
        seeds = select_seeds([], num_seeds=200)
        assert len(seeds) >= 10  # At least one per category

    def test_no_tags_returns_diverse_categories(self):
        """Without tags, seeds should come from different categories."""
        seeds = select_seeds([], num_seeds=5, rng=random.Random(42))
        categories = {s.category for s in seeds}
        assert len(categories) >= 4, (
            f"Expected diverse categories, got: {categories}"
        )

    def test_tags_bias_toward_compatible(self):
        """Seeds compatible with author tags should be preferred."""
        # Run many times and count
        cultivation_count = 0
        runs = 50
        rng = random.Random(123)
        for _ in range(runs):
            seeds = select_seeds(["cultivation"], num_seeds=3, rng=rng)
            for s in seeds:
                if "cultivation" in s.compatible_tags:
                    cultivation_count += 1
        # With the cultivation tag, we should see compatible seeds more often
        assert cultivation_count > runs * 0.3, (
            f"Only {cultivation_count}/{runs*3} seeds were cultivation-compatible"
        )

    def test_incompatible_tags_excluded(self):
        """Seeds with incompatible tags should never be selected."""
        for _ in range(20):
            seeds = select_seeds(["grimdark"], num_seeds=5)
            for s in seeds:
                assert "grimdark" not in s.incompatible_tags, (
                    f"Seed '{s.id}' is incompatible with 'grimdark' but was selected"
                )

    def test_exclude_seeds_respected(self):
        """Explicitly excluded seed IDs should not appear."""
        # Get a seed ID to exclude
        first_seed = list(SEED_BANK.values())[0][0]
        for _ in range(10):
            seeds = select_seeds([], num_seeds=5, exclude_seeds={first_seed.id})
            for s in seeds:
                assert s.id != first_seed.id

    def test_deterministic_with_same_rng(self):
        """Same RNG seed should produce same selection."""
        seeds1 = select_seeds(["dark"], num_seeds=3, rng=random.Random(999))
        seeds2 = select_seeds(["dark"], num_seeds=3, rng=random.Random(999))
        assert [s.id for s in seeds1] == [s.id for s in seeds2]

    def test_chaos_seed_always_included(self):
        """At least one chaos_modifier seed must always be present."""
        for i in range(50):
            seeds = select_seeds([], num_seeds=4, rng=random.Random(i))
            categories = {s.category for s in seeds}
            assert "chaos_modifier" in categories, (
                f"No chaos_modifier seed in run {i}: {[s.id for s in seeds]}"
            )

    def test_default_num_seeds_is_four(self):
        """Default selection should return 4 seeds."""
        seeds = select_seeds([])
        assert len(seeds) == 4


class TestAssembleConventions:
    """Tests for convention assembly."""

    def test_includes_base_conventions(self):
        result = assemble_genre_conventions([], [])
        assert "CORE GENRE CONVENTIONS" in result
        assert "earned power growth" in result

    def test_includes_tag_directives(self):
        result = assemble_genre_conventions(["cultivation", "dark"], [])
        assert "STORY IDENTITY" in result
        assert "Cultivation" in result
        assert "Dark" in result

    def test_includes_seed_text(self):
        seed = DiversitySeed(
            id="test_seed",
            category="test",
            text="The protagonist is a sentient mushroom.",
        )
        result = assemble_genre_conventions([], [seed])
        assert "CREATIVE CONSTRAINTS" in result
        assert "sentient mushroom" in result

    def test_includes_custom_conventions(self):
        result = assemble_genre_conventions(
            [], [],
            custom_conventions="The world has no magic, only technology.",
        )
        assert "AUTHOR CUSTOMIZATIONS" in result
        assert "no magic, only technology" in result

    def test_includes_anti_repetition(self):
        result = assemble_genre_conventions(
            [], [],
            anti_repetition="- Do NOT make the protagonist age 19",
        )
        assert "AVOID THESE PATTERNS" in result
        assert "age 19" in result

    def test_empty_sections_omitted(self):
        """Empty optional sections should not appear."""
        result = assemble_genre_conventions([], [])
        assert "STORY IDENTITY" not in result
        assert "AUTHOR CUSTOMIZATIONS" not in result
        assert "AVOID THESE PATTERNS" not in result

    def test_full_assembly(self):
        """Test with all sections populated."""
        seed = DiversitySeed(
            id="test_seed",
            category="test",
            text="Test creative constraint.",
        )
        result = assemble_genre_conventions(
            author_tags=["isekai", "humorous"],
            selected_seeds=[seed],
            custom_conventions="My custom rules here.",
            anti_repetition="- Avoid dead parent trope",
        )
        assert "CORE GENRE CONVENTIONS" in result
        assert "STORY IDENTITY" in result
        assert "CREATIVE CONSTRAINTS" in result
        assert "AUTHOR CUSTOMIZATIONS" in result
        assert "AVOID THESE PATTERNS" in result

    def test_reasonable_token_size(self):
        """Full assembly shouldn't exceed ~1000 tokens."""
        seeds = select_seeds(["cultivation", "dark", "female_lead"], num_seeds=3)
        result = assemble_genre_conventions(
            author_tags=["cultivation", "dark", "female_lead"],
            selected_seeds=seeds,
            custom_conventions="A moderately long custom section with about 50 words of content.",
            anti_repetition="- Don't do X\n- Don't do Y\n- Don't do Z",
        )
        # Rough estimate: 4 chars per token
        estimated_tokens = len(result) // 4
        assert estimated_tokens < 1200, (
            f"Convention string too long: ~{estimated_tokens} tokens"
        )
