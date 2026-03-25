"""Character identity generator.

Pre-rolls names, sex, and physical traits for characters before LLM
prompts. Uses phonetic-style name pools (not ethnic) to guarantee
diverse, non-repeating character identities across novels.

No LLM calls — pure Python random selection with ban filtering.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.story.name_pools import FIRST_NAMES, SURNAMES

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class CharacterIdentity:
    """A pre-rolled character identity."""

    first_name: str
    last_name: str
    full_name: str
    sex: str  # "female", "male", "nonbinary"
    pronouns: str  # "she/her", "he/him", "they/them"
    physical_traits: list[str]
    name_style: str  # phonetic style used


# ---------------------------------------------------------------------------
# Physical trait pools
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Baseline traits (always assigned)
# ---------------------------------------------------------------------------

_HAIR_COLOR = [
    "jet-black hair",
    "dark brown hair",
    "auburn hair",
    "copper-red hair",
    "sandy blonde hair",
    "platinum blonde hair",
    "steel-grey hair",
    "deep chestnut hair",
    "blue-black hair",
    "honey-brown hair",
    "ash-brown hair",
    "tawny hair",
    "ink-dark hair with reddish undertones",
    "sun-bleached brown hair",
    "white-blonde hair",
]

_HAIR_STYLE = [
    "cropped short",
    "kept in tight braids",
    "loose and unkempt",
    "shaved on the sides",
    "pulled into a topknot",
    "shoulder-length and wavy",
    "buzzed close to the skull",
    "long and worn in a single braid",
    "wild and curly",
    "slicked back",
    "tied in a low ponytail",
    "a tangled mess they never bother with",
]

_EYE_COLOR = [
    "dark brown eyes",
    "amber eyes",
    "grey eyes",
    "pale blue eyes",
    "green eyes",
    "hazel eyes",
    "near-black eyes",
    "warm brown eyes",
    "steel-blue eyes",
    "golden-brown eyes",
    "ice-grey eyes",
    "olive-green eyes",
    "tawny eyes",
    "deep-set dark eyes",
]

_SKIN_TONE = [
    "deep brown skin",
    "warm bronze skin",
    "pale olive skin",
    "fair freckled skin",
    "dark copper skin",
    "light brown skin",
    "ruddy weathered skin",
    "cool brown skin",
    "golden-tan skin",
    "pale skin that burns easily",
    "rich dark skin",
    "warm ochre skin",
    "sun-darkened skin",
    "ashen pale skin",
]

_HEIGHT = [
    "unusually short",
    "below average height",
    "average height",
    "tall",
    "very tall",
    "towering",
]

_BUILD = [
    "wiry",
    "lean",
    "stocky",
    "broad-shouldered",
    "heavyset",
    "rail-thin",
    "compact and muscular",
    "lanky",
    "athletic",
    "soft and round",
]

# ---------------------------------------------------------------------------
# Distinguishing marks (rare — ~30% chance per character)
# ---------------------------------------------------------------------------

_DISTINGUISHING_CHANCE = 0.3

_DISTINGUISHING = [
    # Scars & injuries
    "burn scar across the jaw",
    "a thin scar running from temple to chin",
    "a crooked nose broken and reset multiple times",
    "missing the tip of their right ear",
    "a permanent limp in the left leg",
    "a missing front tooth they never replaced",
    "prosthetic left hand",
    "three parallel claw marks scarred across the collarbone",
    "a puckered scar on the throat, as if once strangled",
    "scarred knuckles from years of fighting",
    # Body anomalies
    "heterochromatic eyes",
    "six fingers on the left hand",
    "one arm noticeably longer than the other",
    "webbed fingers on the left hand",
    "double-jointed fingers that bend unnervingly far",
    "a lazy eye that drifts when they're tired",
    "an extra row of teeth growing behind the first",
    # Skin & markings
    "vitiligo patches on arms and neck",
    "freckle-covered face and shoulders",
    "covered in faded ink markings from wrist to shoulder",
    "a birthmark shaped like a crescent on the neck",
    "skin that flushes copper when emotional",
    "ritual scarring on the scalp",
    "mottled skin with uneven pigmentation across the hands",
    "a port-wine stain covering half the forehead",
    # Presence & mannerisms
    "eyes that don't reflect light correctly",
    "voice that's oddly resonant, as if echoing",
    "unnervingly still face — rarely shows expression",
    "moves with a dancer's precision despite their bulk",
    "hands calloused in patterns that don't match any known trade",
    "always smells faintly of smoke",
    "teeth filed to points",
    "an old tattoo they can't remember getting",
    "a nervous tic — fingers constantly drumming",
    "one eye that never fully closes when they blink",
]

_PRONOUN_MAP = {
    "female": "she/her",
    "male": "he/him",
    "nonbinary": "they/them",
}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def _pick_sex(rng: random.Random) -> str:
    """Pick sex with weighted distribution (47.5/47.5/5)."""
    roll = rng.random()
    if roll < 0.475:
        return "female"
    elif roll < 0.95:
        return "male"
    else:
        return "nonbinary"


def _is_phonetic_match(name: str, banned: set[str]) -> bool:
    """Check if a name is too similar to any banned name."""
    name_lower = name.lower()
    if name_lower in banned:
        return True
    # Check if first 3 chars + last 2 chars match any banned name
    if len(name_lower) >= 4:
        prefix = name_lower[:3]
        suffix = name_lower[-2:]
        for b in banned:
            if len(b) >= 4 and b[:3] == prefix and b[-2:] == suffix:
                return True
    return False


def generate_character_identities(
    existing_names: list[str] | None = None,
    protagonist_count: int = 1,
    antagonist_count: int = 3,
    supporting_count: int = 4,
    rng: random.Random | None = None,
) -> dict[str, list[CharacterIdentity]]:
    """Pre-roll identities for all character roles.

    Args:
        existing_names: Names from prior novels to avoid.
        protagonist_count: Number of protagonists.
        antagonist_count: Number of antagonists.
        supporting_count: Number of supporting characters.
        rng: Random instance for reproducibility.

    Returns:
        Dict with keys "protagonist", "antagonist", "supporting",
        each containing a list of CharacterIdentity objects.
    """
    if rng is None:
        rng = random.Random()

    # Build ban set from existing names
    banned: set[str] = set()
    if existing_names:
        for name in existing_names:
            for part in name.lower().split():
                if len(part) >= 3:
                    banned.add(part)

    # Available styles
    styles = list(FIRST_NAMES.keys())
    surname_styles = list(SURNAMES.keys())

    # Track used styles to encourage variety
    used_styles: list[str] = []
    used_distinguishing: set[str] = set()

    def _pick_identity(role: str) -> CharacterIdentity:
        sex = _pick_sex(rng)
        pronouns = _PRONOUN_MAP[sex]

        # Pick a name style — prefer unused styles
        available_styles = [s for s in styles if s not in used_styles]
        if not available_styles:
            available_styles = styles
        style = rng.choice(available_styles)
        used_styles.append(style)

        # Pick first name from style+sex pool
        pool = FIRST_NAMES[style][sex]
        candidates = [
            n for n in pool if not _is_phonetic_match(n, banned)
        ]
        if not candidates:
            # Fallback: try any style
            for fallback_style in rng.sample(styles, len(styles)):
                candidates = [
                    n for n in FIRST_NAMES[fallback_style][sex]
                    if not _is_phonetic_match(n, banned)
                ]
                if candidates:
                    style = fallback_style
                    break
        if not candidates:
            # Last resort: use the pool without filtering
            candidates = pool

        first_name = rng.choice(candidates)
        banned.add(first_name.lower())

        # Pick surname
        sur_style = rng.choice(surname_styles)
        sur_pool = SURNAMES[sur_style]
        sur_candidates = [
            n for n in sur_pool if not _is_phonetic_match(n, banned)
        ]
        if not sur_candidates:
            sur_candidates = sur_pool
        last_name = rng.choice(sur_candidates)
        # Ban individual words of surname
        for part in last_name.lower().split():
            if len(part) >= 3:
                banned.add(part)

        full_name = f"{first_name} {last_name}"

        # Pick baseline physical traits (always present)
        hair_color = rng.choice(_HAIR_COLOR)
        hair_style = rng.choice(_HAIR_STYLE)
        eye_color = rng.choice(_EYE_COLOR)
        skin_tone = rng.choice(_SKIN_TONE)
        height = rng.choice(_HEIGHT)
        build = rng.choice(_BUILD)

        traits = [
            f"{hair_color} ({hair_style})",
            eye_color,
            skin_tone,
            height,
            build,
        ]

        # Distinguishing feature — rare (~30%), avoid repeats within novel
        if rng.random() < _DISTINGUISHING_CHANCE:
            dist_candidates = [
                d for d in _DISTINGUISHING if d not in used_distinguishing
            ]
            if not dist_candidates:
                dist_candidates = _DISTINGUISHING
            distinguishing = rng.choice(dist_candidates)
            used_distinguishing.add(distinguishing)
            traits.append(distinguishing)

        return CharacterIdentity(
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            sex=sex,
            pronouns=pronouns,
            physical_traits=traits,
            name_style=style,
        )

    result: dict[str, list[CharacterIdentity]] = {
        "protagonist": [],
        "antagonist": [],
        "supporting": [],
    }

    for _ in range(protagonist_count):
        result["protagonist"].append(_pick_identity("protagonist"))
    for _ in range(antagonist_count):
        result["antagonist"].append(_pick_identity("antagonist"))
    for _ in range(supporting_count):
        result["supporting"].append(_pick_identity("supporting"))

    return result


async def generate_character_identities_with_db(
    session: AsyncSession,
    novel_id: int,
    protagonist_count: int = 1,
    antagonist_count: int = 3,
    supporting_count: int = 4,
    rng: random.Random | None = None,
) -> dict[str, list[CharacterIdentity]]:
    """Pre-roll identities, banning names from existing novels.

    Queries the Character table for all names on the platform,
    then delegates to generate_character_identities().
    """
    from aiwebnovel.db.models import Character

    stmt = select(Character.name).where(Character.novel_id != novel_id)
    rows = (await session.execute(stmt)).scalars().all()
    existing_names = [n for n in rows if n]

    return generate_character_identities(
        existing_names=existing_names,
        protagonist_count=protagonist_count,
        antagonist_count=antagonist_count,
        supporting_count=supporting_count,
        rng=rng,
    )


def format_identities_for_prompt(
    identities: dict[str, list[CharacterIdentity]],
    role: str,
    has_custom_direction: bool = False,
) -> str:
    """Format pre-rolled identities as a prompt injection string.

    Args:
        identities: Output of generate_character_identities().
        role: "protagonist", "antagonist", or "supporting".
        has_custom_direction: When True, identities become suggestions
            that defer to the author's custom direction.

    Returns:
        A formatted string to inject into the LLM prompt.
    """
    chars = identities.get(role, [])
    if not chars:
        return ""

    if has_custom_direction:
        return _format_soft(chars, role)
    return _format_strict(chars, role)


def _format_strict(
    chars: list[CharacterIdentity], role: str,
) -> str:
    """Format identities as non-negotiable mandates (no custom direction)."""
    if role == "protagonist" and len(chars) == 1:
        c = chars[0]
        traits = ", ".join(c.physical_traits)
        return (
            "CHARACTER IDENTITY (USE EXACTLY — do NOT change name, "
            "sex, or physical appearance):\n"
            f"- Full name: {c.full_name}\n"
            f"- Sex: {c.sex.title()} ({c.pronouns})\n"
            f"- Physical: {traits}\n"
            "Build this character's personality, background, motivation, "
            "and abilities around these fixed traits. The name, sex, and "
            "appearance are NOT negotiable."
        )

    lines = [
        "CHARACTER IDENTITIES (USE EXACTLY — do NOT change names, "
        "sex, or physical appearance):"
    ]
    for i, c in enumerate(chars, 1):
        traits = ", ".join(c.physical_traits)
        lines.append(
            f"{i}. {c.full_name} — {c.sex.title()} ({c.pronouns}) — {traits}"
        )
    lines.append(
        "Build each character's personality and motivation around "
        "these fixed identities. Names, sex, and appearance are "
        "NOT negotiable."
    )
    return "\n".join(lines)


def _format_soft(
    chars: list[CharacterIdentity], role: str,
) -> str:
    """Format identities as defaults that defer to author direction."""
    if role == "protagonist" and len(chars) == 1:
        c = chars[0]
        traits = ", ".join(c.physical_traits)
        return (
            "CHARACTER IDENTITY DEFAULTS (may be overridden by Author "
            "Direction below):\n"
            f"- Suggested name: {c.full_name}\n"
            f"- Suggested sex: {c.sex.title()} ({c.pronouns})\n"
            f"- Suggested physical traits: {traits}\n"
            "If the author's custom direction describes a different "
            "character concept, species, or physical form, IGNORE these "
            "defaults and follow the author's vision. The suggested name "
            "may still be used if it fits the author's concept."
        )

    lines = [
        "CHARACTER IDENTITY DEFAULTS (may be overridden by Author "
        "Direction below):"
    ]
    for i, c in enumerate(chars, 1):
        traits = ", ".join(c.physical_traits)
        lines.append(
            f"{i}. {c.full_name} — {c.sex.title()} ({c.pronouns}) — {traits}"
        )
    lines.append(
        "These are suggested defaults. If the author's custom direction "
        "describes different characters, species, or physical forms, "
        "IGNORE these defaults and follow the author's vision. Suggested "
        "names may still be used if they fit."
    )
    return "\n".join(lines)
