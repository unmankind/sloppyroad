"""Genre configuration registry.

Single source of truth for genre-specific prompt text, conventions,
validation strategies, and tag/seed compatibility. All 4 genres share
the same 8-stage pipeline and Pydantic parsers — differences are in
prompt text only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageOverride:
    """Per-stage prompt addendum injected after the default stage prompt."""

    preamble: str = ""  # Replaces genre-specific framing at top of user prompt
    addendum: str = ""  # Appended to the user prompt


@dataclass(frozen=True)
class GenreConfig:
    """Frozen configuration for a single genre."""

    slug: str
    display_name: str
    genre_label: str  # Injected into prompts replacing "progression fantasy"
    base_conventions: str  # Replaces BASE_GENRE_CONVENTIONS in seeds.py
    anti_patterns: str  # Replaces _ANTI_PATTERNS in prompts.py
    validation_strategy: str  # "earned_power" | "consistency_only"
    system_analysis_addendum: str  # Genre-specific validation guidance
    stage_overrides: dict[str, StageOverride] = field(default_factory=dict)
    incompatible_tags: frozenset[str] = field(default_factory=frozenset)
    incompatible_seed_categories: frozenset[str] = field(default_factory=frozenset)
    preferred_name_styles: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Shared anti-pattern fragments
# ═══════════════════════════════════════════════════════════════════════════

_COMMON_ANTI_PATTERNS = (
    "- Info-dump worldbuilding in exposition blocks\n"
    "- Break established world rules or internal logic\n"
    "- Use modern Earth idioms, slang, or cultural references\n"
    "- Summarise when you should show\n"
    "- Resolve tension too quickly or conveniently\n"
    "- Introduce deus ex machina solutions"
)

# ═══════════════════════════════════════════════════════════════════════════
# Progression Fantasy (existing genre, moved from hardcoded strings)
# ═══════════════════════════════════════════════════════════════════════════

_PROGRESSION_FANTASY = GenreConfig(
    slug="progression_fantasy",
    display_name="Progression Fantasy",
    genre_label="progression fantasy",
    base_conventions=(
        "Progression fantasy conventions: earned power growth through struggle and "
        "sacrifice, hard magic systems with clear rules and meaningful costs, "
        "escalating scope from personal to cosmic, training arcs that show process "
        "not montage, competent protagonists with clear weaknesses, foreshadowing "
        "that rewards attentive readers.\n\n"
        "NAMING RULES (CRITICAL — violating these will cause REJECTION):\n"
        "- NEVER name a power system 'Resonance', 'Harmony', 'The Flow', "
        "'The Weave', 'Aether', 'The Balance', 'Equilibrium', or 'Essence'\n"
        "- NEVER use 'debt', 'balance', or 'equilibrium' as the core metaphor "
        "unless a creative constraint specifically demands it\n"
        "- Power system names must be SPECIFIC and INVENTED for this world — "
        "not generic fantasy terms that could appear in any novel\n"
        "- Force and energy names must be ORIGINAL — not borrowed from other "
        "fantasy settings\n"
        "- If a name sounds like it could appear in any fantasy novel, "
        "choose something weirder\n\n"
        "STORY RULES:\n"
        "- No orphan protagonists unless a seed specifically calls for it\n"
        "- No vague 'ancient evil awakening' plots\n"
        "- No protagonist names that sound like fantasy name generators "
        "(no Kael, Aethon, Lyric, etc.)\n"
        "- Make the reader say 'wait, what?' at least once per world description"
    ),
    anti_patterns=(
        "DO NOT:\n"
        "- Grant unearned power or sudden convenient abilities\n"
        f"{_COMMON_ANTI_PATTERNS}\n"
        "- Make the protagonist succeed without meaningful struggle\n"
        "- Skip training arcs or montage through advancement"
    ),
    validation_strategy="earned_power",
    system_analysis_addendum="",  # Default earned-power framework applies
    stage_overrides={
        "power_system": StageOverride(
            addendum=(
                "The power system MUST have a PROGRESSION LADDER — ranks that take "
                "genuine effort to climb. Multiple paths with synergies."
            ),
        ),
        "protagonist": StageOverride(
            addendum=(
                "The protagonist MUST start WEAK — at or near the bottom of the "
                "power hierarchy. Their path upward is the story's spine."
            ),
        ),
        "antagonists": StageOverride(
            addendum=(
                "Antagonists should be at a HIGHER power level than the protagonist. "
                "The power gap creates narrative tension."
            ),
        ),
    },
    preferred_name_styles=["melodic", "harsh", "compound", "apostrophe", "tonal"],
)


# ═══════════════════════════════════════════════════════════════════════════
# Epic / High Fantasy
# ═══════════════════════════════════════════════════════════════════════════

_EPIC_FANTASY = GenreConfig(
    slug="epic_fantasy",
    display_name="Epic Fantasy",
    genre_label="epic fantasy",
    base_conventions=(
        "Epic fantasy conventions: sweeping scope with world-shaking stakes, "
        "rich lore and deep history, complex political landscapes, quests and "
        "prophecies that span generations, magic systems rooted in world mythology, "
        "moral complexity without easy answers, ensemble casts with layered "
        "motivations, battles that feel consequential.\n\n"
        "NAMING RULES (CRITICAL — violating these will cause REJECTION):\n"
        "- NEVER use generic fantasy names: 'The Chosen One', 'Shadowlands', "
        "'Darkwood Forest', 'The Elder Council'\n"
        "- Magic system names must feel rooted in the world's culture and history\n"
        "- Place names should suggest the culture that named them\n"
        "- If a name sounds like it came from a fantasy name generator, "
        "choose something with more character\n\n"
        "STORY RULES:\n"
        "- No orphan protagonists unless a seed specifically calls for it\n"
        "- No vague 'ancient evil awakening' without specific motivation\n"
        "- Prophecies must be ambiguous enough to create real tension\n"
        "- Make the reader say 'wait, what?' at least once per world description"
    ),
    anti_patterns=(
        "DO NOT:\n"
        "- Rely on prophecy to remove character agency\n"
        f"{_COMMON_ANTI_PATTERNS}\n"
        "- Make villains evil for evil's sake — give them coherent worldviews\n"
        "- Default to medieval Europe without cultural specificity"
    ),
    validation_strategy="consistency_only",
    system_analysis_addendum=(
        "GENRE-SPECIFIC VALIDATION (Epic Fantasy):\n"
        "- Check quest consistency: are quest goals, obstacles, and stakes "
        "maintained across chapters?\n"
        "- Check character motivation alignment: do character actions follow "
        "from their established beliefs and goals?\n"
        "- Prophecy consistency: are prophecy elements handled consistently?\n"
        "- Magic should feel wondrous and costly, not systematic and gamified.\n"
        "- Do NOT score power advancement using the 4-rule earned power framework. "
        "Instead, flag any magic use that contradicts established rules."
    ),
    stage_overrides={
        "cosmology": StageOverride(
            addendum=(
                "Include divine pantheons or primal forces with their own agendas. "
                "Ancient conflicts between cosmic powers should echo in the present. "
                "Prophecy or fate should be a real force — ambiguous but potent."
            ),
        ),
        "power_system": StageOverride(
            preamble=(
                "You are building the magic system for an epic fantasy novel.\n\n"
            ),
            addendum=(
                "This is a MAGIC SYSTEM, not a progression ladder. Ranks are loose "
                "categories (apprentice, adept, master, archmage) not a numbered "
                "hierarchy to climb. Power is lore-driven: tied to ancient pacts, "
                "divine favor, bloodlines, or dangerous knowledge. Focus on what "
                "magic COSTS and what it MEANS, not how to level up."
            ),
        ),
        "geography": StageOverride(
            addendum=(
                "Include quest-worthy destinations: ancient ruins hiding forgotten "
                "power, legendary locations from history, places of pilgrimage or "
                "dread. The landscape should feel like it has stories embedded in it."
            ),
        ),
        "protagonist": StageOverride(
            addendum=(
                "The protagonist need NOT start weak. They may be competent but "
                "facing a challenge beyond their current understanding. Give them "
                "a quest or destiny that drives them forward — but make the quest's "
                "true nature uncertain. Internal conflict matters as much as external."
            ),
        ),
        "antagonists": StageOverride(
            addendum=(
                "Antagonists should represent meaningful threats through political "
                "power, ancient knowledge, or cosmic backing — not just 'higher "
                "power level'. Each antagonist should believe they are the hero of "
                "their own story."
            ),
        ),
    },
    incompatible_tags=frozenset({
        "litrpg", "system_apocalypse", "dungeon_core",
    }),
    preferred_name_styles=["melodic", "classical", "compound", "short_punchy"],
)


# ═══════════════════════════════════════════════════════════════════════════
# Sci-Fi / Space Opera
# ═══════════════════════════════════════════════════════════════════════════

_SCI_FI = GenreConfig(
    slug="sci_fi",
    display_name="Sci-Fi / Space Opera",
    genre_label="science fiction",
    base_conventions=(
        "Science fiction conventions: technology and science as narrative drivers, "
        "speculative extrapolation from known physics (or clearly defined departures), "
        "civilizations shaped by their technology, the human condition examined through "
        "the lens of the alien or the artificial, sense of wonder at scale and "
        "discovery, consequences of technological choices.\n\n"
        "NAMING RULES (CRITICAL — violating these will cause REJECTION):\n"
        "- NEVER use generic sci-fi names: 'The Federation', 'Sector 7', "
        "'Planet X', 'The Collective'\n"
        "- Ship, station, and planet names should reflect the cultures that named them\n"
        "- Technology names should suggest function or origin, not just sound cool\n"
        "- If a name sounds like it came from a sci-fi name generator, "
        "choose something more grounded\n\n"
        "STORY RULES:\n"
        "- Technology must have costs, limitations, and failure modes\n"
        "- No 'technobabble solves everything' — solutions must follow from "
        "established rules\n"
        "- Alien species must feel genuinely alien, not humans in makeup\n"
        "- Make the reader say 'wait, what?' at least once per world description"
    ),
    anti_patterns=(
        "DO NOT:\n"
        "- Hand-wave physics without establishing the rules first\n"
        f"{_COMMON_ANTI_PATTERNS}\n"
        "- Make technology magically solve plot problems without setup\n"
        "- Default to human-centric monoculture across star systems"
    ),
    validation_strategy="consistency_only",
    system_analysis_addendum=(
        "GENRE-SPECIFIC VALIDATION (Science Fiction):\n"
        "- Check technology consistency: does tech operate within established rules?\n"
        "- No hand-waving physics: if FTL/shields/weapons have defined limits, "
        "those limits must be respected.\n"
        "- Check that abilities (cybernetics, psionics, bioengineering) have "
        "established costs and limitations.\n"
        "- Do NOT score power advancement using the 4-rule earned power framework. "
        "Instead, flag any technology use that contradicts established capabilities."
    ),
    stage_overrides={
        "cosmology": StageOverride(
            preamble=(
                "You are designing the cosmology and physics of a science fiction universe.\n\n"
            ),
            addendum=(
                "Focus on physics and exotic phenomena rather than divine pantheons. "
                "What are the fundamental forces that enable FTL, energy manipulation, "
                "or other speculative technologies? Define civilization tiers based on "
                "energy harnessing capability. Reality tiers might map to spatial scale: "
                "planetary, stellar, galactic, cosmic."
            ),
        ),
        "power_system": StageOverride(
            preamble=(
                "You are building the abilities and technology system for a "
                "science fiction novel.\n\n"
            ),
            addendum=(
                "This is an ABILITIES & TECHNOLOGY system, not a magic system. "
                "Power sources include: cybernetic augmentation, psionic abilities, "
                "bioengineering, nanotech, exotic energy manipulation, or AI symbiosis. "
                "'Ranks' are capability tiers, not mystical levels. Advancement comes "
                "through research, augmentation, training, or discovery — not meditation."
            ),
        ),
        "geography": StageOverride(
            preamble=(
                "Design the STARTING LOCATION for this science fiction universe.\n\n"
            ),
            addendum=(
                "Regions may be star systems, space stations, planets, orbital "
                "habitats, or sectors of a megastructure. Use 'fog of war': detail "
                "the starting location richly, sketch nearby systems briefly, leave "
                "distant sectors as named stubs."
            ),
        ),
        "protagonist": StageOverride(
            addendum=(
                "The protagonist's capability level matters more than a 'power rank'. "
                "They may be skilled but outgunned, or have unique tech/abilities "
                "that create both opportunity and danger. Motivation should connect "
                "to the setting's technological or social tensions."
            ),
        ),
        "antagonists": StageOverride(
            addendum=(
                "Antagonists may be individuals, factions, corporations, AIs, or "
                "alien entities. Reframe 'higher power level' as 'greater resources, "
                "knowledge, or strategic position'. Each should represent a distinct "
                "type of threat."
            ),
        ),
    },
    incompatible_tags=frozenset({
        "cultivation", "eastern_fantasy", "western_fantasy",
    }),
    incompatible_seed_categories=frozenset({
        "magic_system_constraint",
    }),
    preferred_name_styles=["short_punchy", "compound", "latin_greek", "harsh"],
)


# ═══════════════════════════════════════════════════════════════════════════
# Romance Fantasy (Romantasy)
# ═══════════════════════════════════════════════════════════════════════════

_ROMANTASY = GenreConfig(
    slug="romantasy",
    display_name="Romance Fantasy",
    genre_label="romance fantasy",
    base_conventions=(
        "Romance fantasy conventions: romantic relationship as the central narrative "
        "pillar alongside worldbuilding and plot, emotional vulnerability as strength, "
        "magic systems that resonate with emotional bonds, high personal stakes "
        "woven into epic ones, dual POV or deep emotional interiority, the love "
        "interest as a fully realized character with their own arc, tension between "
        "duty and desire, found family as supporting structure.\n\n"
        "NAMING RULES (CRITICAL — violating these will cause REJECTION):\n"
        "- NEVER use generic romance-fantasy names: 'The Bond', 'Soulmate Magic', "
        "'The Fated One', 'Heartstone'\n"
        "- Names should feel evocative and textured, not tropey\n"
        "- Magic system names should suggest emotional resonance without being "
        "on-the-nose\n"
        "- If a name sounds like it came from a romance cover generator, "
        "choose something with more depth\n\n"
        "STORY RULES:\n"
        "- Romance must be EARNED through emotional development, not instant\n"
        "- Both romantic leads must have agency and their own motivations\n"
        "- The world must feel real and consequential, not just a backdrop for romance\n"
        "- Make the reader say 'wait, what?' at least once per world description"
    ),
    anti_patterns=(
        "DO NOT:\n"
        "- Reduce the love interest to a trophy or accessory\n"
        f"{_COMMON_ANTI_PATTERNS}\n"
        "- Use 'fated mates' as a substitute for relationship development\n"
        "- Make the romance feel disconnected from the plot and world"
    ),
    validation_strategy="consistency_only",
    system_analysis_addendum=(
        "GENRE-SPECIFIC VALIDATION (Romance Fantasy):\n"
        "- Check relationship consistency: are emotional states, relationship "
        "progress, and interpersonal dynamics tracked accurately?\n"
        "- Emotional state continuity: do characters' feelings follow logically "
        "from events and prior established emotional arcs?\n"
        "- Romance pacing: is the romantic development earned through scenes, "
        "not jumped via time-skips or sudden declarations?\n"
        "- Do NOT score power advancement using the 4-rule earned power framework. "
        "Instead, flag any emotional/relational inconsistencies."
    ),
    stage_overrides={
        "cosmology": StageOverride(
            addendum=(
                "The cosmology should create conditions for romantic tension. "
                "Consider: oaths or bonds that carry metaphysical weight, cosmic "
                "forces that reflect or interfere with mortal connections, prophecies "
                "about destined pairings (whether true or manipulative), or magic "
                "that reacts to proximity, trust, or betrayal between specific "
                "people. Fate and choice should coexist in productive tension."
            ),
        ),
        "power_system": StageOverride(
            addendum=(
                "The magic system should create ROMANTIC TENSION through one of "
                "these patterns (pick the most interesting for this world):\n"
                "- EMOTIONAL RESONANCE: Magic responds to emotional bonds — "
                "vulnerability unlocks power, trust amplifies it, dishonesty "
                "weakens it\n"
                "- COMPLEMENTARY SYSTEMS: The romantic leads practice fundamentally "
                "different traditions that combine in unexpected ways together\n"
                "- POWER DISPARITY: One lead is vastly more powerful — the gap "
                "creates tension, dependency, and questions of equality\n"
                "- FORBIDDEN PAIRING: Their magic types are antagonistic or taboo "
                "when combined — proximity is dangerous, separation is safe but "
                "unbearable\n"
                "- SHARED BOND: A magical link (curse, ritual, accident) connects "
                "them — proximity has mechanical effects they didn't choose\n"
                "- INDEPENDENT AXES: Magic and romance are entirely separate — "
                "love doesn't power anything, it just complicates everything\n\n"
                "Whatever pattern you choose, the magic should create reasons for "
                "the leads to be drawn together AND reasons to stay apart."
            ),
        ),
        "geography": StageOverride(
            addendum=(
                "Include locations that serve romantic narrative: courts and "
                "ballrooms for political tension, gardens and private spaces for "
                "intimate moments, dangerous wilderness that forces proximity, "
                "estates or territories that create obligation. The setting should "
                "enable and constrain the romantic dynamic."
            ),
        ),
        "protagonist": StageOverride(
            addendum=(
                "The protagonist should have emotional walls, past wounds, or "
                "trust issues that create romantic tension. Their vulnerability "
                "is as important as their strength. Give them a reason to resist "
                "the romantic connection AND a reason they can't fully walk away "
                "from it."
            ),
        ),
        "antagonists": StageOverride(
            addendum=(
                "At least one antagonist should create romantic tension: a rival "
                "for the love interest's attention, a political match that "
                "threatens the relationship, or a villain whose connection to a "
                "lead adds emotional complexity. Not all threats are physical."
            ),
        ),
        "supporting_cast": StageOverride(
            addendum=(
                "Include at least one confidant character who serves as a "
                "sounding board for the protagonist's emotional life. Include a "
                "romantic foil or contrasting relationship that highlights what "
                "makes the central romance unique."
            ),
        ),
    },
    incompatible_tags=frozenset({
        "no_romance", "grimdark",
    }),
    preferred_name_styles=["melodic", "classical", "soft_vowel", "compound"],
)


# ═══════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════

GENRE_REGISTRY: dict[str, GenreConfig] = {
    _PROGRESSION_FANTASY.slug: _PROGRESSION_FANTASY,
    _EPIC_FANTASY.slug: _EPIC_FANTASY,
    _SCI_FI.slug: _SCI_FI,
    _ROMANTASY.slug: _ROMANTASY,
}

# Default genre for novels that don't specify one
DEFAULT_GENRE = "progression_fantasy"


def get_genre_config(genre: str) -> GenreConfig:
    """Look up a GenreConfig by slug, falling back to progression fantasy."""
    return GENRE_REGISTRY.get(genre, GENRE_REGISTRY[DEFAULT_GENRE])


def get_all_genre_choices() -> list[tuple[str, str]]:
    """Return (slug, display_name) pairs for UI dropdowns."""
    return [(g.slug, g.display_name) for g in GENRE_REGISTRY.values()]
