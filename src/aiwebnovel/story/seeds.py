"""Diversity seed bank and genre convention assembly.

The seed bank contains ~140 creative constraints organized into 10 categories.
Seeds are randomly selected (weighted by author tag compatibility) and injected
into world generation prompts to force structural variety between novels.

The assemble_genre_conventions() function combines:
  1. Base progression fantasy conventions
  2. Author tag directives
  3. Selected diversity seeds
  4. Custom author conventions
  5. Anti-repetition blacklist
into a single string that replaces the old hardcoded _GENRE_CONVENTIONS.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from aiwebnovel.story.tags import ALL_TAGS, get_tag_directives


@dataclass(frozen=True)
class DiversitySeed:
    """A creative constraint injected into world generation prompts."""

    id: str
    category: str
    text: str
    compatible_tags: frozenset[str] = field(default_factory=frozenset)
    incompatible_tags: frozenset[str] = field(default_factory=frozenset)
    weight: float = 1.0
    # Genre slugs this seed is compatible with. Empty = all genres.
    genre_affinity: frozenset[str] = field(default_factory=frozenset)


# ═══════════════════════════════════════════════════════════════════════════
# Base conventions (formerly hardcoded in pipeline.py)
# ═══════════════════════════════════════════════════════════════════════════

BASE_GENRE_CONVENTIONS = (
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
)


# ═══════════════════════════════════════════════════════════════════════════
# Seed Bank — ~140 seeds across 10 categories
# ═══════════════════════════════════════════════════════════════════════════

SEED_BANK: dict[str, list[DiversitySeed]] = {

    # ------------------------------------------------------------------
    # PROTAGONIST ARCHETYPE — who the main character is
    # ------------------------------------------------------------------
    "protagonist_archetype": [
        DiversitySeed(
            "protag_elderly",
            "protagonist_archetype",
            "The protagonist is over 60 years old — a retired soldier, scholar, "
            "or merchant rediscovering purpose late in life. Their body is their "
            "primary limitation, not ignorance. Wisdom competes with declining "
            "vitality. They have grandchildren, regrets, and a lifetime of compromises.",
            compatible_tags=frozenset({"older_lead"}),
            incompatible_tags=frozenset({"child_lead", "academy"}),
        ),
        DiversitySeed(
            "protag_child",
            "protagonist_archetype",
            "The protagonist is 8-12 years old, a genuine child with child reasoning. "
            "NOT an adult in a child's body. They are curious, emotionally volatile, "
            "dependent on adults, and process the world through limited experience. "
            "Their emotional world is their strength.",
            compatible_tags=frozenset({"child_lead", "academy"}),
            incompatible_tags=frozenset({"older_lead", "villain_lead", "grimdark"}),
        ),
        DiversitySeed(
            "protag_curiosity",
            "protagonist_archetype",
            "The protagonist's primary motivation is intellectual curiosity, not "
            "vengeance, survival, or personal loss. They advance because they WANT "
            "TO KNOW — they are a researcher, tinkerer, or obsessive question-asker. "
            "Their drive is understanding, and that drive sometimes puts them in danger.",
            compatible_tags=frozenset({"philosophical", "mystery"}),
        ),
        DiversitySeed(
            "protag_mother",
            "protagonist_archetype",
            "The protagonist is a mother whose children are directly at stake. Her "
            "power awakening comes BECAUSE of her maternal bond, not despite it. "
            "Protecting her family is not a weakness the plot punishes but a source "
            "of genuine strength the power system recognizes.",
            compatible_tags=frozenset({"female_lead", "found_family"}),
            incompatible_tags=frozenset({"child_lead", "nonhuman_lead"}),
        ),
        DiversitySeed(
            "protag_disabled",
            "protagonist_archetype",
            "The protagonist has a permanent physical disability that the power "
            "system CANNOT cure: blindness, deafness, paralyzed legs, a missing "
            "limb. Their advancement path must work AROUND it, making the disability "
            "a permanent feature of their combat style and daily life.",
            compatible_tags=frozenset({"dark", "philosophical"}),
        ),
        DiversitySeed(
            "protag_midrank",
            "protagonist_archetype",
            "The protagonist starts at the MIDDLE ranks of power, not the bottom. "
            "They are competent and experienced. Their crisis is stagnation and the "
            "ceiling above — a bottleneck everyone at their level faces. The story "
            "begins where most progression stories end their first arc.",
            incompatible_tags=frozenset({"child_lead"}),
        ),
        DiversitySeed(
            "protag_villain",
            "protagonist_archetype",
            "The protagonist is the villain of someone else's story. They believe "
            "they are justified. Their goals cause genuine harm to innocent people "
            "and they know it. Show why their perspective is compelling without "
            "excusing their actions. Other characters' heroism is real.",
            compatible_tags=frozenset({"villain_lead", "dark", "grimdark"}),
            incompatible_tags=frozenset({"heroic", "cozy"}),
        ),
        DiversitySeed(
            "protag_bureaucrat",
            "protagonist_archetype",
            "The protagonist is a bureaucrat, administrator, or logistics officer. "
            "Their power comes through institutional knowledge, organizational "
            "ability, and understanding how systems actually work. They fight with "
            "paperwork, regulations, and strategic resource allocation as much as "
            "with direct power.",
            compatible_tags=frozenset({"political_intrigue", "satirical"}),
        ),
        DiversitySeed(
            "protag_amnesia",
            "protagonist_archetype",
            "The protagonist wakes with significant power but NO MEMORY of who "
            "they are. Their identity IS the mystery. People recognize them — some "
            "with fear, some with love, some with hatred — and they must reconstruct "
            "who they were while deciding who they want to be.",
            compatible_tags=frozenset({"mystery"}),
        ),
        DiversitySeed(
            "protag_couple",
            "protagonist_archetype",
            "The story has TWO co-protagonists: a couple (romantic, platonic, or "
            "familial) whose arcs are inseparable. They have different power paths "
            "that complement each other. Separation is a narrative tool, not a "
            "permanent state. Their relationship IS the story's emotional core.",
            compatible_tags=frozenset({"romantic", "romance", "found_family"}),
        ),
        DiversitySeed(
            "protag_nonhuman",
            "protagonist_archetype",
            "The protagonist is non-human: a monster, spirit, golem, awakened "
            "animal, or sentient object. Their perception, priorities, and emotional "
            "range are fundamentally different from human norms. Do NOT write a "
            "human wearing a costume — commit to the alien perspective.",
            compatible_tags=frozenset({"nonhuman_lead", "monster_evolution", "dungeon_core"}),
        ),
        DiversitySeed(
            "protag_privileged",
            "protagonist_archetype",
            "The protagonist is wealthy and privileged — born into a powerful "
            "family, given every advantage. Their crisis is MORAL, not material. "
            "They have power but question its legitimacy. The story interrogates "
            "what it means to earn something when you started with everything.",
            compatible_tags=frozenset({"philosophical", "political_intrigue"}),
            incompatible_tags=frozenset({"survival"}),
        ),
        DiversitySeed(
            "protag_voluntary_regression",
            "protagonist_archetype",
            "The protagonist CHOSE to give up their power. The story begins after "
            "voluntary regression — they were strong and walked away. Now circumstances "
            "force them back, but the path is different the second time. They know "
            "what power costs because they've already paid it.",
            incompatible_tags=frozenset({"child_lead"}),
        ),
        DiversitySeed(
            "protag_teacher",
            "protagonist_archetype",
            "The protagonist is a teacher or mentor to someone MORE TALENTED than "
            "themselves. Their arc is about guiding greatness they can never match. "
            "The student surpassing the master is not a failure but the goal. Power "
            "growth happens through teaching, not just personal advancement.",
            compatible_tags=frozenset({"academy"}),
        ),
        DiversitySeed(
            "protag_greedy",
            "protagonist_archetype",
            "The protagonist's primary drive is GREED — not evil, just nakedly "
            "honest about wanting wealth, resources, and material comfort. They "
            "advance because power is profitable. Their moral compass points toward "
            "self-interest, but enlightened self-interest has surprising range.",
            compatible_tags=frozenset({"humorous", "anti_hero"}),
        ),
        DiversitySeed(
            "protag_artisan",
            "protagonist_archetype",
            "The protagonist is an artisan: smith, potter, weaver, cook, or painter. "
            "Power expresses through their craft. They do not fight — they CREATE. "
            "Their workshop is their cultivation chamber. Their masterwork is their "
            "breakthrough. Combat ability is incidental to creative excellence.",
            compatible_tags=frozenset({"craftsman", "everyday_ascendancy", "cozy"}),
        ),
        DiversitySeed(
            "protag_con_artist",
            "protagonist_archetype",
            "The protagonist is a con artist, thief, or trickster who accidentally "
            "stumbled into real power. They're used to faking competence and now must "
            "develop genuine ability while maintaining appearances. Their social "
            "skills are their most dangerous weapon.",
            compatible_tags=frozenset({"humorous", "anti_hero"}),
        ),
        DiversitySeed(
            "protag_two_souls",
            "protagonist_archetype",
            "The protagonist is two souls sharing one body, in constant negotiation. "
            "One is the original inhabitant, the other is an intruder (reincarnated, "
            "possessing spirit, or merged entity). They disagree about goals, methods, "
            "and who gets to be in charge. Internal dialogue IS external conflict.",
            compatible_tags=frozenset({"reincarnation"}),
        ),
        DiversitySeed(
            "protag_immortal_bored",
            "protagonist_archetype",
            "The protagonist is immortal and profoundly bored. They have already "
            "reached the peak and found it empty. Power is meaningless to them — "
            "MEANING is the quest. They are searching for something that makes "
            "eternity worth enduring. A new practitioner's wonder is what they've lost.",
            compatible_tags=frozenset({"philosophical"}),
            incompatible_tags=frozenset({"child_lead"}),
        ),
        DiversitySeed(
            "protag_healer",
            "protagonist_archetype",
            "The protagonist's path is healing and restoration, not combat. They "
            "cannot kill effectively and do not want to. Their power grows through "
            "understanding bodies, spirits, and systems well enough to mend them. "
            "Triage decisions — who to save when you can't save everyone — drive "
            "their moral arc.",
            compatible_tags=frozenset({"healer"}),
        ),
        DiversitySeed(
            "protag_pacifist",
            "protagonist_archetype",
            "The protagonist is a committed pacifist in a world where violence is "
            "the primary currency of power. They advance through non-violent means: "
            "diplomacy, evasion, redirection, barrier arts, or transformation of "
            "hostile intent. Every temptation to fight is a test of their principles.",
            compatible_tags=frozenset({"philosophical", "cozy"}),
        ),
        DiversitySeed(
            "protag_late_bloomer",
            "protagonist_archetype",
            "The protagonist is 28-35 and has ALREADY FAILED at their first career "
            "or path. They washed out of the academy, lost their previous power, or "
            "simply never qualified. This is their second chance, and they bring the "
            "bitter wisdom of failure to a path usually walked by the young.",
        ),
        DiversitySeed(
            "protag_reluctant",
            "protagonist_archetype",
            "The protagonist genuinely does NOT want power and actively resists "
            "advancement. They are pulled in by obligation, accident, or external "
            "forces. Their reluctance is not false modesty — they have legitimate "
            "reasons to fear what power will do to them or demand of them.",
            compatible_tags=frozenset({"horror", "dark"}),
        ),
        DiversitySeed(
            "protag_twin",
            "protagonist_archetype",
            "The protagonist has a TWIN (identical or fraternal) who is their "
            "opposite in power affinity. One excels where the other fails. The "
            "twin relationship — rivalry, love, codependence, or estrangement — "
            "is a central emotional axis. Diverging paths for people who started "
            "identical creates powerful narrative tension.",
            compatible_tags=frozenset({"found_family"}),
        ),
    ],

    # ------------------------------------------------------------------
    # POWER SYSTEM STRUCTURE — how magic works
    # ------------------------------------------------------------------
    "power_system_structure": [
        DiversitySeed(
            "power_single_force",
            "power_system_structure",
            "The world has exactly ONE fundamental force. ALL variation in the power "
            "system comes from HOW that single force is shaped, directed, and "
            "understood — not from different force types. Practitioners disagree "
            "about the nature of this force, and those disagreements ARE the "
            "different schools of practice.",
        ),
        DiversitySeed(
            "power_many_hostile_forces",
            "power_system_structure",
            "The world has 5-6 fundamental forces that are HOSTILE to each "
            "other. Mixing paths causes real, physical damage to the practitioner. "
            "Multi-discipline cultivators are not rare because they're talented — "
            "they're rare because the attempt usually kills people.",
        ),
        DiversitySeed(
            "power_loss_based",
            "power_system_structure",
            "Power is gained by LOSING things: memories, senses, relationships, "
            "years of life, emotional capacity. The strongest practitioners are the "
            "most diminished as people. Every advancement is a genuine sacrifice "
            "that changes who the character is. There are no refunds.",
            compatible_tags=frozenset({"dark", "grimdark", "horror"}),
        ),
        DiversitySeed(
            "power_biological",
            "power_system_structure",
            "The power system is BIOLOGICAL, not mystical. There is no qi, mana, "
            "or spiritual energy — advancement literally reshapes the body. Organs "
            "grow, bones restructure, new sensory apparatus develops. It is evolution "
            "on a personal timescale. Healers double as power-system scholars.",
            compatible_tags=frozenset({"sci_fi", "horror"}),
        ),
        DiversitySeed(
            "power_consensus",
            "power_system_structure",
            "Advancement requires CONSENSUS. A practitioner cannot rank up alone — "
            "they need a quorum of peers to witness, validate, and anchor the "
            "breakthrough. This makes social bonds a literal power requirement and "
            "makes exile the most devastating punishment possible.",
            compatible_tags=frozenset({"found_family", "political_intrigue"}),
        ),
        DiversitySeed(
            "power_low_ceiling",
            "power_system_structure",
            "The power system has only 3-4 ranks total. The ceiling is LOW. Most "
            "practitioners reach the top within a decade. What matters is LATERAL "
            "mastery: creative applications, technique refinement, and synergy. "
            "The strongest are not higher-ranked, just more inventive.",
        ),
        DiversitySeed(
            "power_contracts",
            "power_system_structure",
            "Power comes from CONTRACTS with external entities: spirits, demons, "
            "natural forces, or abstract concepts. You do not cultivate — you "
            "negotiate. Every ability has terms and conditions. Breach of contract "
            "has devastating consequences. The best practitioners are the best "
            "dealmakers.",
            compatible_tags=frozenset({"fae", "demons", "spirits"}),
        ),
        DiversitySeed(
            "power_technological",
            "power_system_structure",
            "The power system is TECHNOLOGICAL. Advancement comes through artifacts, "
            "machines, implants, or engineered substances — not internal energy "
            "cultivation. The 'ranks' are equipment tiers. The strongest are the "
            "best-equipped, not the most talented. This makes economics central.",
            compatible_tags=frozenset({"sci_fi", "steampunk"}),
        ),
        DiversitySeed(
            "power_musical",
            "power_system_structure",
            "The power system is MUSICAL. Cultivation is composition. Combat is "
            "performance. Harmonies between practitioners create amplification, "
            "while dissonance creates interference. Advancement requires creating "
            "genuinely original music — derivative works produce derivative power.",
        ),
        DiversitySeed(
            "power_communal",
            "power_system_structure",
            "Power is COMMUNAL. Individuals are weak — solo practitioners cap out "
            "at low ranks. Groups that train together, harmonize their energies, and "
            "build genuine bonds become exponentially stronger than the sum of parts. "
            "The cultivation unit is the party/squad/family, not the individual.",
            compatible_tags=frozenset({"found_family"}),
        ),
        DiversitySeed(
            "power_debt",
            "power_system_structure",
            "The power system runs on DEBT. Every ability is borrowed from a cosmic "
            "source and must be repaid with interest. Quick power now means crippling "
            "payments later. The wisest practitioners take only what they can repay. "
            "The most reckless are the most powerful — until collection day.",
            compatible_tags=frozenset({"dark"}),
        ),
        DiversitySeed(
            "power_random",
            "power_system_structure",
            "Advancement is RANDOM. Breakthroughs come like lightning — unpredictable, "
            "unchosen, sometimes unwanted. Training helps but doesn't guarantee "
            "anything. Some people get lucky. Some train for decades and get nothing. "
            "The system is explicitly, provably unfair, and everyone knows it.",
            compatible_tags=frozenset({"satirical", "system_apocalypse"}),
        ),
        DiversitySeed(
            "power_emotional",
            "power_system_structure",
            "The power system runs on EMOTIONS. Genuine feeling — not performed "
            "emotion but real, deep sentiment — is the fuel. Grief powers destruction, "
            "joy powers healing, anger powers transformation, love powers protection. "
            "Practitioners who suppress emotions become powerless. Vulnerability IS "
            "strength.",
            compatible_tags=frozenset({"romantic", "romance"}),
        ),
        DiversitySeed(
            "power_language",
            "power_system_structure",
            "The power system is LINGUISTIC. True Names, spoken formulas, and "
            "written sigils are the mechanism. Knowing something's true name gives "
            "power over it. Literacy is power. The most dangerous practitioners are "
            "poets, linguists, and translators. Naming a thing changes its nature.",
            compatible_tags=frozenset({"philosophical"}),
        ),
        DiversitySeed(
            "power_parasitic",
            "power_system_structure",
            "The power system is PARASITIC. Every practitioner hosts an entity, "
            "symbiote, or foreign energy that grants abilities but feeds on the host. "
            "Advancement means feeding the parasite more. The relationship is not "
            "purely antagonistic — but it is never fully cooperative either.",
            compatible_tags=frozenset({"horror", "dark"}),
        ),
    ],

    # ------------------------------------------------------------------
    # WORLD STRUCTURE — how the setting is organized
    # ------------------------------------------------------------------
    "world_structure": [
        DiversitySeed(
            "world_no_nations",
            "world_structure",
            "There are no large nations or empires. Power belongs to wandering "
            "schools, trade caravans, monster-hunting companies, and mercenary guilds. "
            "Territory is defined by monster threat levels, not political borders. "
            "Settlements exist as independent city-states or outposts. "
            "List these organizations as factions and settlements as regions.",
        ),
        DiversitySeed(
            "world_vertical",
            "world_structure",
            "The world is VERTICAL: a massive tower, world-tree, underground shaft, "
            "or layered megastructure. Geography is measured in floors or layers, not "
            "latitude. Going deeper/higher means going into more dangerous territory. "
            "Horizontal distance barely matters.",
            compatible_tags=frozenset({"tower_climbing", "subterranean"}),
        ),
        DiversitySeed(
            "world_shattered_empire",
            "world_structure",
            "ONE government shattered within living memory (5-15 years ago). Every "
            "current faction is a splinter of the old empire. Loyalists, reformists, "
            "separatists, and opportunists all claim legitimacy. The protagonist is "
            "born into the power vacuum, not the empire.",
        ),
        DiversitySeed(
            "world_two_civilizations",
            "world_structure",
            "TWO fundamentally different civilizations coexist with incompatible "
            "power systems and a fragile truce. The protagonist is caught between "
            "them. Each side views the other's power as abomination. The conflict "
            "is cultural, not just military.",
        ),
        DiversitySeed(
            "world_dying",
            "world_structure",
            "The world is DYING — and everyone knows it. A known expiration date "
            "(decades, years, or months) drives everything. Some factions try to "
            "prevent the end. Some prepare for what comes after. Some accelerate "
            "it. Power progression takes on urgency when the clock is ticking.",
            compatible_tags=frozenset({"dark", "survival"}),
        ),
        DiversitySeed(
            "world_newborn",
            "world_structure",
            "The world is BRAND NEW — created within living memory (1-3 generations). "
            "History is still being written. The cosmology is not ancient lore but "
            "something grandparents remember emerging. Traditions are young. Rules "
            "are still being discovered. Everything is first-generation.",
        ),
        DiversitySeed(
            "world_megacity",
            "world_structure",
            "A single MEGACITY is the entire known world. The wilds beyond its walls "
            "are absolute unknown — lethal, uncharted, and possibly infinite. All "
            "politics, factions, and power structures exist within the city. "
            "List the city's major districts as separate regions (at least 3). "
            "Districts are as different as countries.",
            compatible_tags=frozenset({"urban"}),
        ),
        DiversitySeed(
            "world_seasonal_power",
            "world_structure",
            "The world operates on SEASONS of power that cycle on a multi-year "
            "timescale. During high season, advancement is easy but dangers multiply. "
            "During low season, power dims and practitioners must survive on reserves. "
            "The story begins at a seasonal transition.",
        ),
        DiversitySeed(
            "world_layered_reality",
            "world_structure",
            "Reality is LAYERED. The same geography exists in multiple overlapping "
            "dimensions simultaneously. Stepping between layers changes the rules. "
            "Buildings in one layer are ruins in another. Powerful beings exist "
            "across multiple layers at once.",
        ),
        DiversitySeed(
            "world_post_utopia",
            "world_structure",
            "The world is POST-UTOPIA. Paradise was real and it fell. The ruins are "
            "more dangerous for being beautiful. Ancient infrastructure that once "
            "served everyone now serves no one. The memory of perfection makes "
            "the present harder to endure.",
        ),
        DiversitySeed(
            "world_nomadic",
            "world_structure",
            "ALL civilizations are NOMADIC. The landscape itself shifts, so permanent "
            "settlement is impossible. Cities walk, float, or migrate. Home is the "
            "people, not the place. Resource caches and waypoints replace cities.",
        ),
        DiversitySeed(
            "world_archipelago",
            "world_structure",
            "The world is an ARCHIPELAGO of islands separated by a hostile medium: "
            "toxic sea, void storms, monster-infested wilderness, or dimensional "
            "gaps. Each island is its own micro-culture. Travel between them is "
            "an event, not a commute.",
            compatible_tags=frozenset({"undersea", "aerial"}),
        ),
        DiversitySeed(
            "world_living",
            "world_structure",
            "The WORLD ITSELF is alive — a continent-sized organism, a sleeping god, "
            "or a growing entity. Geography changes because the world moves. Earthquakes "
            "are heartbeats. Rivers are circulation. The power system taps into the "
            "world's biology. Practitioners are parasites, symbiotes, or cells.",
            compatible_tags=frozenset({"horror", "eldritch"}),
        ),
    ],

    # ------------------------------------------------------------------
    # TONE AND MOOD — the emotional register
    # ------------------------------------------------------------------
    "tone_and_mood": [
        DiversitySeed(
            "tone_cozy",
            "tone_and_mood",
            "The tone is COZY. Power growth happens alongside found family, good "
            "meals, comfortable routines, and quiet moments of genuine connection. "
            "Violence exists but is not glorified or frequent. Slice-of-life moments "
            "carry equal narrative weight to action. The world has dangers but also "
            "genuine warmth.",
            compatible_tags=frozenset({"cozy", "found_family"}),
            incompatible_tags=frozenset({"grimdark", "gore", "horror"}),
        ),
        DiversitySeed(
            "tone_grimdark",
            "tone_and_mood",
            "The tone is GRIMDARK. The power system is actively cruel — designed by "
            "something indifferent or hostile to mortal wellbeing. Institutions are "
            "corrupt by design, not accident. Happy endings are earned by paying "
            "terrible prices. Betrayal is a survival tool. Hope is rare and precious.",
            compatible_tags=frozenset({"grimdark", "dark"}),
            incompatible_tags=frozenset({"cozy", "humorous", "heroic"}),
        ),
        DiversitySeed(
            "tone_comedic",
            "tone_and_mood",
            "The tone is COMEDIC. The world takes itself seriously but the protagonist's "
            "perspective is irreverent. Comedy arises naturally from genre-awareness "
            "without breaking the fourth wall. Absurd situations are played completely "
            "straight. The humor makes the serious moments hit harder.",
            compatible_tags=frozenset({"humorous", "satirical"}),
            incompatible_tags=frozenset({"grimdark", "horror"}),
        ),
        DiversitySeed(
            "tone_philosophical",
            "tone_and_mood",
            "The tone is PHILOSOPHICAL. Characters genuinely debate the ethics of "
            "power, the nature of consciousness, the meaning of advancement. Intellectual "
            "conflicts carry as much weight as physical ones. The story asks questions "
            "it doesn't fully answer. Readers should think, not just feel.",
            compatible_tags=frozenset({"philosophical"}),
        ),
        DiversitySeed(
            "tone_horror",
            "tone_and_mood",
            "The tone includes genuine HORROR. Power is terrifying. Advancement "
            "changes you in ways that frighten the people who love you. The unknown "
            "is genuinely threatening. Scenes should create dread, not just danger. "
            "Cosmic indifference or active malice lurks behind the power system's "
            "mechanics.",
            compatible_tags=frozenset({"horror", "eldritch", "dark"}),
            incompatible_tags=frozenset({"cozy", "humorous"}),
        ),
        DiversitySeed(
            "tone_tragic",
            "tone_and_mood",
            "The tone is TRAGIC. The protagonist will not get everything they want. "
            "Some losses are permanent. The journey still matters, and meaning can "
            "be found in the losing. Do not mistake tragedy for grimdark — tragic "
            "stories are about love and loss, not cruelty.",
            compatible_tags=frozenset({"dark"}),
        ),
        DiversitySeed(
            "tone_satirical",
            "tone_and_mood",
            "The tone is SATIRICAL. The power system and its institutions serve as "
            "pointed commentary on real-world systems: bureaucracy, capitalism, "
            "academia, social media, or meritocracy myths. Played straight but the "
            "parallels are unmistakable. The satire has teeth.",
            compatible_tags=frozenset({"satirical", "humorous"}),
        ),
        DiversitySeed(
            "tone_melancholic",
            "tone_and_mood",
            "The tone is MELANCHOLIC. Beauty and loss are intertwined. Power "
            "preserves some things but can never restore others. The world is "
            "gorgeous and fading. Characters carry a sense of things ending even "
            "as they strive. Nostalgia is a force as real as magic.",
        ),
        DiversitySeed(
            "tone_pulp",
            "tone_and_mood",
            "The tone is PULP ADVENTURE. Fast, fun, high-stakes. The protagonist "
            "quips mid-combat. Setpieces are dramatic and cinematic. The pacing "
            "rarely slows. Enemies are formidable but fights are thrilling rather "
            "than traumatic. Swagger is a survival skill.",
            compatible_tags=frozenset({"fast_paced", "heroic"}),
        ),
        DiversitySeed(
            "tone_mythic",
            "tone_and_mood",
            "The tone is MYTHIC. The prose register is elevated without being "
            "purple. Events feel like legend being written in real-time. Characters "
            "speak with weight. The scale is grand from the beginning. This is a "
            "story that will be told around fires for generations.",
            compatible_tags=frozenset({"heroic"}),
        ),
        DiversitySeed(
            "tone_noir",
            "tone_and_mood",
            "The tone is NOIR. Rain-slicked streets, moral compromise, femmes "
            "fatales or hommes fatals. The protagonist is cynical for good reasons. "
            "Trust is the most dangerous currency. Everyone has an angle. The power "
            "system is another tool for corruption.",
            compatible_tags=frozenset({"urban", "dark", "mystery"}),
        ),
        DiversitySeed(
            "tone_whimsical",
            "tone_and_mood",
            "The tone is WHIMSICAL. The world operates on narrative logic and "
            "fairy-tale rules. Things that are poetically right tend to happen. "
            "Names have power. Promises bind. The absurd is normal. Behind the "
            "whimsy, real stakes and real consequences give the story weight.",
            compatible_tags=frozenset({"fae", "humorous"}),
        ),
    ],

    # ------------------------------------------------------------------
    # VOICE AND STYLE — prose style, POV, narrative voice
    # ------------------------------------------------------------------
    "voice_and_style": [
        DiversitySeed(
            "voice_first_person",
            "voice_and_style",
            "Write in FIRST PERSON. The protagonist narrates directly using 'I' and "
            "'me'. Every description is filtered through their personality, bias, and "
            "limited knowledge. What they misunderstand, the reader misunderstands. "
            "Their voice IS the prose style.",
            compatible_tags=frozenset({"first_person"}),
            incompatible_tags=frozenset({"omniscient", "ensemble"}),
        ),
        DiversitySeed(
            "voice_present_tense",
            "voice_and_style",
            "Write in PRESENT TENSE throughout. 'She walks. The blade falls. He "
            "doesn't see it coming.' This removes the safety of retrospection — the "
            "narrator does not know what happens next. Immediacy and tension are "
            "constant. The reader is trapped in the now.",
            compatible_tags=frozenset({"present_tense", "fast_paced"}),
        ),
        DiversitySeed(
            "voice_omniscient_ironic",
            "voice_and_style",
            "Use an OMNISCIENT narrator with a distinct personality — wry, knowing, "
            "occasionally sardonic. The narrator comments on events, foreshadows with "
            "deliberate irony, and has access to every character's thoughts. The "
            "narrator's voice is a character in its own right, like Pratchett or "
            "Vonnegut at their most engaged.",
            compatible_tags=frozenset({"omniscient", "humorous", "satirical"}),
            incompatible_tags=frozenset({"first_person"}),
        ),
        DiversitySeed(
            "voice_sparse_hemingway",
            "voice_and_style",
            "Write in SPARSE, stripped-down prose. Short declarative sentences. "
            "Almost no adjectives. Emotion lives in what is NOT said — in the gap "
            "between action and reaction. Descriptions are surgical: one precise "
            "detail over three vague ones. Dialogue is clipped. Let silence do work.",
            compatible_tags=frozenset({"sparse_prose", "dark", "grimdark"}),
            incompatible_tags=frozenset({"lush_prose", "lyrical"}),
        ),
        DiversitySeed(
            "voice_lush_sensory",
            "voice_and_style",
            "Write in LUSH, sensory-rich prose. Every scene has texture, smell, "
            "temperature, and sound layered into the description. Metaphors are "
            "drawn from the world's own logic — cultivation imagery, power-system "
            "vocabulary woven into everyday observation. Sentences vary from long "
            "flowing passages to sharp interruptions. The prose is a pleasure in "
            "itself.",
            compatible_tags=frozenset({"lush_prose", "lyrical"}),
            incompatible_tags=frozenset({"sparse_prose", "fast_paced"}),
        ),
        DiversitySeed(
            "voice_dialogue_driven",
            "voice_and_style",
            "Make the prose DIALOGUE-HEAVY. Characters talk constantly — arguing, "
            "negotiating, joking, lying, confessing. Scenes are built around "
            "conversations. Subtext matters: what characters refuse to say reveals "
            "more than what they do say. Action scenes use dialogue mid-combat. "
            "Minimize narration between speech.",
            compatible_tags=frozenset({"dialogue_heavy", "humorous"}),
        ),
        DiversitySeed(
            "voice_deep_introspection",
            "voice_and_style",
            "The prose is deeply INTROSPECTIVE. The protagonist's thought process "
            "is shown in granular, real-time detail. They analyze situations, "
            "second-guess themselves, notice their own emotional patterns, and "
            "construct theories about the world that may be wrong. The reader lives "
            "inside their head. External events are always filtered through "
            "psychological response.",
            compatible_tags=frozenset({"introspective", "philosophical", "slow_burn"}),
        ),
        DiversitySeed(
            "voice_action_kinetic",
            "voice_and_style",
            "The prose is KINETIC and action-forward. Sentences during combat are "
            "short, percussive, sometimes fragments. Movement verbs dominate. "
            "Fight choreography is beat-by-beat specific — no 'they fought for "
            "hours' summaries. Even quiet scenes maintain physical momentum: "
            "characters pace, fidget, cook, repair. Bodies are always doing "
            "something.",
            compatible_tags=frozenset({"action_forward", "fast_paced"}),
            incompatible_tags=frozenset({"slow_burn", "introspective"}),
        ),
        DiversitySeed(
            "voice_sardonic_narrator",
            "voice_and_style",
            "The narrative voice is DRY and SARDONIC. The protagonist observes the "
            "absurdity of their situation with sharp wit. Descriptions carry an "
            "undertone of 'can you believe this?' Internal commentary undercuts "
            "dramatic moments — but when the humor drops, the sincerity hits harder "
            "for the contrast. Think Rothfuss's Kvothe or Abercrombie's Glokta.",
            compatible_tags=frozenset({"sardonic_voice", "humorous", "anti_hero"}),
        ),
        DiversitySeed(
            "voice_lyrical_poetic",
            "voice_and_style",
            "The prose is LYRICAL. Sentence rhythm is deliberate — read passages "
            "aloud and they have cadence. Repetition and parallelism are structural "
            "tools. Key moments use near-poetic register without tipping into "
            "purple prose. The sound of the language reinforces meaning. Paragraph "
            "endings land like last notes of a phrase.",
            compatible_tags=frozenset({"lyrical", "lush_prose"}),
            incompatible_tags=frozenset({"sparse_prose"}),
        ),
        DiversitySeed(
            "voice_epistolary_mixed",
            "voice_and_style",
            "Intersperse standard prose with EPISTOLARY fragments: journal entries, "
            "official reports, intercepted letters, research notes, system logs, or "
            "recovered documents. These fragments have their own voice distinct from "
            "the main narrative. They provide information the protagonist doesn't "
            "have, creating dramatic irony. At least one in-world document per "
            "chapter.",
            compatible_tags=frozenset({"epistolary", "mystery"}),
        ),
        DiversitySeed(
            "voice_unreliable_close",
            "voice_and_style",
            "Use TIGHT CLOSE-THIRD perspective where the narrator's reliability "
            "degrades under stress. When the protagonist is calm, descriptions are "
            "accurate. When afraid, angry, or in pain, perception distorts — time "
            "stretches, details blur, the prose itself becomes fragmentary or "
            "run-on. The reader feels the character's psychological state through "
            "the prose texture, not just through content.",
            compatible_tags=frozenset({"horror", "dark", "introspective"}),
        ),
        DiversitySeed(
            "voice_cinematic",
            "voice_and_style",
            "Write with CINEMATIC framing. Open scenes with wide establishing shots, "
            "then cut to close-ups. Transitions between scenes are sharp cuts, not "
            "gradual fades. Visual composition matters: where characters stand "
            "relative to each other, lighting, the angle of observation. The reader "
            "should be able to storyboard every chapter.",
            compatible_tags=frozenset({"action_forward", "fast_paced"}),
        ),
        DiversitySeed(
            "voice_folklore_oral",
            "voice_and_style",
            "Write as if the story is being TOLD ALOUD — an oral tradition rendered "
            "in text. The narrator occasionally addresses the listener: 'Now, you "
            "must understand...' or 'What happened next, no one expected.' Digressions "
            "are natural. The voice is warm, knowing, and slightly conspiratorial. "
            "Foreshadowing is explicit: 'They did not know this would be the last "
            "time.'",
            compatible_tags=frozenset({"omniscient"}),
        ),
    ],

    # ------------------------------------------------------------------
    # SETTING TWIST — unusual environmental constraints
    # ------------------------------------------------------------------
    "setting_twist": [
        DiversitySeed(
            "setting_urban",
            "setting_twist",
            "The world is URBAN — the entire story takes place inside one massive "
            "city or interconnected urban sprawl. Districts replace regions. "
            "Politics is local, personal, and claustrophobic. Nature is distant "
            "memory or carefully maintained park. Rooftops, sewers, and skyscrapers "
            "are the wilderness.",
            compatible_tags=frozenset({"urban"}),
        ),
        DiversitySeed(
            "setting_post_apocalyptic",
            "setting_twist",
            "The setting is POST-APOCALYPTIC. A previous civilization collapsed "
            "within the last 1-2 generations. Its ruins contain power and existential "
            "danger. Survival is a baseline concern. Scavenging the old world's "
            "knowledge is as important as personal cultivation.",
            compatible_tags=frozenset({"post_apocalyptic", "survival"}),
        ),
        DiversitySeed(
            "setting_aerial",
            "setting_twist",
            "The setting is AERIAL. There is no ground, or ground is lethal. "
            "People live on floating islands, the backs of sky-creatures, cloud "
            "formations, or wind-current platforms. Falling is the universal fear. "
            "Vertical distance replaces horizontal. Flight is survival, not luxury.",
            compatible_tags=frozenset({"aerial"}),
        ),
        DiversitySeed(
            "setting_subterranean",
            "setting_twist",
            "The setting is SUBTERRANEAN. The surface is a myth, a death zone, or "
            "simply unknown. Caves, fungal forests, magma rivers, crystal caverns, "
            "and bioluminescent ecosystems define geography. Light is precious. "
            "Direction is relative. Claustrophobia is a character trait, not a phobia.",
            compatible_tags=frozenset({"subterranean"}),
        ),
        DiversitySeed(
            "setting_nautical",
            "setting_twist",
            "The setting is NAUTICAL. An island archipelago or endless ocean. Power "
            "flows through ocean currents. Ships are everything: home, weapon, "
            "status symbol, cultivation chamber. Navigation is a form of divination. "
            "What lies in the deep is more dangerous than anything on the surface.",
            compatible_tags=frozenset({"undersea"}),
        ),
        DiversitySeed(
            "setting_arctic",
            "setting_twist",
            "The setting is ARCTIC. Perpetual winter or glacial environment. Power "
            "costs body heat — the strongest practitioners are always cold. Warmth "
            "is precious. Settlements huddle around heat sources. The frozen waste "
            "preserves things that should have stayed buried.",
        ),
        DiversitySeed(
            "setting_desert",
            "setting_twist",
            "The setting is DESERT. Water is currency. The power system revolves "
            "around scarcity and preservation. Oases are power centers. Sand hides "
            "ancient ruins. The sun is an enemy. Night is when the world truly "
            "comes alive. Mirages may be real.",
        ),
        DiversitySeed(
            "setting_dream",
            "setting_twist",
            "The setting is DREAM-ADJACENT. Reality bleeds into dream. Geography "
            "shifts when enough people sleep in the same area. Nightmares manifest. "
            "The boundary between waking and dreaming is a frontier to be explored, "
            "not a line to be maintained. Insomnia is a superpower and a curse.",
        ),
        DiversitySeed(
            "setting_microscopic",
            "setting_twist",
            "The world exists INSIDE a living body. Cells are nations. Blood vessels "
            "are highways. The immune system is a military force. Disease is invasion. "
            "The protagonist navigates a world defined by biology. Scale is reversed — "
            "the vast is actually tiny.",
        ),
        DiversitySeed(
            "setting_time_fractured",
            "setting_twist",
            "Different regions exist in DIFFERENT TIME PERIODS simultaneously. Cross "
            "a border and you step from the medieval era into the industrial age. "
            "Time is geography. Temporal displacement is as disorienting as culture "
            "shock. Chronological navigation is a skill.",
        ),
        DiversitySeed(
            "setting_inverted",
            "setting_twist",
            "The world is INVERTED from standard fantasy. What would normally be "
            "safe is dangerous (cities, temples, roads) and what would normally be "
            "dangerous is safe (monster lairs, cursed forests, abandoned ruins). "
            "Civilization is the threat. Wilderness is sanctuary.",
        ),
        DiversitySeed(
            "setting_pocket_dimensions",
            "setting_twist",
            "The world is a network of POCKET DIMENSIONS connected by unstable "
            "portals. Each pocket has different physical laws. Gravity, time, "
            "element composition — all vary. Navigating between pockets is the "
            "primary form of travel and the primary source of danger.",
        ),
    ],

    # ------------------------------------------------------------------
    # NARRATIVE SHAPE — how the story is told
    # ------------------------------------------------------------------
    "narrative_shape": [
        DiversitySeed(
            "narrative_dual_timeline",
            "narrative_shape",
            "The story uses DUAL TIMELINES. Alternate chapters between past and "
            "present. The connection between timelines IS the mystery. Events in "
            "one timeline recontextualize events in the other. The convergence "
            "point is a major narrative payoff.",
            compatible_tags=frozenset({"mystery", "regression"}),
        ),
        DiversitySeed(
            "narrative_unreliable",
            "narrative_shape",
            "The protagonist has an UNRELIABLE perception of reality. Something "
            "they fundamentally believe about the power system, their own nature, "
            "or the world has at least one critical error that will be revealed. "
            "Plant clues early. The revelation should recontextualize prior events.",
            compatible_tags=frozenset({"mystery", "horror"}),
        ),
        DiversitySeed(
            "narrative_ensemble",
            "narrative_shape",
            "The story is ENSEMBLE. While one character may anchor the narrative, "
            "3-4 characters share roughly equal narrative weight with their own "
            "arcs, growth trajectories, and perspective chapters. The group dynamic "
            "matters more than any individual.",
            compatible_tags=frozenset({"ensemble", "found_family"}),
        ),
        DiversitySeed(
            "narrative_mystery_box",
            "narrative_shape",
            "The story is structured around a MYSTERY BOX. The central question "
            "of the world (What happened? What is the protagonist? What is this "
            "place?) is explicitly unknowable at first and drives everything. "
            "Each answer reveals a deeper question. The mystery deepens before "
            "it resolves.",
            compatible_tags=frozenset({"mystery"}),
        ),
        DiversitySeed(
            "narrative_tournament",
            "narrative_shape",
            "The world is organized around recurring COMPETITIONS or tournaments. "
            "Ranking, matchups, and elimination brackets provide natural story "
            "structure. The tournament is not just entertainment — it serves a "
            "political, religious, or cosmic function. Losing has real consequences.",
            compatible_tags=frozenset({"academy"}),
        ),
        DiversitySeed(
            "narrative_countdown",
            "narrative_shape",
            "A FIXED DEADLINE drives the narrative. The protagonist has a specific "
            "amount of time before something irreversible happens. They cannot train "
            "forever. Every choice about how to spend their remaining time is "
            "meaningful. The clock creates tension that raw power cannot solve.",
            compatible_tags=frozenset({"survival", "fast_paced"}),
        ),
        DiversitySeed(
            "narrative_parallel",
            "narrative_shape",
            "TWO PROTAGONISTS on separate paths that will eventually converge. "
            "One may be in a position of power while the other starts from nothing. "
            "Their stories echo and contrast. When they finally meet, the reader "
            "has context neither character possesses.",
        ),
        DiversitySeed(
            "narrative_mentor_student",
            "narrative_shape",
            "The story centers on a MENTOR-STUDENT relationship from chapter 1. "
            "The mentor is flawed, possibly unreliable, and definitely hiding "
            "something. The student's growth challenges the mentor's worldview. "
            "Surpassing the teacher is inevitable but not simple.",
            compatible_tags=frozenset({"academy"}),
        ),
        DiversitySeed(
            "narrative_found_manuscript",
            "narrative_shape",
            "Parts of the story are told through DISCOVERED DOCUMENTS: letters, "
            "research notes, official records, confessions, or ancient texts. These "
            "fragments provide information the protagonist doesn't have yet. The "
            "reader knows more than the characters, creating dramatic irony.",
            compatible_tags=frozenset({"mystery"}),
        ),
        DiversitySeed(
            "narrative_nonlinear",
            "narrative_shape",
            "The story is told NON-LINEARLY. Chapters jump between time periods, "
            "showing consequences before causes, answers before questions. The "
            "reader's experience of assembling the timeline IS the story. Chronological "
            "order would make it a different, lesser narrative.",
        ),
    ],

    # ------------------------------------------------------------------
    # SUBGENRE FLAVOR — structural identity modifiers
    # ------------------------------------------------------------------
    "subgenre_flavor": [
        DiversitySeed(
            "flavor_system_apocalypse",
            "subgenre_flavor",
            "A game-like SYSTEM has been imposed on reality. Status screens, level "
            "notifications, skill acquisitions, and dungeon instances are physical "
            "facts. Society is collapsing and rebuilding around these new rules. "
            "The system itself may be sentient, indifferent, or hostile.",
            compatible_tags=frozenset({"system_apocalypse", "litrpg"}),
        ),
        DiversitySeed(
            "flavor_isekai",
            "subgenre_flavor",
            "The protagonist originates from ANOTHER WORLD (modern Earth or "
            "equivalent). They carry foreign knowledge and cultural assumptions that "
            "are sometimes helpful, sometimes dangerously wrong. They are not "
            "special because they're from elsewhere — they must earn their place.",
            compatible_tags=frozenset({"isekai"}),
        ),
        DiversitySeed(
            "flavor_reincarnation",
            "subgenre_flavor",
            "The protagonist has PAST-LIFE MEMORIES. They know the future (or a "
            "version of it) but lack the power to change it. Knowledge creates "
            "obligation. The gap between knowing and doing is the central tension. "
            "Butterfly effects mean their foreknowledge becomes unreliable.",
            compatible_tags=frozenset({"reincarnation", "regression"}),
        ),
        DiversitySeed(
            "flavor_dungeon_core",
            "subgenre_flavor",
            "The protagonist IS a dungeon or is bonded to one. Growth means "
            "designing floors, spawning monsters, creating ecosystems, and absorbing "
            "the essence of delvers. The perspective is architectural and strategic. "
            "The dungeon's reputation matters. Delvers are both threat and resource.",
            compatible_tags=frozenset({"dungeon_core", "base_builder"}),
        ),
        DiversitySeed(
            "flavor_monster_evolution",
            "subgenre_flavor",
            "The protagonist IS a non-human creature that evolves. They start as "
            "something small and weak — a slime, insect, lizard, or fungal spore. "
            "Evolution choices are irreversible and define their future path. "
            "Communication with humanoids is a late-game achievement, not a default.",
            compatible_tags=frozenset({"monster_evolution", "nonhuman_lead"}),
        ),
        DiversitySeed(
            "flavor_crafting",
            "subgenre_flavor",
            "CRAFTING is the primary axis of power progression. The protagonist "
            "advances by creating increasingly powerful artifacts, potions, "
            "formations, or constructs. The creative process IS cultivation. "
            "Resource acquisition, recipe discovery, and workshop management drive "
            "the plot as much as combat.",
            compatible_tags=frozenset({"craftsman", "everyday_ascendancy"}),
        ),
        DiversitySeed(
            "flavor_regression",
            "subgenre_flavor",
            "The protagonist has been SENT BACK IN TIME to an earlier point in "
            "their life. They retain knowledge but not power. Foreknowledge is a "
            "double-edged sword — some tragedies can be prevented, but changing "
            "one thing changes everything. The future they remember is not guaranteed.",
            compatible_tags=frozenset({"regression"}),
        ),
        DiversitySeed(
            "flavor_everyday",
            "subgenre_flavor",
            "Power comes through mastery of the MUNDANE: cooking, farming, cleaning, "
            "accounting, carpentry, or gardening. The magic system treats these "
            "activities as legitimate cultivation paths. A perfectly baked loaf of "
            "bread can be as powerful as a sword technique. Domestic skills ascend.",
            compatible_tags=frozenset({"everyday_ascendancy", "cozy"}),
        ),
        DiversitySeed(
            "flavor_sect_politics",
            "subgenre_flavor",
            "SECT POLITICS drive the narrative. Cultivation institutions with "
            "internal factions, elder councils, disciple rankings, resource "
            "allocation battles, and inter-sect diplomacy. The protagonist must "
            "navigate institutional power structures as skillfully as combat.",
            compatible_tags=frozenset({"cultivation", "academy", "political_intrigue"}),
        ),
        DiversitySeed(
            "flavor_apocalypse_survival",
            "subgenre_flavor",
            "The WORLD IS ENDING NOW. Not in a prophecy — right now. Power growth "
            "happens under siege conditions. There is no safe training ground. "
            "Resources are scarce. Every advancement choice must be immediately "
            "useful. Long-term planning is a luxury the protagonist cannot afford.",
            compatible_tags=frozenset({"survival", "fast_paced", "dark"}),
        ),
        DiversitySeed(
            "flavor_virtual_reality",
            "subgenre_flavor",
            "The primary setting is a VIRTUAL WORLD — a game, simulation, or "
            "constructed reality. But the boundaries between virtual and real are "
            "blurring. Death in-game may have real consequences. The virtual world "
            "may be MORE real than assumed. NPCs may be people.",
            compatible_tags=frozenset({"litrpg", "sci_fi"}),
        ),
        DiversitySeed(
            "flavor_summoner",
            "subgenre_flavor",
            "The protagonist fights through BOUND ENTITIES rather than personal "
            "combat. Acquiring, training, evolving, and synergizing summons is the "
            "progression axis. The bond between summoner and summoned is the "
            "emotional core. Each summon has personality and agency.",
            compatible_tags=frozenset({"summoner", "spirits", "demons"}),
        ),
        DiversitySeed(
            "flavor_healer",
            "subgenre_flavor",
            "The protagonist's path is RESTORATION, not destruction. They advance "
            "by understanding bodies, spirits, and systems well enough to mend them. "
            "Triage decisions — who to save when you can't save everyone — drive "
            "moral arcs. Being needed by everyone is a weight, not a gift.",
            compatible_tags=frozenset({"healer"}),
        ),
        DiversitySeed(
            "flavor_base_builder",
            "subgenre_flavor",
            "The protagonist establishes and grows a SETTLEMENT, guild, or faction. "
            "Resource management, recruitment, defense, trade, and expansion are "
            "core progression axes alongside personal power. The community the "
            "protagonist builds is as much a character as any individual.",
            compatible_tags=frozenset({"base_builder", "political_intrigue"}),
        ),
    ],

    # ------------------------------------------------------------------
    # CHAOS MODIFIER — deliberately wild constraints to force the LLM
    # out of its comfort zone. High base weight ensures frequent selection.
    # ------------------------------------------------------------------
    "chaos_modifier": [
        DiversitySeed(
            "chaos_pun_magic",
            "chaos_modifier",
            "The magic system is powered by bad puns. The worse the pun, the "
            "stronger the spell. Practitioners train by studying wordplay across "
            "multiple languages. The most powerful technique is the triple entendre.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_retired_accounting_god",
            "chaos_modifier",
            "The protagonist is a retired accounting god who was demoted to mortal "
            "for creative bookkeeping. They still instinctively see the world in "
            "ledgers, and their power grows when they balance cosmic accounts.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_inverse_cool",
            "chaos_modifier",
            "Every character's power level is inversely proportional to how cool "
            "they look. The strongest warrior wears cargo shorts and crocs. The "
            "weakest has the most dramatic entrance. Looking badass is a tactical "
            "disadvantage.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_blackmail_economy",
            "chaos_modifier",
            "The world's economy runs on embarrassing secrets. Currency is literally "
            "blackmail. The central bank is a gossip network. Inflation happens when "
            "too many secrets get publicly revealed. The poorest are the shameless.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_compliment_combat",
            "chaos_modifier",
            "The power system requires users to sincerely compliment their enemies "
            "mid-combat. Insincere compliments backfire. The strongest fighters are "
            "those who can find genuine good in anyone trying to kill them.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_unobserved_power",
            "chaos_modifier",
            "The protagonist's special ability only works when nobody is watching, "
            "including the reader. Scenes where they use their power are described "
            "only through aftermath and other characters' confused reactions.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_bureaucratic_magic",
            "chaos_modifier",
            "All magic in this world is technically a bureaucratic process. There "
            "are forms to fill out, approvals to obtain, and interdepartmental "
            "reviews. Emergency spells require expedited processing fees. The most "
            "powerful mages are the ones who know which forms to skip.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_committee_gods",
            "chaos_modifier",
            "The world was created by a committee of gods who fundamentally disagree "
            "on physics. Gravity works differently depending on which god's territory "
            "you're in. Natural laws are a compromise document nobody is happy with.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_hobby_progression",
            "chaos_modifier",
            "Power progression requires the protagonist to master increasingly "
            "obscure hobbies. Rank 1 requires competent knitting. Rank 5 demands "
            "championship-level competitive bird watching. The final rank requires "
            "mastering a hobby that doesn't exist yet.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_correct_antagonist",
            "chaos_modifier",
            "The antagonist is objectively correct about everything but has terrible "
            "communication skills. Every conflict arises because they can't explain "
            "their (valid) reasoning without insulting everyone in the room.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_attachment_tax",
            "chaos_modifier",
            "Every rank-up requires the character to lose something they just got "
            "attached to. The power system specifically targets new attachments. "
            "Veteran practitioners are either emotionally devastated or have learned "
            "to never like anything.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_weaponized_nostalgia",
            "chaos_modifier",
            "The world's most powerful force is weaponized nostalgia. Practitioners "
            "who can make you remember your childhood become unstoppable. The "
            "military-industrial complex runs on bottled memories of better times.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_mild_annoyance",
            "chaos_modifier",
            "The protagonist can only use their power while maintaining a specific "
            "emotional state: mild annoyance. Too calm and it fades. Too angry and "
            "it backfires. They must cultivate a precise level of being slightly "
            "put out about everything.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_magic_customer_service",
            "chaos_modifier",
            "The magic system has a customer service hotline. Hold times are "
            "unreasonable. You can escalate to a supervisor for more powerful spells "
            "but they're always in a meeting. Premium subscribers get faster casting.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_misleading_prophecies",
            "chaos_modifier",
            "All prophecies in this world are technically accurate but maximally "
            "misleading. Seers are honest professionals who hate that their gift "
            "works this way. 'The chosen one will fall' means they trip on a rock.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_cooking_power",
            "chaos_modifier",
            "The power system is based on cooking. The better the dish, the stronger "
            "the technique. Ingredient sourcing is dungeon delving. Recipe creation "
            "is spell research. Food critics are the most feared beings alive.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_accidental_leader",
            "chaos_modifier",
            "The protagonist keeps accidentally becoming the leader of organizations "
            "they were trying to destroy. Every infiltration mission ends with them "
            "being promoted. They now lead three rival factions simultaneously.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_narrative_awareness",
            "chaos_modifier",
            "The world operates on narrative awareness — characters who realize "
            "they're in a story become more powerful but also more constrained by "
            "genre conventions. The protagonist suspects but can't confirm.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_teach_to_advance",
            "chaos_modifier",
            "Power advancement requires successfully teaching your skills to someone "
            "less talented than you. The worse the student, the more power the "
            "teacher gains. The greatest masters seek out the most hopeless pupils.",
            weight=1.5,
        ),
        DiversitySeed(
            "chaos_max_level_boredom",
            "chaos_modifier",
            "The setting is a world where everyone already hit max level and is "
            "desperately bored. The economy has collapsed because nobody needs "
            "anything. The protagonist's unique trait is being the only person "
            "who hasn't reached the cap.",
            weight=1.5,
        ),
    ],

    # ------------------------------------------------------------------
    # NAMING PALETTE — positive vocabulary direction for world naming.
    # Instead of just banning words, these tell the LLM WHAT vocabulary
    # to draw from for names, places, forces, and power systems.
    # ------------------------------------------------------------------
    "naming_palette": [
        DiversitySeed(
            "naming_geological",
            "naming_palette",
            "All names in this world should draw from GEOLOGICAL vocabulary. "
            "Power ranks, forces, places, and techniques should evoke: strata, "
            "fault, mantle, sediment, erosion, tectonic, basalt, obsidian, "
            "schist, alluvial. The world feels ancient and mineral.",
        ),
        DiversitySeed(
            "naming_maritime",
            "naming_palette",
            "Naming conventions should evoke MARITIME themes. Power terms, "
            "places, and ranks should draw from: tide, hull, keel, current, "
            "bilge, reef, fathom, sounding, rigging, leeward. The world "
            "feels vast and oceanic.",
        ),
        DiversitySeed(
            "naming_industrial",
            "naming_palette",
            "Names should sound INDUSTRIAL. Power systems, ranks, and places "
            "should evoke: forge, press, gauge, valve, exhaust, temper, alloy, "
            "rivets, slag, calibration. The world feels mechanical and precise.",
        ),
        DiversitySeed(
            "naming_culinary",
            "naming_palette",
            "Use CULINARY vocabulary for all power terminology. Ranks, "
            "techniques, and forces should evoke: simmer, ferment, distill, "
            "reduce, cure, brine, caramelize, deglaze. Cultivation is cooking. "
            "The kitchen is the dojo.",
        ),
        DiversitySeed(
            "naming_astronomical",
            "naming_palette",
            "Names should evoke ASTRONOMICAL concepts. Forces, ranks, and "
            "places should draw from: parallax, apogee, corona, umbra, zenith, "
            "transit, occultation, perihelion. The world feels cosmic and "
            "mathematical.",
        ),
        DiversitySeed(
            "naming_botanical",
            "naming_palette",
            "Use BOTANICAL vocabulary throughout. Power terms should evoke: "
            "graft, root, canopy, spore, bloom, wilt, rhizome, mycelia, "
            "phloem, germination. Power grows like a living thing.",
        ),
        DiversitySeed(
            "naming_textile",
            "naming_palette",
            "Use TEXTILE and WEAVING vocabulary for power terminology. "
            "Forces and techniques should evoke: warp, weft, shuttle, loom, "
            "selvage, bobbin, tension, dye-lot, mordant. Power is woven, "
            "not wielded.",
        ),
        DiversitySeed(
            "naming_weather",
            "naming_palette",
            "Names should evoke WEATHER phenomena. Forces, ranks, and places "
            "should draw from: squall, doldrums, haboob, derecho, petrichor, "
            "virga, graupel, inversion. The world feels atmospheric and wild.",
        ),
        DiversitySeed(
            "naming_architectural",
            "naming_palette",
            "Use ARCHITECTURAL vocabulary for world naming. Power ranks and "
            "places should evoke: buttress, lintel, keystone, vault, corbel, "
            "plinth, cantilever, coping. The world is built, not born.",
        ),
        DiversitySeed(
            "naming_cartographic",
            "naming_palette",
            "Names should draw from CARTOGRAPHIC terms. Forces and places "
            "should evoke: meridian, azimuth, contour, projection, datum, "
            "triangulation, bearing, declination. The world is mapped, "
            "measured, and contested.",
        ),
        DiversitySeed(
            "naming_metallurgical",
            "naming_palette",
            "Use METALLURGICAL vocabulary throughout. Power terms should "
            "evoke: smelt, anneal, quench, slag, crucible, patina, temper, "
            "assay, flux, tarnish. Power is refined, not discovered.",
        ),
        DiversitySeed(
            "naming_entomological",
            "naming_palette",
            "Names should draw from INSECT and ENTOMOLOGICAL vocabulary. "
            "Forces and techniques should evoke: chitin, molt, pheromone, "
            "larval, pupation, compound, mandible, thorax. The world hums "
            "and swarms and transforms.",
        ),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# Seed Selection Algorithm
# ═══════════════════════════════════════════════════════════════════════════


def select_seeds(
    author_tags: list[str],
    num_seeds: int = 4,
    exclude_seeds: set[str] | None = None,
    rng: random.Random | None = None,
    genre: str = "progression_fantasy",
) -> list[DiversitySeed]:
    """Select diversity seeds weighted by author tag compatibility.

    Algorithm:
    1. Score each seed by tag affinity (compatible +2, incompatible → exclude)
    2. Pick one seed from each of the top-scoring categories (ensures variety)
    3. Fill remaining slots with highest-scoring unselected seeds
    4. Guarantee at least one chaos_modifier seed is included

    When no tags are provided, selection is purely random across categories
    for maximum diversity.
    """
    from aiwebnovel.story.genre_config import get_genre_config

    if rng is None:
        rng = random.Random()
    if exclude_seeds is None:
        exclude_seeds = set()

    tag_set = set(author_tags)
    genre_config = get_genre_config(genre)

    # Score all seeds
    scored: list[tuple[float, DiversitySeed]] = []
    for category_name, category_seeds in SEED_BANK.items():
        # Skip entire categories incompatible with this genre
        if category_name in genre_config.incompatible_seed_categories:
            continue
        for seed in category_seeds:
            if seed.id in exclude_seeds:
                continue
            # Exclude if seed has genre_affinity and this genre isn't in it
            if seed.genre_affinity and genre not in seed.genre_affinity:
                continue
            # Exclude if any author tag is in the seed's incompatible set
            if tag_set & seed.incompatible_tags:
                continue
            score = seed.weight
            # Bonus for compatible tags
            matches = tag_set & seed.compatible_tags
            score += len(matches) * 2.0
            # Small random jitter to avoid deterministic selection
            score += rng.random() * 0.5
            scored.append((score, seed))

    if not scored:
        return []

    # Group by category, pick best from each
    by_category: dict[str, list[tuple[float, DiversitySeed]]] = {}
    for score, seed in scored:
        by_category.setdefault(seed.category, []).append((score, seed))

    # Sort each category by score descending
    for cat_seeds in by_category.values():
        cat_seeds.sort(key=lambda x: x[0], reverse=True)

    # Sort categories by their best seed's score
    ranked_categories = sorted(
        by_category.items(),
        key=lambda x: x[1][0][0],
        reverse=True,
    )

    selected: list[DiversitySeed] = []
    used_categories: set[str] = set()

    # Phase 1: one seed per category from top-scoring categories
    for cat_name, cat_seeds in ranked_categories:
        if len(selected) >= num_seeds:
            break
        seed = cat_seeds[0][1]
        selected.append(seed)
        used_categories.add(cat_name)

    # Phase 2: if still need more, pick from remaining high-scorers
    if len(selected) < num_seeds:
        remaining = [
            (score, seed) for score, seed in scored
            if seed not in selected
        ]
        remaining.sort(key=lambda x: x[0], reverse=True)
        for _, seed in remaining:
            if len(selected) >= num_seeds:
                break
            selected.append(seed)

    # Phase 3: guarantee at least one chaos_modifier seed
    has_chaos = any(s.category == "chaos_modifier" for s in selected)
    if not has_chaos and "chaos_modifier" in by_category:
        chaos_candidates = [
            seed for _, seed in by_category["chaos_modifier"]
            if seed not in selected
        ]
        if chaos_candidates:
            chaos_pick = rng.choice(chaos_candidates)
            # Replace the lowest-scored selected seed
            if selected:
                # Find which selected seed had the lowest score
                lowest_idx = 0
                lowest_score = float("inf")
                for i, sel in enumerate(selected):
                    for sc, sd in scored:
                        if sd is sel and sc < lowest_score:
                            lowest_score = sc
                            lowest_idx = i
                            break
                selected[lowest_idx] = chaos_pick

    return selected


# ═══════════════════════════════════════════════════════════════════════════
# Convention Assembly
# ═══════════════════════════════════════════════════════════════════════════


def assemble_genre_conventions(
    author_tags: list[str],
    selected_seeds: list[DiversitySeed],
    custom_conventions: str | None = None,
    anti_repetition: str = "",
    genre: str = "progression_fantasy",
) -> str:
    """Combine all diversity sources into a single genre_conventions string.

    This replaces the old hardcoded _GENRE_CONVENTIONS everywhere.

    Structure:
    - Core genre conventions (from GenreConfig, or BASE_GENRE_CONVENTIONS fallback)
    - Story identity from author tags (if any)
    - Creative constraints from diversity seeds (always present)
    - Author custom conventions (if any)
    - Anti-repetition directives (if any)
    """
    from aiwebnovel.story.genre_config import get_genre_config

    genre_config = get_genre_config(genre)
    sections: list[str] = []

    # 1. Core conventions — genre-specific
    sections.append(f"=== CORE GENRE CONVENTIONS ===\n{genre_config.base_conventions}")

    # 2. Tag directives
    if author_tags:
        tag_text = get_tag_directives(author_tags)
        if tag_text:
            tag_names = ", ".join(
                ALL_TAGS[slug].name for slug in author_tags if slug in ALL_TAGS
            )
            sections.append(
                f"=== STORY IDENTITY ===\n"
                f"This story is tagged: {tag_names}\n\n"
                f"{tag_text}"
            )

    # 3. Diversity seeds — always present
    if selected_seeds:
        seed_lines = "\n".join(f"- {seed.text}" for seed in selected_seeds)
        sections.append(
            f"=== CREATIVE CONSTRAINTS (follow these closely) ===\n{seed_lines}"
        )

    # 4. Author custom conventions
    if custom_conventions and custom_conventions.strip():
        sections.append(
            f"=== AUTHOR CUSTOMIZATIONS ===\n{custom_conventions.strip()}"
        )

    # 5. Anti-repetition
    if anti_repetition and anti_repetition.strip():
        sections.append(
            f"=== AVOID THESE PATTERNS ===\n{anti_repetition.strip()}"
        )

    return "\n\n".join(sections)


# ═══════════════════════════════════════════════════════════════════════════
# Seed Lookup
# ═══════════════════════════════════════════════════════════════════════════

# Flat index built once: seed_id → DiversitySeed
_SEED_INDEX: dict[str, DiversitySeed] = {
    seed.id: seed
    for category_seeds in SEED_BANK.values()
    for seed in category_seeds
}


def get_seed_by_id(seed_id: str) -> DiversitySeed | None:
    """Look up a DiversitySeed from the bank by its id."""
    return _SEED_INDEX.get(seed_id)
