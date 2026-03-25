"""Tests for scene marker extraction."""

from __future__ import annotations

from aiwebnovel.story.scene_markers import (
    MAX_SCENE_MARKERS,
    extract_scene_markers,
)


class TestExtractSceneMarkers:
    """Test extract_scene_markers function."""

    def test_single_marker(self) -> None:
        raw = (
            "The warrior drew his sword.\n\n"
            "[SCENE: A lone warrior stands on a cliff edge,"
            " sword raised against a crimson sunset]\n\n"
            "He leapt into battle."
        )
        clean, markers = extract_scene_markers(raw)

        assert len(markers) == 1
        assert markers[0].description == (
            "A lone warrior stands on a cliff edge,"
            " sword raised against a crimson sunset"
        )
        assert markers[0].paragraph_index == 1
        assert "[SCENE:" not in clean
        assert "The warrior drew his sword." in clean
        assert "He leapt into battle." in clean

    def test_multiple_markers(self) -> None:
        raw = (
            "Paragraph one.\n\n"
            "[SCENE: First scene description]\n\n"
            "Paragraph two.\n\n"
            "Paragraph three.\n\n"
            "[SCENE: Second scene description]\n\n"
            "Paragraph four."
        )
        clean, markers = extract_scene_markers(raw)

        assert len(markers) == 2
        assert markers[0].description == "First scene description"
        assert markers[0].paragraph_index == 1
        assert markers[1].description == "Second scene description"
        assert markers[1].paragraph_index == 4

    def test_zero_markers(self) -> None:
        raw = "Just a normal paragraph.\n\nAnother paragraph."
        clean, markers = extract_scene_markers(raw)

        assert len(markers) == 0
        assert clean == raw

    def test_cap_at_max(self) -> None:
        """More than MAX_SCENE_MARKERS should keep only the first ones."""
        parts = []
        for i in range(5):
            parts.append(f"Paragraph {i}.")
            parts.append(f"[SCENE: Scene {i}]")
        parts.append("Final paragraph.")
        raw = "\n\n".join(parts)

        clean, markers = extract_scene_markers(raw)

        assert len(markers) == MAX_SCENE_MARKERS
        # First 3 kept
        assert markers[0].description == "Scene 0"
        assert markers[1].description == "Scene 1"
        assert markers[2].description == "Scene 2"
        # ALL markers stripped from text (not just first 3)
        assert "[SCENE:" not in clean

    def test_paragraph_index_accuracy(self) -> None:
        """Paragraph index should count \n\n splits before the marker."""
        raw = "P0.\n\nP1.\n\nP2.\n\n[SCENE: After third paragraph break]\n\nP3."
        clean, markers = extract_scene_markers(raw)

        assert len(markers) == 1
        assert markers[0].paragraph_index == 3

    def test_empty_description_skipped(self) -> None:
        """Markers with empty descriptions should be skipped."""
        raw = "Text before.\n\n[SCENE:   ]\n\nText after."
        clean, markers = extract_scene_markers(raw)

        assert len(markers) == 0

    def test_case_insensitive(self) -> None:
        """Markers should be matched case-insensitively."""
        raw = "Text.\n\n[scene: Lower case marker]\n\n[Scene: Mixed case]\n\n[SCENE: Upper case]"
        clean, markers = extract_scene_markers(raw)

        assert len(markers) == 3
        assert markers[0].description == "Lower case marker"
        assert markers[1].description == "Mixed case"
        assert markers[2].description == "Upper case"

    def test_triple_newlines_collapsed(self) -> None:
        """Removing markers should not leave triple+ newlines."""
        raw = "Before.\n\n[SCENE: Something dramatic]\n\nAfter."
        clean, markers = extract_scene_markers(raw)

        assert "\n\n\n" not in clean
        assert clean == "Before.\n\nAfter."

    def test_marker_at_start(self) -> None:
        """Marker at the very start of text."""
        raw = "[SCENE: Opening scene]\n\nFirst paragraph."
        clean, markers = extract_scene_markers(raw)

        assert len(markers) == 1
        assert markers[0].paragraph_index == 0
        assert clean == "First paragraph."

    def test_marker_at_end(self) -> None:
        """Marker at the very end of text."""
        raw = "Last paragraph.\n\n[SCENE: Closing scene]"
        clean, markers = extract_scene_markers(raw)

        assert len(markers) == 1
        assert markers[0].paragraph_index == 1
        assert clean == "Last paragraph."

    def test_marker_inline_with_text(self) -> None:
        """Marker embedded within a paragraph (unusual but should still work)."""
        raw = "The sky split open [SCENE: Lightning cracks the dark sky] and thunder followed."
        clean, markers = extract_scene_markers(raw)

        assert len(markers) == 1
        assert markers[0].description == "Lightning cracks the dark sky"
        assert markers[0].paragraph_index == 0
        assert "The sky split open  and thunder followed." in clean

    def test_empty_text(self) -> None:
        clean, markers = extract_scene_markers("")

        assert clean == ""
        assert markers == []

    def test_whitespace_in_description_trimmed(self) -> None:
        raw = "Text.\n\n[SCENE:   spacey description   ]\n\nMore."
        clean, markers = extract_scene_markers(raw)

        assert markers[0].description == "spacey description"
