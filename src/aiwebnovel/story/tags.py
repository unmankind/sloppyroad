"""Predefined tag taxonomy for novel creation.

Authors select tags when creating a story. Tags influence world generation
by injecting genre-specific directives into prompts. Tags are also used
for novel discovery and browsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TagDefinition:
    """A single tag that an author can apply to a novel."""

    name: str  # Display name: "Isekai", "Vampires", etc.
    slug: str  # DB value: "isekai", "vampires"
    category: str  # "subgenre", "setting", "tone", etc.
    description: str  # Tooltip for UI
    genre_directive: str  # Injected into prompts when this tag is active
    # Genre slugs this tag is compatible with. Empty = all genres.
    genre_affinity: frozenset[str] = field(default_factory=frozenset)


# ═══════════════════════════════════════════════════════════════════════════
# Tag Catalog — organized by category
# ═══════════════════════════════════════════════════════════════════════════

TAG_CATEGORIES: dict[str, list[TagDefinition]] = {
    # ------------------------------------------------------------------
    # Subgenre — the structural identity of the story
    # ------------------------------------------------------------------
    "subgenre": [
        TagDefinition(
            "Isekai", "isekai", "subgenre",
            "Protagonist transported to another world",
            "This is an isekai story. The protagonist originates from a different "
            "world and carries foreign knowledge, cultural assumptions, and possibly "
            "anachronistic skills. The tension between their origin-world understanding "
            "and the new world's rules is a core narrative driver.",
            genre_affinity=frozenset({"progression_fantasy", "epic_fantasy", "romantasy"}),
        ),
        TagDefinition(
            "Reincarnation", "reincarnation", "subgenre",
            "Protagonist reborn with past-life memories",
            "This is a reincarnation story. The protagonist carries memories from a "
            "previous life. The gap between knowledge and power drives tension — they "
            "know what's coming but lack the strength to change it. Past regrets "
            "inform present choices.",
            genre_affinity=frozenset({"progression_fantasy", "epic_fantasy", "romantasy"}),
        ),
        TagDefinition(
            "System Apocalypse", "system_apocalypse", "subgenre",
            "Game-like system overlays reality",
            "This is a system apocalypse story. A game-like overlay has been imposed "
            "on reality: status screens, level notifications, skill acquisitions, and "
            "dungeon instances are physical facts, not metaphors. Society is being "
            "rebuilt around these new rules.",
            genre_affinity=frozenset({"progression_fantasy"}),
        ),
        TagDefinition(
            "Cultivation", "cultivation", "subgenre",
            "Eastern-inspired qi/energy cultivation",
            "This is a cultivation story. Power growth happens through meditation, "
            "energy circulation, body refinement, and philosophical insight. Sects, "
            "lineages, and master-disciple relationships matter. Pills, formations, "
            "tribulations, and heavenly dao are real elements of the world.",
            genre_affinity=frozenset({"progression_fantasy"}),
        ),
        TagDefinition(
            "LitRPG", "litrpg", "subgenre",
            "Explicit game mechanics, stats, and levels",
            "This is a LitRPG story. The power system includes explicit, visible "
            "game mechanics: numerical stats, skill trees, experience points, loot "
            "tables, and class systems. Characters are aware of and discuss these "
            "mechanics. Include stat blocks where narratively appropriate.",
            genre_affinity=frozenset({"progression_fantasy"}),
        ),
        TagDefinition(
            "Dungeon Core", "dungeon_core", "subgenre",
            "Protagonist is or bonds with a dungeon",
            "This is a dungeon core story. The protagonist IS the dungeon or is "
            "deeply bonded to one. Power growth means designing floors, spawning "
            "monsters, creating traps, and absorbing the essence of delvers. "
            "The perspective is fundamentally non-human or partially so.",
            genre_affinity=frozenset({"progression_fantasy"}),
        ),
        TagDefinition(
            "Tower Climbing", "tower_climbing", "subgenre",
            "Ascending floors of a tower for power",
            "This is a tower climbing story. A massive vertical structure defines "
            "the world. Each floor is its own environment with unique rules. "
            "Ascending is the primary axis of progression. Climbers form parties, "
            "compete, and die on the stairs between worlds.",
            genre_affinity=frozenset({"progression_fantasy"}),
        ),
        TagDefinition(
            "Everyday Ascendancy", "everyday_ascendancy", "subgenre",
            "Power through mundane skill mastery",
            "This is an everyday ascendancy story. The protagonist ascends to power "
            "through mastery of something mundane: cooking, gardening, pottery, "
            "bookkeeping, cleaning, or another ordinary craft. The magic system "
            "integrates and elevates this mundane skill into something cosmic.",
            genre_affinity=frozenset({"progression_fantasy", "romantasy"}),
        ),
        TagDefinition(
            "Academy", "academy", "subgenre",
            "Set in a training institution",
            "This is an academy story. The protagonist attends a training institution "
            "where power is formally taught. Classmates are rivals and allies. "
            "Instructors have hidden agendas. School politics intersect with larger "
            "world conflicts. Rankings and examinations drive short-term arcs.",
        ),
        TagDefinition(
            "Monster Evolution", "monster_evolution", "subgenre",
            "Protagonist is a monster that evolves",
            "This is a monster evolution story. The protagonist IS a non-human "
            "creature that grows by consuming, fighting, or evolving. They gain "
            "new forms, abilities, and eventually sapience or higher intelligence. "
            "The world is experienced from a fundamentally inhuman perspective.",
            genre_affinity=frozenset({"progression_fantasy"}),
        ),
        TagDefinition(
            "Regression", "regression", "subgenre",
            "Protagonist sent back in time with knowledge",
            "This is a regression story. The protagonist has been sent back to an "
            "earlier point in their life with knowledge of the future. They must "
            "navigate the tension between foreknowledge and changed circumstances. "
            "Butterfly effects mean the future they remember is not guaranteed.",
            genre_affinity=frozenset({"progression_fantasy"}),
        ),
        TagDefinition(
            "Base Builder", "base_builder", "subgenre",
            "Building and managing a settlement or territory",
            "This is a base builder story. The protagonist establishes and grows "
            "a settlement, territory, guild, or faction. Resource management, "
            "recruitment, defense, and expansion are core progression axes alongside "
            "personal power growth.",
            genre_affinity=frozenset({"progression_fantasy", "sci_fi"}),
        ),
        TagDefinition(
            "Summoner", "summoner", "subgenre",
            "Protagonist fights through bound entities",
            "This is a summoner story. The protagonist's primary combat method is "
            "through bound, contracted, or tamed entities. Personal power grows by "
            "acquiring, strengthening, and synergizing summons rather than direct "
            "physical or magical combat.",
            genre_affinity=frozenset({"progression_fantasy", "epic_fantasy"}),
        ),
        TagDefinition(
            "Healer", "healer", "subgenre",
            "Protagonist's path is restoration, not destruction",
            "This is a healer-focused story. The protagonist's primary power path "
            "is restoration, mending, and preservation rather than destruction. "
            "This creates different stakes: triage decisions, ethical dilemmas about "
            "who to save, and the psychological weight of being needed by everyone.",
        ),
        TagDefinition(
            "Craftsman", "craftsman", "subgenre",
            "Protagonist advances through crafting/creation",
            "This is a crafting-focused story. The protagonist advances primarily "
            "through creating things: weapons, armor, potions, formations, "
            "constructs, or other artifacts. The creative process IS the cultivation. "
            "Combat exists but is secondary to the forge/workshop/laboratory.",
            genre_affinity=frozenset({"progression_fantasy", "epic_fantasy"}),
        ),
    ],

    # ------------------------------------------------------------------
    # Setting — where and when the story takes place
    # ------------------------------------------------------------------
    "setting": [
        TagDefinition(
            "Sci-Fi", "sci_fi", "setting",
            "Science fiction elements and technology",
            "The setting incorporates science fiction elements: advanced technology, "
            "space travel, artificial intelligence, genetic engineering, or other "
            "speculative science. The power system should interface with technology, "
            "not replace it.",
        ),
        TagDefinition(
            "Urban", "urban", "setting",
            "Modern or contemporary city setting",
            "The setting is urban: a large city or metropolis where modern (or "
            "near-modern) infrastructure coexists with the power system. Streets, "
            "buildings, public transit, and dense populations define the environment.",
        ),
        TagDefinition(
            "Post-Apocalyptic", "post_apocalyptic", "setting",
            "After civilization's collapse",
            "The setting is post-apocalyptic. A previous civilization has fallen "
            "and its ruins contain both power and danger. Survival is a baseline "
            "concern. The old world's technology and knowledge are treasures.",
        ),
        TagDefinition(
            "Undersea", "undersea", "setting",
            "Oceanic or underwater world",
            "The setting is underwater or oceanic. Civilizations exist beneath the "
            "waves: in air pockets, adapted to water breathing, or in magical "
            "environments. Pressure, currents, and the abyss define geography. "
            "Three-dimensional movement is natural.",
        ),
        TagDefinition(
            "Aerial", "aerial", "setting",
            "Floating islands and sky realms",
            "The setting is aerial. There is no ground, or ground is lethal. People "
            "live on floating islands, flying creatures, cloud formations, or "
            "wind-current platforms. Falling is the universal fear. Vertical distance "
            "replaces horizontal distance.",
        ),
        TagDefinition(
            "Subterranean", "subterranean", "setting",
            "Underground civilizations and caverns",
            "The setting is underground. The surface is a myth, a death zone, or "
            "simply unknown. Caves, fungal forests, magma rivers, crystalline "
            "caverns, and bioluminescent ecosystems define geography. Light is "
            "precious. Direction is relative.",
        ),
        TagDefinition(
            "Eastern Fantasy", "eastern_fantasy", "setting",
            "Wuxia/xianxia inspired setting",
            "The setting draws from East Asian fantasy traditions: mountain sects, "
            "jade palaces, spirit beasts, celestial courts, and vast untamed "
            "wilderness. Honor, face, and hierarchical relationships shape society.",
        ),
        TagDefinition(
            "Western Fantasy", "western_fantasy", "setting",
            "Classic medieval European-inspired fantasy",
            "The setting draws from Western medieval fantasy traditions: castles, "
            "kingdoms, knightly orders, guild halls, and frontier towns. Feudal "
            "hierarchies and divine mandates shape political structures.",
        ),
        TagDefinition(
            "Space", "space", "setting",
            "Interplanetary or interstellar setting",
            "The setting spans multiple planets, space stations, or star systems. "
            "The power system operates across the void. Ships, warp travel, and "
            "alien ecosystems are part of the landscape.",
        ),
        TagDefinition(
            "Steampunk", "steampunk", "setting",
            "Victorian-era technology meets magic",
            "The setting blends steam-age technology with the power system: "
            "clockwork constructs, aether engines, dirigibles, and brass-and-glass "
            "laboratories. Industrialization and its consequences are thematic.",
        ),
    ],

    # ------------------------------------------------------------------
    # Tone — the emotional register and narrative feel
    # ------------------------------------------------------------------
    "tone": [
        TagDefinition(
            "Dark", "dark", "tone",
            "Morally gray, heavy consequences",
            "The tone is dark. Choices have permanent, painful consequences. "
            "Morality is genuinely gray. The world does not reward good intentions. "
            "Characters suffer meaningfully, not gratuitously.",
        ),
        TagDefinition(
            "Grimdark", "grimdark", "tone",
            "Bleak, brutal world with cruel systems",
            "The tone is grimdark. The power system is actively cruel. Institutions "
            "are corrupt by design. Happy endings are earned by paying terrible "
            "prices. Betrayal and compromise are survival tools.",
        ),
        TagDefinition(
            "Cozy", "cozy", "tone",
            "Found family, warm moments, low-stakes progression",
            "The tone is cozy. Power growth happens alongside found family, good "
            "meals, comfortable routines, and quiet moments of connection. Violence "
            "may exist but is not the focus. Slice-of-life moments carry equal "
            "narrative weight to action scenes.",
        ),
        TagDefinition(
            "Humorous", "humorous", "tone",
            "Comedy and irreverent protagonist",
            "The tone is humorous. The world takes itself seriously but the "
            "protagonist's perspective is irreverent. Comedy arises naturally from "
            "genre-awareness without breaking the fourth wall. Absurd situations "
            "are played straight.",
        ),
        TagDefinition(
            "Romantic", "romantic", "tone",
            "Romance as a major narrative thread",
            "Romance is a significant narrative element. Relationship development "
            "carries as much weight as power progression. Emotional vulnerability "
            "is a form of strength. The love interest has their own arc and agency.",
        ),
        TagDefinition(
            "Philosophical", "philosophical", "tone",
            "Ideas and ethics are central themes",
            "The tone is philosophical. Characters genuinely debate the ethics of "
            "power, the nature of consciousness, and the meaning of advancement. "
            "Intellectual conflicts carry as much weight as physical ones. "
            "The story asks questions it doesn't fully answer.",
        ),
        TagDefinition(
            "Horror", "horror", "tone",
            "Dread, cosmic horror, body horror elements",
            "Horror elements are prominent. Power is terrifying. Advancement changes "
            "practitioners in ways that frighten the people who love them. The "
            "unknown is genuinely threatening. Cosmic indifference or malice lurks "
            "behind the power system.",
        ),
        TagDefinition(
            "Heroic", "heroic", "tone",
            "Classic heroism, clear good vs. evil",
            "The tone is heroic. The protagonist is genuinely good and strives to "
            "do the right thing. Evil is real and worth fighting. Sacrifices are "
            "noble. Hope is justified, even when the odds are grim.",
        ),
        TagDefinition(
            "Satirical", "satirical", "tone",
            "Social commentary through genre conventions",
            "The tone is satirical. The power system and its institutions serve as "
            "commentary on real-world systems: bureaucracy, capitalism, academia, "
            "or social hierarchies. Played straight but pointed.",
        ),
    ],

    # ------------------------------------------------------------------
    # Voice & style — prose style, POV, narrative voice
    # ------------------------------------------------------------------
    "voice_and_style": [
        TagDefinition(
            "First Person", "first_person", "voice_and_style",
            "Narrated in first person (I/me)",
            "Write in FIRST PERSON perspective. The protagonist narrates directly "
            "using 'I' and 'me'. The reader sees only what the narrator perceives "
            "and knows. Voice, bias, and personality bleed into every description. "
            "Unreported events are invisible.",
        ),
        TagDefinition(
            "Present Tense", "present_tense", "voice_and_style",
            "Written in present tense",
            "Write in PRESENT TENSE. Events unfold as the reader watches: 'I walk', "
            "'she says', 'the blade cuts'. This creates immediacy and removes the "
            "safety of retrospection. The narrator does not know what happens next.",
        ),
        TagDefinition(
            "Omniscient Narrator", "omniscient", "voice_and_style",
            "All-knowing narrator with access to multiple minds",
            "Use an OMNISCIENT narrative voice. The narrator knows what every "
            "character thinks and feels, can comment on events with irony or "
            "foreshadowing, and may address the reader directly. The narrator "
            "has personality and perspective separate from any character.",
        ),
        TagDefinition(
            "Sparse Prose", "sparse_prose", "voice_and_style",
            "Minimalist, Hemingway-style prose",
            "Write in a SPARSE, minimalist style. Short sentences. Few adjectives. "
            "Let action and dialogue carry the weight. Descriptions are precise and "
            "essential — no ornament. Emotion is implied by what characters do, not "
            "what the narrator explains they feel. Trust the reader.",
        ),
        TagDefinition(
            "Lush Prose", "lush_prose", "voice_and_style",
            "Rich, literary, densely descriptive writing",
            "Write in LUSH, literary prose. Descriptions are sensory-rich and layered. "
            "Metaphor and imagery are tools, not decoration. Sentences vary from long "
            "and flowing to sharp and punctuating. The prose itself is a pleasure to "
            "read, with attention to rhythm, sound, and texture.",
        ),
        TagDefinition(
            "Dialogue-Heavy", "dialogue_heavy", "voice_and_style",
            "Conversations drive the narrative forward",
            "The prose is DIALOGUE-HEAVY. Conversations drive scenes forward. "
            "Characters reveal themselves through what they say and how they say it. "
            "Subtext matters — what is left unsaid is as important as what is spoken. "
            "Minimize narration between dialogue beats.",
        ),
        TagDefinition(
            "Introspective", "introspective", "voice_and_style",
            "Deep internal monologue and psychological depth",
            "The prose is deeply INTROSPECTIVE. The protagonist's internal monologue "
            "is rich, complex, and honest. Thought processes are shown in real-time. "
            "External events are filtered through psychological response. The inner "
            "world is as detailed as the outer world.",
        ),
        TagDefinition(
            "Action-Forward", "action_forward", "voice_and_style",
            "Kinetic, fast-paced prose focused on movement",
            "The prose is ACTION-FORWARD. Paragraphs move. Fight scenes are "
            "choreographed beat by beat. Chase sequences use short sentences and "
            "present-tense verbs. Even non-combat scenes maintain kinetic energy. "
            "Characters are always doing something, not just thinking or talking.",
        ),
        TagDefinition(
            "Sardonic Voice", "sardonic_voice", "voice_and_style",
            "Dry, witty, cynical narrative voice",
            "The narrative voice is SARDONIC. The protagonist (or narrator) observes "
            "the world with dry wit and earned cynicism. Observations are sharp and "
            "often funny. The humor is a defense mechanism that occasionally drops "
            "to reveal genuine feeling underneath.",
        ),
        TagDefinition(
            "Lyrical", "lyrical", "voice_and_style",
            "Poetic, rhythmic prose with musicality",
            "The prose is LYRICAL. Sentence rhythm matters. Repetition, parallelism, "
            "and cadence are deliberate tools. Passages read almost like poetry in "
            "places. The musicality of the language reinforces emotional beats. "
            "Sound and meaning work together.",
        ),
        TagDefinition(
            "Epistolary", "epistolary", "voice_and_style",
            "Told through letters, journals, reports, or documents",
            "Portions of the narrative are EPISTOLARY — told through in-world "
            "documents: letters, journal entries, official reports, recovered notes, "
            "transcripts, or system logs. These fragments provide information the "
            "main narrative cannot, and their voice differs from the prose sections.",
        ),
    ],

    # ------------------------------------------------------------------
    # Creature type — beings central to the world
    # ------------------------------------------------------------------
    "creature_type": [
        TagDefinition(
            "Vampires", "vampires", "creature_type",
            "Vampire-centric elements and themes",
            "Vampires are a significant presence in this world. Blood, immortality, "
            "predation, and the tension between humanity and hunger should influence "
            "the power system, politics, or protagonist's nature.",
        ),
        TagDefinition(
            "Dragons", "dragons", "creature_type",
            "Dragons are central to the world",
            "Dragons are a significant presence: as apex predators, ancient powers, "
            "bonded companions, or a source of cultivation resources. Their biology, "
            "hierarchy, and relationship with humanoids shapes the world.",
        ),
        TagDefinition(
            "Undead", "undead", "creature_type",
            "Necromancy and undead themes",
            "Undead and necromancy are significant elements. Death is not the end "
            "but a transition. The power system interacts with death energy, soul "
            "manipulation, or the boundary between life and undeath.",
        ),
        TagDefinition(
            "Eldritch", "eldritch", "creature_type",
            "Lovecraftian/cosmic horror entities",
            "Eldritch beings exist beyond normal comprehension. The power system "
            "brushes against entities whose logic is alien and whose attention is "
            "dangerous. Sanity and identity are resources that can be spent.",
        ),
        TagDefinition(
            "Beastkin", "beastkin", "creature_type",
            "Animal-human hybrid races",
            "Beastkin or animal-human hybrid species are part of the world. "
            "Different beast lineages have distinct cultural traditions, power "
            "affinities, and social dynamics with pure humans.",
        ),
        TagDefinition(
            "Fae", "fae", "creature_type",
            "Fairy/fae courts and wild magic",
            "Fae creatures and their courts are a significant presence. Bargains, "
            "true names, and wild magic that follows narrative logic rather than "
            "physical law. Beauty that is dangerous. Promises that bind reality.",
        ),
        TagDefinition(
            "Demons", "demons", "creature_type",
            "Demonic entities and infernal politics",
            "Demons or infernal entities are part of the world's fabric. Contracts, "
            "corruption, and temptation are real forces. The power system may involve "
            "dealing with entities whose interests are opposed to mortal wellbeing.",
        ),
        TagDefinition(
            "Spirits", "spirits", "creature_type",
            "Nature spirits, ancestral spirits, or elemental beings",
            "Spirits inhabit the world: nature spirits, ancestral ghosts, elemental "
            "beings, or echoes of the dead. The power system involves communication, "
            "negotiation, or bonding with these entities.",
        ),
    ],

    # ------------------------------------------------------------------
    # Protagonist type — who the main character is
    # ------------------------------------------------------------------
    "protagonist_type": [
        TagDefinition(
            "Female Lead", "female_lead", "protagonist_type",
            "Female protagonist",
            "The protagonist is female. Her experiences, relationships, and "
            "challenges should be shaped by but not reduced to her gender. Avoid "
            "male-gaze framing.",
        ),
        TagDefinition(
            "Non-Human Lead", "nonhuman_lead", "protagonist_type",
            "Monster, spirit, AI, or non-human protagonist",
            "The protagonist is not human: a monster, spirit, golem, AI, or other "
            "non-human entity. Their perception and priorities are fundamentally "
            "different from human norms. Do not simply write a human in a costume.",
        ),
        TagDefinition(
            "Older Lead", "older_lead", "protagonist_type",
            "Protagonist over 40 years old",
            "The protagonist is middle-aged or older (40+). They have a lifetime "
            "of experience, regrets, relationships, and possibly children. Their "
            "body may be a limitation. Wisdom competes with declining vitality.",
        ),
        TagDefinition(
            "Child Lead", "child_lead", "protagonist_type",
            "Protagonist under 14 years old",
            "The protagonist is a child (under 14). Write a genuine child: curious, "
            "emotionally volatile, dependent on adults, processing the world through "
            "limited experience. NOT an adult mind in a child's body.",
        ),
        TagDefinition(
            "Villain Lead", "villain_lead", "protagonist_type",
            "Protagonist is morally gray or villainous",
            "The protagonist would be the villain in someone else's story. They "
            "may be selfish, ruthless, or pursuing goals that harm others. Make "
            "their perspective compelling without excusing their actions.",
        ),
        TagDefinition(
            "Ensemble", "ensemble", "protagonist_type",
            "Multiple POV characters with equal weight",
            "The story has an ensemble cast. While one character may anchor the "
            "narrative, 3-4 characters share roughly equal narrative weight with "
            "their own arcs, growth, and perspective chapters.",
        ),
        TagDefinition(
            "Anti-Hero", "anti_hero", "protagonist_type",
            "Morally complex protagonist who breaks rules",
            "The protagonist is an anti-hero: willing to use morally questionable "
            "methods for their goals. They break rules, deceive allies, and make "
            "compromises that traditional heroes would refuse.",
        ),
    ],

    # ------------------------------------------------------------------
    # Theme — narrative themes and emotional cores
    # ------------------------------------------------------------------
    "theme": [
        TagDefinition(
            "Found Family", "found_family", "theme",
            "Building bonds and chosen family",
            "Found family is a central theme. The protagonist builds deep bonds "
            "with people who become more important than blood relations. The party/"
            "group dynamic carries emotional weight equal to the main plot.",
        ),
        TagDefinition(
            "Revenge", "revenge", "theme",
            "Vengeance as a driving motivation",
            "Revenge is a primary motivation. The protagonist has been wronged and "
            "seeks justice or retribution. Explore whether revenge fulfills or "
            "hollows. The target of revenge should be compelling, not cartoonish.",
        ),
        TagDefinition(
            "Redemption", "redemption", "theme",
            "Protagonist seeking atonement",
            "Redemption is a central theme. The protagonist has done something "
            "terrible and seeks to atone. Their past is not erased by good deeds "
            "but must be lived with. Forgiveness is earned, not given.",
        ),
        TagDefinition(
            "Political Intrigue", "political_intrigue", "theme",
            "Court politics, faction warfare, scheming",
            "Political intrigue is central. Factions maneuver for advantage. "
            "Alliances shift. Information is a weapon. The protagonist must navigate "
            "systems where strength alone is insufficient.",
        ),
        TagDefinition(
            "Survival", "survival", "theme",
            "Staying alive against overwhelming odds",
            "Survival is the primary concern. The world is hostile enough that "
            "merely staying alive is an achievement. Resources are scarce. Every "
            "encounter could be lethal. Power growth serves survival first.",
        ),
        TagDefinition(
            "Mystery", "mystery", "theme",
            "Central mystery driving the plot",
            "A core mystery drives the narrative. The protagonist uncovers layers "
            "of hidden truth. Clues are planted fairly. The answer recontextualizes "
            "everything the reader thought they knew.",
        ),
        TagDefinition(
            "Romance", "romance", "theme",
            "Romantic relationship as major subplot",
            "Romance is a significant subplot. Relationship development is given "
            "narrative space and emotional depth. The love interest has their own "
            "arc. Romance complicates and enriches the power progression.",
        ),
    ],

    # ------------------------------------------------------------------
    # Content — content style and structural preferences
    # ------------------------------------------------------------------
    "content": [
        TagDefinition(
            "Harem", "harem", "content",
            "Multiple romantic interests simultaneously",
            "Multiple romantic interests develop simultaneously. Handle each "
            "relationship with genuine emotional depth rather than collecting "
            "partners as trophies. Each love interest has agency and their own arc.",
        ),
        TagDefinition(
            "Gore", "gore", "content",
            "Graphic violence and body horror",
            "Violence is depicted graphically. Combat has visceral, physical "
            "consequences. Injuries are described in detail. Body horror elements "
            "may be present. Power has a physical cost that is shown, not implied.",
        ),
        TagDefinition(
            "No Romance", "no_romance", "content",
            "Minimal or no romantic subplots",
            "Romance is absent or minimal. Relationships are platonic, familial, "
            "or professional. The narrative focus stays on power progression, "
            "world exploration, and non-romantic character bonds.",
        ),
        TagDefinition(
            "Slow Burn", "slow_burn", "content",
            "Gradual power progression and plot development",
            "Progression is deliberately slow. Training arcs are long and detailed. "
            "Breakthroughs take many chapters to earn. The reader should feel every "
            "step of the climb. Quick power-ups are explicitly avoided.",
        ),
        TagDefinition(
            "Fast-Paced", "fast_paced", "content",
            "Rapid plot progression and frequent action",
            "The pacing is fast. Action scenes are frequent. Plot developments "
            "come quickly. Downtime exists but is brief. The reader should feel "
            "propelled forward at all times.",
        ),
    ],

    # ------------------------------------------------------------------
    # Relationship type — romantic dynamic (primarily romantasy)
    # ------------------------------------------------------------------
    "relationship_type": [
        TagDefinition(
            "M/F Romance", "mf_romance", "relationship_type",
            "Male/female central romance",
            "The central romance is between a man and a woman. Write their "
            "dynamic with emotional depth — the pairing is classic but the "
            "relationship should feel specific to these characters.",
            genre_affinity=frozenset({"romantasy"}),
        ),
        TagDefinition(
            "M/M Romance", "mm_romance", "relationship_type",
            "Male/male central romance",
            "The central romance is between two men. Write with authenticity "
            "and emotional depth, not fetishization. Their masculinity and "
            "vulnerability coexist naturally.",
            genre_affinity=frozenset({"romantasy"}),
        ),
        TagDefinition(
            "F/F Romance", "ff_romance", "relationship_type",
            "Female/female central romance",
            "The central romance is between two women. Write with authenticity "
            "and emotional depth, not fetishization. Their dynamic should feel "
            "genuine and specific to these characters.",
            genre_affinity=frozenset({"romantasy"}),
        ),
        TagDefinition(
            "Polyamorous", "polyamorous", "relationship_type",
            "Multiple romantic relationships with mutual knowledge",
            "Multiple romantic relationships develop with the knowledge and "
            "consent of all parties. Each relationship has distinct dynamics, "
            "tensions, and joys. This is NOT a harem — all partners have "
            "agency and the arrangement is negotiated, not collected.",
            genre_affinity=frozenset({"romantasy"}),
        ),
        TagDefinition(
            "Interspecies Romance", "interspecies_romance", "relationship_type",
            "Romance crossing species boundaries",
            "The central romance crosses species boundaries. Lean into the "
            "genuine alienness — different bodies, lifespans, senses, values, "
            "and communication modes. The differences are the tension AND the "
            "fascination. Do not simply write a human in a costume.",
            genre_affinity=frozenset({"romantasy", "sci_fi"}),
        ),
        TagDefinition(
            "Fated Lovers", "fated_lovers", "relationship_type",
            "Cosmically destined romantic connection",
            "The romantic leads are cosmically destined — prophecy, soul bonds, "
            "or divine design draws them together. But fate provides the "
            "CONNECTION, not the relationship. They must still choose each "
            "other. The tension is whether destiny is a gift or a cage.",
            genre_affinity=frozenset({"romantasy", "epic_fantasy"}),
        ),
        TagDefinition(
            "Forbidden Love", "forbidden_love", "relationship_type",
            "Romance forbidden by law, culture, or magic",
            "The romance is forbidden — by law, culture, faction allegiance, "
            "or magical taboo. The cost of being together is real and "
            "escalating. Every stolen moment risks everything. The question "
            "is whether love is worth what it destroys.",
            genre_affinity=frozenset({"romantasy", "epic_fantasy"}),
        ),
        TagDefinition(
            "Slow Burn Romance", "slow_burn_romance", "relationship_type",
            "Agonizingly gradual romantic development",
            "The romantic tension builds across many chapters. The first kiss "
            "is an EVENT. Every accidental touch, loaded glance, and almost-"
            "moment ratchets the tension higher. Delay gratification — make "
            "the reader ache for it.",
            genre_affinity=frozenset({"romantasy"}),
        ),
        TagDefinition(
            "Enemies to Lovers", "enemies_to_lovers", "relationship_type",
            "Romance between genuine adversaries",
            "The romantic leads begin as genuine adversaries. Neither is "
            "pretending — the hatred is real, and so is the attraction that "
            "complicates it. The shift from antagonism to vulnerability is "
            "gradual, reluctant, and earned through shared experience.",
            genre_affinity=frozenset({"romantasy"}),
        ),
        TagDefinition(
            "Power Couple", "power_couple", "relationship_type",
            "Both leads are formidable in their own right",
            "Both romantic leads are formidable — powerful, competent, and "
            "dangerous in their own right. The romance makes them more "
            "dangerous together. Neither completes the other; they are whole "
            "people who choose partnership.",
            genre_affinity=frozenset({"romantasy", "epic_fantasy"}),
        ),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# Flat lookups
# ═══════════════════════════════════════════════════════════════════════════

ALL_TAGS: dict[str, TagDefinition] = {
    td.slug: td
    for tds in TAG_CATEGORIES.values()
    for td in tds
}

ALL_TAG_NAMES: dict[str, TagDefinition] = {
    td.name: td
    for tds in TAG_CATEGORIES.values()
    for td in tds
}


def validate_tags(tag_slugs: list[str]) -> list[str]:
    """Return list of invalid tag slugs. Empty list means all valid."""
    return [s for s in tag_slugs if s not in ALL_TAGS]


def get_tags_for_genre(genre: str) -> dict[str, list[TagDefinition]]:
    """Return TAG_CATEGORIES filtered to tags compatible with the given genre.

    Tags with empty genre_affinity are compatible with all genres.
    """
    result: dict[str, list[TagDefinition]] = {}
    for category, tags in TAG_CATEGORIES.items():
        filtered = [
            t for t in tags
            if not t.genre_affinity or genre in t.genre_affinity
        ]
        if filtered:
            result[category] = filtered
    return result


def get_tag_directives(tag_slugs: list[str]) -> str:
    """Resolve tag slugs to their genre directives, combined into a block.

    Returns empty string if no valid tags provided.
    """
    directives: list[str] = []
    for slug in tag_slugs:
        td = ALL_TAGS.get(slug)
        if td:
            directives.append(f"- [{td.category.upper()}: {td.name}] {td.genre_directive}")
    return "\n".join(directives)
