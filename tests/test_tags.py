"""Tests for the tag taxonomy system."""

from aiwebnovel.story.tags import (
    ALL_TAGS,
    TAG_CATEGORIES,
    get_tag_directives,
    validate_tags,
)


def test_all_tags_have_unique_slugs():
    """Every tag slug must be unique across all categories."""
    seen: dict[str, str] = {}
    for cat_name, tag_defs in TAG_CATEGORIES.items():
        for td in tag_defs:
            assert td.slug not in seen, (
                f"Duplicate slug '{td.slug}' in category '{cat_name}' "
                f"(also in '{seen[td.slug]}')"
            )
            seen[td.slug] = cat_name


def test_all_tags_have_unique_display_names():
    """Every display name should be unique."""
    seen: dict[str, str] = {}
    for cat_name, tag_defs in TAG_CATEGORIES.items():
        for td in tag_defs:
            assert td.name not in seen, (
                f"Duplicate name '{td.name}' in '{cat_name}' and '{seen[td.name]}'"
            )
            seen[td.name] = cat_name


def test_all_tag_categories_non_empty():
    """Every category must contain at least 3 tags."""
    for cat_name, tag_defs in TAG_CATEGORIES.items():
        assert len(tag_defs) >= 3, f"Category '{cat_name}' has only {len(tag_defs)} tags"


def test_tag_definition_fields():
    """Each tag must have all required fields populated."""
    for cat_name, tag_defs in TAG_CATEGORIES.items():
        for td in tag_defs:
            assert td.name, f"Empty name in {cat_name}"
            assert td.slug, f"Empty slug in {cat_name}: {td.name}"
            assert td.category == cat_name, (
                f"Tag '{td.name}' has category '{td.category}' but is in '{cat_name}'"
            )
            assert td.description, f"Empty description for {td.name}"
            assert td.genre_directive, f"Empty genre_directive for {td.name}"
            assert len(td.genre_directive) >= 50, (
                f"Genre directive for '{td.name}' is too short ({len(td.genre_directive)} chars)"
            )


def test_all_tags_lookup_matches_categories():
    """ALL_TAGS dict should have an entry for every tag in TAG_CATEGORIES."""
    count = sum(len(tds) for tds in TAG_CATEGORIES.values())
    assert len(ALL_TAGS) == count


def test_validate_tags_accepts_valid():
    assert validate_tags(["isekai", "dark", "female_lead"]) == []


def test_validate_tags_rejects_unknown():
    invalid = validate_tags(["isekai", "FAKE_TAG", "another_bad"])
    assert "FAKE_TAG" in invalid
    assert "another_bad" in invalid
    assert "isekai" not in invalid


def test_validate_tags_empty():
    assert validate_tags([]) == []


def test_get_tag_directives_produces_text():
    result = get_tag_directives(["cultivation", "dark"])
    assert "Cultivation" in result or "cultivation" in result.lower()
    assert "dark" in result.lower() or "Dark" in result


def test_get_tag_directives_empty_for_no_tags():
    assert get_tag_directives([]) == ""


def test_get_tag_directives_ignores_invalid_slugs():
    result = get_tag_directives(["cultivation", "NOT_A_TAG"])
    assert "cultivation" in result.lower()
    assert "NOT_A_TAG" not in result


def test_total_tag_count():
    """We should have a substantial tag catalog (50+)."""
    assert len(ALL_TAGS) >= 50
