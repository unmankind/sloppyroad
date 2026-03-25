"""Anti-repetition system for world generation.

Queries previously generated worlds on the platform to build dynamic
blacklists of overused patterns (protagonist age, motivation archetype,
force count, name prefixes, etc.).
"""

from __future__ import annotations

import json
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import Novel, WorldBuildingStage

# Names that LLMs default to across providers — always banned regardless
# of whether any prior novels exist on the platform.
_HARDCODED_BANNED_NAMES: list[str] = [
    "Kael", "Marin", "Elara", "Aether", "Lyra", "Kai", "Ren", "Zara",
    "Thorne", "Vex", "Aria", "Cael", "Rowan", "Ash", "Ember", "Sage",
]

# Power system names that LLMs gravitate to — always banned.
_HARDCODED_BANNED_SYSTEM_WORDS: list[str] = [
    "Resonance", "Harmony", "The Weave", "The Flow", "Aether",
    "Equilibrium", "The Balance", "Essence", "The Veil",
]


async def build_anti_repetition_directives(
    session: AsyncSession,
    novel_id: int,
    limit: int = 10,
) -> str:
    """Query recent world generations and extract overused patterns.

    Looks at the 'protagonist' and 'cosmology' stages from up to `limit`
    other novels. Extracts structural patterns and formats them as explicit
    avoidance directives for prompt injection.

    Always includes hardcoded banned names that LLMs default to, even with
    zero prior novels on the platform.
    """
    # Fetch protagonist stages from other novels
    protag_stmt = (
        select(WorldBuildingStage)
        .where(
            WorldBuildingStage.stage_name == "protagonist",
            WorldBuildingStage.novel_id != novel_id,
            WorldBuildingStage.status == "complete",
        )
        .order_by(WorldBuildingStage.id.desc())
        .limit(limit)
    )
    protag_rows = (await session.execute(protag_stmt)).scalars().all()

    # Fetch cosmology stages from other novels
    cosmo_stmt = (
        select(WorldBuildingStage)
        .where(
            WorldBuildingStage.stage_name == "cosmology",
            WorldBuildingStage.novel_id != novel_id,
            WorldBuildingStage.status == "complete",
        )
        .order_by(WorldBuildingStage.id.desc())
        .limit(limit)
    )
    cosmo_rows = (await session.execute(cosmo_stmt)).scalars().all()

    if not protag_rows and not cosmo_rows:
        return ""

    directives: list[str] = []

    # --- Protagonist patterns ---
    ages: list[int] = []
    name_prefixes: Counter[str] = Counter()
    motivation_types: Counter[str] = Counter()
    ability_types: Counter[str] = Counter()

    for row in protag_rows:
        data = _parse_data(row.parsed_data)
        if not data:
            continue

        # Age
        age = data.get("age")
        if isinstance(age, int):
            ages.append(age)

        # Name prefix (first 3 chars of first name)
        name = data.get("name", "")
        if name and len(name) >= 3:
            prefix = name[:3].lower()
            name_prefixes[prefix] += 1

        # Motivation type — classify from surface_motivation
        motivation = data.get("motivation", {})
        if isinstance(motivation, dict):
            surface = motivation.get("surface_motivation", "")
        else:
            surface = str(motivation)
        mot_type = _classify_motivation(surface)
        if mot_type:
            motivation_types[mot_type] += 1

        # Latent ability type
        starting = data.get("starting_power", {})
        if isinstance(starting, dict):
            latent = str(starting.get("latent_abilities", ""))
        else:
            latent = ""
        ab_type = _classify_ability(latent)
        if ab_type:
            ability_types[ab_type] += 1

    # Generate age directive if one age dominates
    if ages:
        age_counter = Counter(ages)
        most_common_age, count = age_counter.most_common(1)[0]
        if count >= 2 or (len(ages) >= 3 and count / len(ages) > 0.4):
            directives.append(
                f"Do NOT make the protagonist age {most_common_age} "
                f"(used in {count} recent novels on this platform). "
                f"Choose a meaningfully different age."
            )

    # Name prefix directive
    for prefix, count in name_prefixes.most_common(3):
        if count >= 2:
            directives.append(
                f'Do NOT use names starting with "{prefix.title()}-" '
                f"(used {count} times recently)."
            )

    # Motivation directive
    for mot, count in motivation_types.most_common(2):
        if count >= 2:
            directives.append(
                f"Do NOT use '{mot}' as the protagonist's primary motivation "
                f"(used in {count} recent novels). Choose a different driver."
            )

    # Ability type directive
    for ab, count in ability_types.most_common(2):
        if count >= 2:
            directives.append(
                f"Do NOT give the protagonist a '{ab}' latent ability "
                f"(used in {count} recent novels). Choose a different gift."
            )

    # --- Cosmology patterns ---
    force_counts: Counter[int] = Counter()
    geo_prefixes: Counter[str] = Counter()

    for row in cosmo_rows:
        data = _parse_data(row.parsed_data)
        if not data:
            continue

        forces = data.get("fundamental_forces", [])
        if isinstance(forces, list):
            force_counts[len(forces)] += 1

    for row in protag_rows:
        data = _parse_data(row.parsed_data)
        if not data:
            continue
        # Extract geography-like name fragments from background
        bg = data.get("background", "")
        geo_pat = r"\b([A-Z][a-z]{2,}(?:fen|vale|wood|marsh|deep|mere|fall|hold))\b"
        for match in re.findall(geo_pat, bg):
            geo_prefixes[match.lower()] += 1

    # Force count directive
    for fcount, count in force_counts.most_common(1):
        if count >= 2:
            directives.append(
                f"Do NOT use exactly {fcount} fundamental forces "
                f"(used in {count} recent novels). Use a different number."
            )

    # Geography name directive
    for geo, count in geo_prefixes.most_common(3):
        if count >= 2:
            directives.append(
                f'Do NOT use "{geo.title()}" or similar in geography names '
                f"(used {count} times recently)."
            )

    # --- Power system & naming patterns ---
    power_stmt = (
        select(WorldBuildingStage)
        .where(
            WorldBuildingStage.stage_name == "power_system",
            WorldBuildingStage.novel_id != novel_id,
            WorldBuildingStage.status == "complete",
        )
        .order_by(WorldBuildingStage.id.desc())
        .limit(limit)
    )
    power_rows = (await session.execute(power_stmt)).scalars().all()

    system_names: list[str] = []
    for row in power_rows:
        data = _parse_data(row.parsed_data)
        if not data:
            continue
        sname = data.get("system_name", "")
        if sname:
            system_names.append(sname)

    # Extract force and energy type names from cosmology
    force_names: list[str] = []
    energy_names: list[str] = []
    for row in cosmo_rows:
        data = _parse_data(row.parsed_data)
        if not data:
            continue
        for force in data.get("fundamental_forces", []):
            if isinstance(force, dict) and force.get("name"):
                force_names.append(force["name"])
        for energy in data.get("energy_types", []):
            if isinstance(energy, dict) and energy.get("name"):
                energy_names.append(energy["name"])

    # Fetch existing novel titles
    title_stmt = (
        select(Novel.title)
        .where(
            Novel.id != novel_id,
            Novel.title.isnot(None),
            Novel.title != "Untitled World",
        )
        .limit(limit)
    )
    title_rows = (await session.execute(title_stmt)).scalars().all()
    existing_titles = [t for t in title_rows if t]

    # Power system name directives
    if system_names:
        names_csv = ", ".join(f'"{n}"' for n in system_names)
        directives.append(
            f"Do NOT name the power system any of: {names_csv} "
            f"(used in recent novels). Invent a completely original name."
        )

    # Force/energy name directives
    all_used_names = set(force_names + energy_names)
    if all_used_names:
        used_csv = ", ".join(sorted(all_used_names)[:10])
        directives.append(
            f"Do NOT name forces or energy types: {used_csv} "
            f"(used recently). Invent entirely new names."
        )

    # Title word directives — extract common words from existing titles
    if existing_titles:
        title_words: Counter[str] = Counter()
        for title in existing_titles:
            for word in title.lower().split():
                if len(word) >= 4 and word not in {"the", "with", "from", "into"}:
                    title_words[word] += 1
        overused = [
            w for w, c in title_words.most_common(5) if c >= 2
        ]
        if overused:
            overused_csv = ", ".join(f'"{w}"' for w in overused)
            directives.append(
                f"Do NOT use these words in the novel title: "
                f"{overused_csv} (overused on this platform)."
            )

    # Always inject hardcoded banned names — LLM favorites regardless of platform history
    banned_csv = ", ".join(_HARDCODED_BANNED_NAMES)
    directives.append(
        f"NEVER use any of these names (or close variants) for ANY character: "
        f"{banned_csv}. These are overused LLM defaults. Choose genuinely "
        f"original names."
    )

    # Always inject hardcoded banned power system vocabulary
    banned_sys_csv = ", ".join(
        f'"{w}"' for w in _HARDCODED_BANNED_SYSTEM_WORDS
    )
    directives.append(
        f"NEVER name the power system any of: {banned_sys_csv}. "
        f"These are generic LLM defaults. The power system name must be "
        f"SPECIFIC and ORIGINAL to this world."
    )

    return "\n".join(f"- {d}" for d in directives)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _parse_data(parsed_data: dict | str | None) -> dict | None:
    """Safely extract parsed_data as a dict."""
    if parsed_data is None:
        return None
    if isinstance(parsed_data, dict):
        return parsed_data
    if isinstance(parsed_data, str):
        try:
            return json.loads(parsed_data)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def _classify_motivation(text: str) -> str | None:
    """Classify a motivation string into a category."""
    text_lower = text.lower()
    if any(w in text_lower for w in ("mother", "father", "parent", "family death", "died")):
        return "dead family member"
    if any(w in text_lower for w in ("revenge", "avenge", "vengeance")):
        return "revenge"
    if any(w in text_lower for w in ("survival", "survive", "staying alive")):
        return "survival"
    if any(w in text_lower for w in ("curiosity", "understand", "know", "learn", "discover")):
        return "intellectual curiosity"
    if any(w in text_lower for w in ("protect", "save", "shield", "defend")):
        return "protecting loved ones"
    return None


def _classify_ability(text: str) -> str | None:
    """Classify a latent ability description into a category."""
    text_lower = text.lower()
    if any(w in text_lower for w in ("perceiv", "perception", "sense", "sight", "see", "vision")):
        return "perception-based"
    if any(w in text_lower for w in ("physical", "strength", "body", "endurance")):
        return "physical enhancement"
    if any(w in text_lower for w in ("elemental", "fire", "water", "earth", "wind")):
        return "elemental affinity"
    if any(w in text_lower for w in ("heal", "restor", "mend")):
        return "healing affinity"
    return None
