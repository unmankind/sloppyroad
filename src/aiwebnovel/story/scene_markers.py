"""Scene marker extraction for inline chapter illustrations.

The chapter generation prompt instructs the LLM to emit markers like
``[SCENE: visual description]`` at narratively significant moments.
This module extracts those markers, records their paragraph positions,
and returns clean prose with all markers stripped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCENE_MARKER_RE = re.compile(r"\[SCENE:\s*(.+?)\]", re.IGNORECASE)
MAX_SCENE_MARKERS = 3


@dataclass
class SceneMarker:
    """A single scene illustration marker extracted from chapter text."""

    description: str
    paragraph_index: int


def extract_scene_markers(raw_text: str) -> tuple[str, list[SceneMarker]]:
    """Extract scene markers from raw chapter text.

    Returns:
        A tuple of (clean_text, markers) where clean_text has all
        ``[SCENE: ...]`` markers removed and triple+ newlines collapsed,
        and markers is a list of up to ``MAX_SCENE_MARKERS`` SceneMarker
        objects with paragraph positions.
    """
    markers: list[SceneMarker] = []

    for match in SCENE_MARKER_RE.finditer(raw_text):
        description = match.group(1).strip()
        if not description:
            continue

        # Count paragraph breaks (\n\n) before this marker position
        text_before = raw_text[: match.start()]
        paragraph_index = text_before.count("\n\n")

        markers.append(SceneMarker(description=description, paragraph_index=paragraph_index))

    # Cap at MAX_SCENE_MARKERS (keep first N)
    markers = markers[:MAX_SCENE_MARKERS]

    # Strip ALL markers from text (even beyond the cap)
    clean_text = SCENE_MARKER_RE.sub("", raw_text)

    # Collapse triple+ newlines to double
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

    # Strip leading/trailing whitespace
    clean_text = clean_text.strip()

    return clean_text, markers
