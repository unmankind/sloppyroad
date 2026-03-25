"""Prompt templates for all LLM interactions.

Every template is a PromptTemplate dataclass with system and user prompts,
recommended temperature, max_tokens, and an optional response parser.
Templates are organised by system and accessible as module-level constants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from aiwebnovel.llm.parsers import (
    AntagonistsResponse,
    ArcPlanResult,
    ArcSummaryResult,
    ButterflyChoiceResult,
    ChapterPlanResult,
    ChapterSummaryResult,
    CosmologyResponse,
    CurrentStateResponse,
    EnhancedRecapResult,
    GeographyResponse,
    HistoryResponse,
    ImagePromptResult,
    NarrativeAnalysisResult,
    OracleFilterResult,
    PlotThreadResult,
    PowerSystemResponse,
    ProtagonistResponse,
    SupportingCastResponse,
    SystemAnalysisResult,
)


@dataclass
class PromptTemplate:
    """A reusable LLM prompt template with recommended generation params."""

    name: str
    system_prompt: str
    user_template: str
    response_parser: type[BaseModel] | None = None
    temperature: float = 0.7
    max_tokens: int = 4000
    # Fields that must appear in the user_template
    required_context_keys: list[str] = field(default_factory=list)

    def render(self, **context: Any) -> tuple[str, str]:
        """Return (system, user) prompt pair with placeholders filled.

        Missing context keys are replaced with empty strings to prevent
        KeyError during optional-section rendering.
        """
        user = self.user_template
        for key, value in context.items():
            user = user.replace("{" + key + "}", str(value))
        # Replace any remaining placeholders with empty string
        import re
        user = re.sub(r"\{[a-z_]+\}", "", user)
        return self.system_prompt, user


# ---------------------------------------------------------------------------
# Shared system-prompt fragments
# ---------------------------------------------------------------------------

_WORLD_BUILDER_SYSTEM = (
    "You are a world-builder specialising in progression fantasy. "
    "Be concise: use 1-2 sentences per field unless the prompt specifies otherwise. "
    "Focus on what makes this world unique — skip generic fantasy filler. "
    "Respond ONLY with valid JSON. No markdown, no code fences, no commentary — "
    "just the raw JSON object."
)

_GENRE_CONVENTIONS_DEFAULT = (
    "Progression fantasy conventions: earned power growth through struggle and "
    "sacrifice, hard magic systems with clear rules and meaningful costs, "
    "escalating scope from personal to cosmic, training arcs that show process "
    "not montage, competent protagonists with clear weaknesses, foreshadowing "
    "that rewards attentive readers."
)

_ANTI_PATTERNS = (
    "DO NOT:\n"
    "- Grant unearned power or sudden convenient abilities\n"
    "- Info-dump worldbuilding in exposition blocks\n"
    "- Break established power system rules or world laws\n"
    "- Use modern Earth idioms, slang, or cultural references\n"
    "- Summarise when you should show\n"
    "- Resolve tension too quickly or conveniently\n"
    "- Make the protagonist succeed without meaningful struggle\n"
    "- Introduce deus ex machina solutions"
)


# ═══════════════════════════════════════════════════════════════════════════
# WORLD PIPELINE (8 templates)
# ═══════════════════════════════════════════════════════════════════════════


COSMOLOGY = PromptTemplate(
    name="cosmology",
    system_prompt=_WORLD_BUILDER_SYSTEM,
    user_template=(
        "Given that this is a progression fantasy novel, design the cosmology "
        "and metaphysics of this world.\n\n"
        "{novel_title_context}"
        "Genre conventions to respect:\n{genre_conventions}\n\n"
        "{prior_context}\n\n"
        "Generate a JSON object with these keys:\n"
        '- "fundamental_forces": Array of 1-3 fundamental forces/energies. Each must '
        "have: name, description (1-2 sentences), mortal_interaction (1 sentence), "
        "extreme_concentration_effect (1 sentence).\n"
        '- "planes_of_existence": Array of 2-4 planes/realms. Each: name, description '
        "(1-2 sentences), accessibility_requirements (1 sentence), "
        "native_inhabitants (1 sentence).\n"
        '- "cosmic_laws": Array of 3-5 inviolable rules that govern ALL reality '
        '(each with a "description" field, 1-2 sentences).\n'
        '- "energy_types": Array of 1-3 energy types mortals can cultivate. Each: '
        "name, source, properties, fundamental_force, interactions (all 1 sentence each).\n"
        '- "reality_tiers": Array of 3-5 tiers of reality, from mundane to cosmic. '
        "Each: tier_name, description (1-2 sentences), power_ceiling_description (1 sentence), "
        "beings (1 sentence), qualitative_change (1 sentence).\n\n"
        "CRITICAL: Reality tiers must feel QUALITATIVELY different. Higher tiers "
        "should mean fundamentally different relationships with reality, not just "
        "bigger numbers.\n\n"
        "Be concise. Focus on what's unique, not generic fantasy filler."
    ),
    response_parser=CosmologyResponse,
    temperature=0.95,
    max_tokens=8000,
    required_context_keys=["genre_conventions"],
)


POWER_SYSTEM = PromptTemplate(
    name="power_system",
    system_prompt=_WORLD_BUILDER_SYSTEM,
    user_template=(
        "You are building the power/magic system for a progression fantasy novel.\n\n"
        "{novel_title_context}"
        "Here is the established cosmology:\n{prior_context}\n\n"
        "Genre conventions:\n{genre_conventions}\n\n"
        "Design a power system that:\n"
        "1. Has CLEAR RULES -- readers should be able to predict what is/isn't possible\n"
        "2. Has MEANINGFUL COSTS -- every power use costs something\n"
        "3. Has a PROGRESSION LADDER -- ranks that take genuine effort to climb\n"
        "4. Has MULTIPLE PATHS -- at least 3 distinct disciplines/traditions\n"
        "5. Has SYNERGIES -- combining paths creates emergent effects\n"
        "6. Has a CEILING -- and hints at what lies beyond it\n\n"
        "Generate JSON:\n"
        '- "system_name": The name of this power system\n'
        '- "core_mechanic": How power fundamentally works (1-2 paragraphs)\n'
        '- "energy_source": What practitioners draw from, how it connects to cosmology\n'
        '- "ranks": Array of 3-12 ranks. Each: rank_name, rank_order, description, '
        "typical_capabilities, advancement_requirements, advancement_bottleneck, "
        "population_ratio, qualitative_shift\n"
        '- "disciplines": Array of 3-6 paths. Each: name, philosophy, source_energy, '
        "strengths, weaknesses, typical_practitioners, synergies_with\n"
        '- "advancement_mechanics": training_methods, breakthrough_triggers, '
        "failure_modes, regression_conditions\n"
        '- "hard_limits": Array of things that are IMPOSSIBLE regardless of power level\n'
        '- "soft_limits": Array of things possible but impractical/dangerous\n'
        '- "power_ceiling": What the absolute peak looks like'
    ),
    response_parser=PowerSystemResponse,
    temperature=0.95,
    max_tokens=8000,
    required_context_keys=["prior_context", "genre_conventions"],
)


GEOGRAPHY = PromptTemplate(
    name="geography",
    system_prompt=_WORLD_BUILDER_SYSTEM,
    user_template=(
        "Design the STARTING REGION for this progression fantasy world — where the "
        "protagonist begins their journey. Use a 'fog of war' approach: detail the "
        "immediate setting richly, sketch neighboring areas briefly, and leave distant "
        "regions as named stubs to be expanded when the story needs them.\n\n"
        "{novel_title_context}"
        "Established context:\n{prior_context}\n\n"
        "Genre conventions:\n{genre_conventions}\n\n"
        "Generate JSON:\n"
        '- "regions": Array of 4-8 regions. The FIRST region is the starting area '
        "(detailed: 2-3 paragraphs). 1-2 neighboring regions (1 paragraph each). "
        "Remaining regions are stubs (1-2 sentences, marked with stub: true). "
        "Each: name, description, parent_region (null if top-level), climate, "
        "notable_features, political_entity, stub (boolean, default false)\n"
        '- "factions": Array of 3-5 factions relevant to the starting area. '
        "Each: name, description, territory, goals, resources, relationships\n"
        '- "political_entities": Array of 1-3. Each: name, government_type, '
        "description, factions\n\n"
        "The starting region should have immediate dangers, opportunities for a "
        "low-ranked cultivator, and hints of what lies beyond."
    ),
    response_parser=GeographyResponse,
    temperature=0.7,
    max_tokens=8000,
    required_context_keys=["prior_context", "genre_conventions"],
)


HISTORY = PromptTemplate(
    name="history",
    system_prompt=_WORLD_BUILDER_SYSTEM,
    user_template=(
        "Design the history of this progression fantasy world. Focus on 3-5 eras "
        "with the most narrative relevance — what shaped the current conflicts and "
        "what mysteries might the protagonist uncover?\n\n"
        "{novel_title_context}"
        "Established context:\n{prior_context}\n\n"
        "Genre conventions:\n{genre_conventions}\n\n"
        "Generate JSON:\n"
        '- "eras": Array of 3-5 historical eras. Each: era_name, duration, '
        "description (1-2 paragraphs), defining_events (array of strings)\n"
        '- "events": Array of 3-6 pivotal events. Each: name, era, description '
        "(1 paragraph), consequences, key_figures (array of names)\n"
        '- "key_figures": Array of 3-5 legendary figures. Each: name, era, role, '
        "legacy (1-2 sentences)\n\n"
        "Be concise — prioritize narrative hooks over exhaustive detail."
    ),
    response_parser=HistoryResponse,
    temperature=0.7,
    max_tokens=8000,
    required_context_keys=["prior_context", "genre_conventions"],
)


CURRENT_STATE = PromptTemplate(
    name="current_state",
    system_prompt=_WORLD_BUILDER_SYSTEM,
    user_template=(
        "Define the current state of the world at the story's start.\n\n"
        "{novel_title_context}"
        "Established context:\n{prior_context}\n\n"
        "Genre conventions:\n{genre_conventions}\n\n"
        "Generate JSON:\n"
        '- "active_conflicts": Array. Each: name, parties (list), description, stakes\n'
        '- "political_landscape": String overview of political tensions\n'
        '- "power_balance": String describing the current balance of power\n\n'
        "The current state should provide fertile ground for a protagonist starting "
        "from the bottom of the power hierarchy."
    ),
    response_parser=CurrentStateResponse,
    temperature=0.7,
    max_tokens=8000,
    required_context_keys=["prior_context", "genre_conventions"],
)


PROTAGONIST = PromptTemplate(
    name="protagonist",
    system_prompt=_WORLD_BUILDER_SYSTEM,
    user_template=(
        "Design the protagonist for this progression fantasy novel.\n\n"
        "{novel_title_context}"
        "{character_identities}\n\n"
        "Established world:\n{prior_context}\n\n"
        "Genre conventions:\n{genre_conventions}\n\n"
        "The protagonist MUST:\n"
        "1. Start WEAK -- at or near the bottom of the power hierarchy\n"
        "2. Have a COMPELLING motivation that drives them upward\n"
        "3. Have a DISADVANTAGE that makes their path harder than normal\n"
        "4. Have an UNUSUAL TRAIT that lets them find unconventional solutions\n"
        "5. Have a hidden connection to the world's deeper mysteries\n"
        "6. Be someone readers can root for -- flawed but sympathetic\n\n"
        "Generate JSON:\n"
        '- "name": Full name (USE THE NAME FROM CHARACTER IDENTITY ABOVE)\n'
        '- "age": Starting age (integer)\n'
        '- "background": 2-3 paragraphs of history\n'
        '- "personality": core_traits, flaws, strengths, fears, desires (all arrays)\n'
        '- "starting_power": current_rank, discipline (or null), latent_abilities (or null)\n'
        '- "disadvantage": What makes their path harder\n'
        '- "unusual_trait": What makes them different\n'
        '- "hidden_connection": Connection to deeper world (for author, not revealed early)\n'
        '- "motivation": surface_motivation, deep_motivation\n'
        '- "initial_circumstances": Where they are when the story begins\n'
        '- "arc_trajectory": High-level description of their growth arc\n'
        '- "visual_appearance": 1-2 sentences describing how this character LOOKS '
        "(build, coloring, distinguishing features, species if non-human). "
        "Used for portrait generation."
    ),
    response_parser=ProtagonistResponse,
    temperature=0.95,
    max_tokens=8000,
    required_context_keys=["prior_context", "genre_conventions"],
)


ANTAGONISTS = PromptTemplate(
    name="antagonists",
    system_prompt=_WORLD_BUILDER_SYSTEM,
    user_template=(
        "Design the antagonists for this progression fantasy novel.\n\n"
        "{novel_title_context}"
        "{character_identities}\n\n"
        "Established world and protagonist:\n{prior_context}\n\n"
        "Genre conventions:\n{genre_conventions}\n\n"
        "Each antagonist should:\n"
        "- Have a MOTIVATION that makes sense from their perspective\n"
        "- Be at a HIGHER power level than the protagonist (for now)\n"
        "- Create DISTINCT types of conflict (physical, political, ideological)\n"
        "- Have their own arc and growth potential\n\n"
        "Generate JSON:\n"
        '- "antagonists": Array (2+). Each: name, role, power_level, motivation, '
        "relationship_to_protagonist, threat_type, visual_appearance "
        "(1-2 sentences: build, coloring, distinguishing features, species if non-human)"
    ),
    response_parser=AntagonistsResponse,
    temperature=0.8,
    max_tokens=8000,
    required_context_keys=["prior_context", "genre_conventions"],
)


SUPPORTING_CAST = PromptTemplate(
    name="supporting_cast",
    system_prompt=_WORLD_BUILDER_SYSTEM,
    user_template=(
        "Design the supporting cast for this progression fantasy novel.\n\n"
        "{novel_title_context}"
        "{character_identities}\n\n"
        "Established world, protagonist, and antagonists:\n{prior_context}\n\n"
        "Genre conventions:\n{genre_conventions}\n\n"
        "Each supporting character should:\n"
        "- Serve a NARRATIVE PURPOSE (mentor, rival, friend, foil, etc.)\n"
        "- Have their own goals that sometimes align, sometimes conflict\n"
        "- Bring out different aspects of the protagonist's personality\n"
        "- Feel like real people, not archetypes\n\n"
        "Generate JSON:\n"
        '- "characters": Array (3+). Each: name, role, connection_to_protagonist, '
        "narrative_purpose, personality_sketch, visual_appearance "
        "(1-2 sentences: build, coloring, distinguishing features, species if non-human)"
    ),
    response_parser=SupportingCastResponse,
    temperature=0.8,
    max_tokens=8000,
    required_context_keys=["prior_context", "genre_conventions"],
)


# ═══════════════════════════════════════════════════════════════════════════
# POST-WORLD GENERATION (2 templates)
# ═══════════════════════════════════════════════════════════════════════════


NOVEL_TITLE = PromptTemplate(
    name="novel_title",
    system_prompt=(
        "You are a bestselling fantasy author naming a new novel. "
        "Respond with ONLY the title — no quotes, no punctuation, no explanation."
    ),
    user_template=(
        "Generate a compelling, evocative title for a progression fantasy novel "
        "set in this world.\n\n"
        "WORLD SUMMARY:\n{world_summary}\n\n"
        "CREATIVE IDENTITY (what makes this world unique):\n{creative_identity}\n\n"
        "{title_constraints}\n\n"
        "The title should be:\n"
        "- 2-6 words, memorable and punchy\n"
        "- Evocative of the world's UNIQUE identity, not generic fantasy\n"
        "- Something that would look good on a book cover\n"
        "- NOT generic (avoid 'The Chosen One', 'Rise of Power', etc.)\n"
        "- Draw from the creative identity and naming palette above\n\n"
        "Respond with ONLY the title. Nothing else."
    ),
    response_parser=None,
    temperature=0.95,
    max_tokens=50,
    required_context_keys=["world_summary"],
)


NOVEL_SYNOPSIS = PromptTemplate(
    name="novel_synopsis",
    system_prompt=(
        "You are a bestselling-novel copywriter. Your job is to write "
        "back-cover hooks — the kind that make someone pick up a book in a "
        "store and refuse to put it down.\n\n"
        "Rules:\n"
        "- Mystery over explanation. Tease, never tell.\n"
        "- Emotional stakes over world mechanics. The reader must feel something.\n"
        "- Short, punchy sentences. Vary rhythm. Let lines breathe.\n"
        "- ONE evocative detail about the world — not a geography lesson.\n"
        "- ONE hint of the power/magic — with sensory language, not system specs.\n"
        "- The protagonist's personal stakes must be the beating heart.\n"
        "- End on a line that creates a physical urge to turn the page.\n"
        "- NEVER use phrases like 'In a world where…' or 'must embark on a "
        "journey…'\n\n"
        "Respond with ONLY the synopsis text — no headings, no labels, no preamble."
    ),
    user_template=(
        "Write a back-cover hook for this progression fantasy novel. "
        "Two short paragraphs. 100-150 words MAX.\n\n"
        "PROTAGONIST:\n{protagonist_summary}\n\n"
        "WORLD & CONFLICT (reference only — do NOT regurgitate):\n"
        "{world_context}\n\n"
        "CONSTRAINTS:\n"
        "- Do NOT explain the magic system or cosmology. Hint at power with "
        "evocative, sensory language.\n"
        "- Do NOT list world details. Pick ONE vivid image that captures the "
        "world's feel.\n"
        "- Focus on the protagonist: who they are, what they want, what "
        "stands in their way, what they'll lose.\n"
        "- First paragraph: hook the reader with the protagonist's situation "
        "and one striking world detail.\n"
        "- Second paragraph: escalate the tension. End with urgency.\n\n"
        "DON'T write: 'In a world governed by seventeen tiers of reality, "
        "where ancient cosmic laws dictate the flow of ethereal energy…'\n"
        "DO write: 'She was born in the lowest tier, where even the "
        "light felt borrowed.'\n\n"
        "Write ONLY the synopsis. No preamble, no labels."
    ),
    response_parser=None,
    temperature=0.8,
    max_tokens=500,
    required_context_keys=["protagonist_summary"],
)


# ═══════════════════════════════════════════════════════════════════════════
# PLANNING (4 templates)
# ═══════════════════════════════════════════════════════════════════════════


ARC_PLANNING = PromptTemplate(
    name="arc_planning",
    system_prompt=(
        "You are the narrative architect for a progression fantasy serial novel. Your "
        "job is to plan multi-chapter story arcs that deliver compelling, escalating "
        "narrative with earned character growth, coherent plot threads, and satisfying "
        "payoffs.\n\n"
        "You must balance:\n"
        "- Long-term plot progression with immediate chapter-level engagement\n"
        "- Character development with action and worldbuilding\n"
        "- Tension escalation with necessary rest periods\n"
        "- Resolving existing threads while introducing new ones\n"
        "- Honouring the power system's earned-advancement rules\n\n"
        "Output structured JSON matching the requested schema exactly."
    ),
    user_template=(
        "Plan the next story arc for this novel.\n\n"
        "CURRENT STATE:\n"
        "- Current chapter: {current_chapter}\n"
        "- Escalation phase: {escalation_phase}\n"
        "- Scope tier: {scope_tier}\n"
        "- Story tags: {story_tags}\n\n"
        "ACTIVE PLOT THREADS:\n{active_threads}\n\n"
        "CHARACTER STATES:\n{character_states}\n\n"
        "ACTIVE CHEKHOV GUNS (narrative promises needing resolution):\n{chekhov_guns}\n\n"
        "READER INTEREST:\n{reader_signals}\n\n"
        "RECENT STORY SUMMARIES:\n{recent_summaries}\n\n"
        "ARC HISTORY (most recent first):\n{arc_history}\n\n"
        "OUTSTANDING PROMISES FROM PREVIOUS ARC (must address):\n"
        "{outstanding_promises}\n\n"
        "AUTHOR GUIDANCE (incorporate if provided):\n{author_guidance}\n\n"
        "NEXT ARC MUST START AT CHAPTER: {next_chapter_start}\n\n"
        "Generate a SINGLE JSON object with EXACTLY these top-level keys "
        "(no wrapper, no metadata, no extra nesting):\n"
        '- "title": string — Arc title (evocative, not spoilery)\n'
        '- "description": string — 2-3 paragraph summary of what this arc accomplishes\n'
        '- "target_chapter_start": integer — MUST be {next_chapter_start}\n'
        '- "target_chapter_end": integer — start + 5 to 8 chapters\n'
        '- "key_events": array — Ordered events. Each object: event_order (int), '
        "description (string), chapter_target (int or null), "
        "characters_involved (array of strings)\n"
        '- "character_arcs": array — Per-character goals. Each object: character_name, '
        "arc_goal, starting_state, ending_state\n"
        '- "themes": array — Thematic elements. Each object: theme, how_explored\n\n'
        "RESPOND WITH ONLY THE JSON OBJECT. No commentary before or after.\n\n"
        "CONSTRAINTS:\n"
        "- High-pressure Chekhov guns (>0.7) MUST be addressed in this arc\n"
        "- Power advancements must feel EARNED -- plan the struggle BEFORE the gain\n"
        "- At least one plot thread should see meaningful progress\n"
        "- Include at least one rest/character-bonding beat\n"
        "- The arc should end at a natural narrative inflection point"
    ),
    response_parser=ArcPlanResult,
    temperature=0.7,
    max_tokens=8000,
    required_context_keys=["current_chapter", "escalation_phase", "scope_tier"],
)


ARC_REVISION = PromptTemplate(
    name="arc_revision",
    system_prompt=(
        "You are revising a story arc plan based on author feedback. Maintain the "
        "overall narrative quality while incorporating the requested changes. "
        "Output structured JSON matching the requested schema exactly."
    ),
    user_template=(
        "Revise this arc plan based on the author's notes.\n\n"
        "CURRENT ARC PLAN:\n{current_arc_plan}\n\n"
        "AUTHOR'S REVISION NOTES:\n{author_notes}\n\n"
        "CONSTRAINTS (still apply):\n"
        "- Power advancements must feel EARNED\n"
        "- Maintain narrative coherence with existing threads\n"
        "- Keep the arc between 5-8 chapters\n\n"
        "Generate a revised JSON arc plan with the same schema as before:\n"
        "title, description, target_chapter_start, target_chapter_end, key_events, "
        "character_arcs, themes."
    ),
    response_parser=ArcPlanResult,
    temperature=0.7,
    max_tokens=8000,
    required_context_keys=["current_arc_plan", "author_notes"],
)


CHAPTER_PLANNING = PromptTemplate(
    name="chapter_planning",
    system_prompt=(
        "You are planning a single chapter within a larger story arc. Create a "
        "detailed scene-by-scene outline that serves the arc's goals while being "
        "a satisfying chapter in its own right.\n\n"
        "Each chapter should have 3-5 scenes with clear beats, emotional movement, "
        "and a compelling reason for the reader to continue to the next chapter.\n\n"
        "Output structured JSON matching the requested schema exactly."
    ),
    user_template=(
        "Plan Chapter {chapter_number} of this novel.\n\n"
        "ARC CONTEXT:\n"
        '- Arc: "{arc_title}"\n'
        "- Arc description: {arc_description}\n"
        "- Position in arc: {arc_position}\n"
        "- Key events for this chapter: {relevant_arc_events}\n\n"
        "POV CHARACTER: {pov_character}\n\n"
        "TARGET TENSION: {tension_target}\n\n"
        "CHEKHOV DIRECTIVES (follow these):\n{chekhov_directives}\n\n"
        "ACTIVE PLOT THREADS:\n{active_threads}\n\n"
        "{reader_signals}\n\n"
        "Generate a JSON chapter plan:\n"
        '- "title": Chapter title\n'
        '- "scenes": Array of 3-5 scenes. Each: description, beats (array of '
        "strings), emotional_trajectory\n"
        '- "target_tension": float 0.0-1.0'
    ),
    response_parser=ChapterPlanResult,
    temperature=0.7,
    max_tokens=3000,
    required_context_keys=["chapter_number", "arc_title"],
)


PLOT_THREAD_EXTRACTION = PromptTemplate(
    name="plot_thread_extraction",
    system_prompt=(
        "You are a narrative analyst. Extract active plot threads from a chapter "
        "analysis. Each thread should be a distinct narrative question, conflict, "
        "or character arc that requires future resolution.\n\n"
        "Output structured JSON."
    ),
    user_template=(
        "Extract plot threads from this chapter analysis.\n\n"
        "CHAPTER SUMMARY:\n{chapter_summary}\n\n"
        "KEY EVENTS:\n{key_events}\n\n"
        "EXISTING THREADS:\n{existing_threads}\n\n"
        "Generate JSON:\n"
        '- "threads": Array. Each: name, description, thread_type '
        "(main/subplot/character_arc/mystery/relationship), related_characters\n\n"
        "Include both NEW threads introduced and UPDATED existing threads."
    ),
    response_parser=PlotThreadResult,
    temperature=0.5,
    max_tokens=2000,
    required_context_keys=["chapter_summary"],
)


# ═══════════════════════════════════════════════════════════════════════════
# CHAPTER GENERATION (1 template, heavily parameterised)
# ═══════════════════════════════════════════════════════════════════════════


CHAPTER_GENERATION = PromptTemplate(
    name="chapter_generation",
    system_prompt=(
        "You are a master storyteller writing a progression fantasy serial novel. "
        "Your prose should be immersive, vivid, and propulsive. Each chapter must "
        "feel like a complete reading experience while advancing the larger story.\n\n"
        "WRITING PRINCIPLES:\n"
        "- Show, don't tell. Use concrete sensory details, not abstract statements.\n"
        "- Dialogue should reveal character, advance plot, or build tension -- never "
        "all three at once.\n"
        "- Action scenes should be tactical and grounded in the power system's rules.\n"
        "- Internal monologue should feel authentic to the POV character's voice and "
        "knowledge.\n"
        "- Pacing should vary: tension needs valleys to make peaks feel high.\n"
        "- End on a hook: a question, revelation, danger, or emotional turning point.\n\n"
        f"{_ANTI_PATTERNS}\n\n"
        "SCENE ILLUSTRATIONS:\n"
        "At up to 3 moments of high visual significance, you may insert a scene marker "
        "on its own line between paragraphs: [SCENE: 1-2 sentence visual description]\n"
        "Focus on composition, lighting, mood, and key visual elements. Only mark truly "
        "striking or pivotal moments — not every scene deserves one.\n\n"
        "Write the chapter as flowing prose. No JSON. No meta-commentary. Just the "
        "story.\n\n"
        "WORLD FIDELITY (CRITICAL):\n"
        "- You MUST use the world elements provided in WORLD CONTEXT exactly as defined.\n"
        "- Use the protagonist's EXACT name, age, background, and abilities from the world data.\n"
        "- Use the EXACT power system name, ranks, and mechanics. Do NOT invent alternatives.\n"
        "- Set the story in the EXACT locations defined in the geography. Do NOT invent "
        "alternative settings.\n"
        "- Reference the defined factions, antagonists, and history. Do NOT replace them.\n"
        "- If the world data says the protagonist is a 47-year-old immortal in a desert, "
        "do NOT write about a 17-year-old orphan in an urban city.\n\n"
        "CHAPTER STRUCTURE:\n"
        "- End on a natural stopping point: a scene break, cliffhanger, or moment of "
        "decision.\n"
        "- The chapter must feel complete and self-contained, not truncated mid-scene.\n"
        "- If approaching the word limit, wrap up the current scene gracefully rather "
        "than starting a new one."
    ),
    user_template=(
        "Write Chapter {chapter_number}: \"{chapter_title}\"\n\n"
        "=== WORLD CONTEXT ===\n{world_context}\n\n"
        "=== POWER SYSTEM CONTEXT ===\n{power_context}\n\n"
        "=== ESCALATION CONTEXT ===\n{escalation_context}\n\n"
        "=== PREVIOUS CHAPTER RECAP ===\n{enhanced_recap}\n\n"
        "=== STORY BIBLE (relevant entries) ===\n{story_bible_entries}\n\n"
        "=== CHAPTER PLAN ===\n{chapter_plan}\n\n"
        "=== PERSPECTIVE FILTER ===\n{perspective_filter}\n\n"
        "=== READER INFLUENCE ===\n{reader_influence}\n\n"
        "=== PROTAGONIST ===\n{protagonist_context}\n\n"
        "=== CAST (characters in this chapter) ===\n{cast_context}\n\n"
        "=== CHEKHOV DIRECTIVES ===\n{chekhov_directives}\n\n"
        "=== NAME EXCLUSIONS ===\n{name_exclusions}\n\n"
        "=== DIVERSITY / CREATIVE CONSTRAINTS ===\n{diversity_seeds}\n\n"
        "=== VOICE & STYLE ===\n{voice_style_directives}\n\n"
        "{content_rating_directive}\n\n"
        "Target word count: {target_word_count}\n"
        "Target tension: {target_tension}\n\n"
        "REMINDER: You MUST use the exact protagonist name, power system, and setting "
        "from the WORLD CONTEXT above. Do NOT invent alternative names or systems.\n\n"
        "Write the complete chapter. End on a natural stopping point — a scene break, "
        "cliffhanger, or moment of decision. The chapter must feel complete, not truncated."
    ),
    response_parser=None,  # Raw prose, not structured
    temperature=0.7,
    max_tokens=12000,
    required_context_keys=["chapter_number", "chapter_title"],
)


# ═══════════════════════════════════════════════════════════════════════════
# POST-CHAPTER ANALYSIS (2 consolidated templates)
# ═══════════════════════════════════════════════════════════════════════════


NARRATIVE_ANALYSIS = PromptTemplate(
    name="narrative_analysis",
    system_prompt=(
        "You are a narrative analyst for a progression fantasy serial novel. You "
        "extract structured information from a chapter: what happened, how the "
        "tension moved, what narrative promises were made or paid off, and what "
        "facts should be recorded in the story bible.\n\n"
        "Be precise. Do not fabricate details not present in the chapter text.\n"
        "Output valid JSON matching the requested schema exactly."
    ),
    user_template=(
        'Analyse chapter {chapter_number} of "{novel_title}".\n\n'
        "CHAPTER PLAN (what was intended):\n{chapter_plan_summary}\n\n"
        "CURRENT ESCALATION STATE:\n"
        "- Scope tier: {current_tier_name} (Tier {tier_order})\n"
        "- Narrative phase: {current_phase}\n"
        "- Target tension: {target_tension_range}\n\n"
        "EXISTING FORESHADOWING SEEDS:\n{planted_seeds}\n\n"
        "CHAPTER TEXT:\n{chapter_text}\n\n"
        "Extract:\n"
        "1. key_events: Every narratively significant event. Each with: description, "
        "emotional_beat, characters_involved, narrative_importance (minor/moderate/"
        "major/pivotal).\n"
        "2. overall_emotional_arc: The chapter's emotion-to-emotion trajectory.\n"
        "3. tension_level: Final tension 0.0-1.0.\n"
        "4. tension_phase: rest/buildup/confrontation/climax/resolution/aftermath.\n"
        "5. new_foreshadowing_seeds: New hints planted. Each: description, seed_type "
        "(rumor/artifact/character_mention/event_echo/power_anomaly/mystery), "
        "target_scope_tier (int or null), subtlety (subtle/moderate/overt).\n"
        "6. foreshadowing_references: Existing seeds reinforced or paid off. Each: "
        "existing_seed_description, reference_type (reinforced/partially_paid_off/"
        "fully_paid_off), payoff_description.\n"
        "7. bible_entries_to_extract: New/changed facts. Each: entry_type, content, "
        "entity_types, entity_names, is_public_knowledge, supersedes_description.\n"
        "8. cliffhanger_description: How the chapter ends (null if resolves cleanly).\n\n"
        "Return JSON matching NarrativeAnalysisResult."
    ),
    response_parser=NarrativeAnalysisResult,
    temperature=0.3,
    max_tokens=8000,
    required_context_keys=["chapter_number", "novel_title", "chapter_text"],
)


SYSTEM_ANALYSIS = PromptTemplate(
    name="system_analysis",
    system_prompt=(
        "You are a continuity and rules enforcer for a progression fantasy novel. "
        "You check whether a chapter respects the power system rules, the story "
        "bible, and the Chekhov gun lifecycle. You also score any power advancement "
        "events using the 4-rule Earned Power framework (Struggle, Foundation, Cost, "
        "Buildup), each 0.00-0.25.\n\n"
        "Be rigorous. Unearned power gains and continuity errors damage reader trust "
        "and must be flagged.\n"
        "Output valid JSON matching the requested schema exactly."
    ),
    user_template=(
        'Audit chapter {chapter_number} of "{novel_title}" for system compliance.\n\n'
        "POWER SYSTEM:\n"
        "- Name: {power_system_name}\n"
        "- Core mechanic: {core_mechanic}\n"
        "- Hard limits: {hard_limits}\n\n"
        "CHARACTER POWER PROFILE ({protagonist_name}):\n"
        "- Current rank: {current_rank} (rank {rank_order} of {total_ranks})\n"
        "- Primary discipline: {primary_discipline}\n"
        "- Advancement progress: {advancement_progress}\n"
        "- Current bottleneck: {bottleneck_description}\n"
        "- Known abilities: {abilities_with_proficiency}\n\n"
        "RECENT CHAPTER SUMMARIES (last 5):\n{recent_summaries}\n\n"
        "STORY BIBLE CONTEXT:\n{bible_entries}\n\n"
        "ACTIVE CHEKHOV GUNS:\n{active_guns}\n\n"
        "CHAPTER TEXT:\n{chapter_text}\n\n"
        "Check:\n"
        "1. power_events: Every power-related event. Each: character_name, event_type "
        "(rank_up/new_ability/ability_mastery/insight/power_loss/training_progress), "
        "description, struggle_context, sacrifice_or_cost, foundation, "
        "narrative_buildup_chapters, new_rank, ability_name, training_progress_delta.\n"
        "2. earned_power_evaluations: For each rank_up or new_ability event, score the "
        "4 rules. Each: character_name, event_description, struggle_score (0-0.25), "
        "struggle_reasoning, foundation_score (0-0.25), foundation_reasoning, "
        "cost_score (0-0.25), cost_reasoning, buildup_score (0-0.25), "
        "buildup_reasoning, total_score, approved (total >= 0.5), reasoning.\n"
        "3. ability_usages: How abilities were used. Each: character_name, ability_name, "
        "context, proficiency_indication (improving/stable/struggling).\n"
        "4. consistency_issues: Contradictions with bible facts. Each: description, "
        "severity (minor/moderate/critical), bible_entry_content, suggested_fix.\n"
        "5. chekhov_interactions: Gun interactions. Each: gun_description, "
        "interaction_type (new_gun/touched/advanced/resolved/subverted), details, "
        "resolution_description, subversion_description.\n"
        "6. has_critical_violations: true if any critical consistency issue or any "
        "earned power evaluation has approved=false.\n\n"
        "Return JSON matching SystemAnalysisResult."
    ),
    response_parser=SystemAnalysisResult,
    temperature=0.2,
    max_tokens=8000,
    required_context_keys=["chapter_number", "novel_title", "chapter_text"],
)


# ═══════════════════════════════════════════════════════════════════════════
# CHAPTER SUMMARIES (3 templates)
# ═══════════════════════════════════════════════════════════════════════════


STANDARD_SUMMARY = PromptTemplate(
    name="standard_summary",
    system_prompt=(
        "You are a concise narrative summariser for a progression fantasy serial. "
        "Produce a ~300-token summary capturing key events, emotional arc, and "
        "any cliffhangers. Output valid JSON only."
    ),
    user_template=(
        "Summarise Chapter {chapter_number}.\n\n"
        "CHAPTER TEXT:\n{chapter_text}\n\n"
        "Generate JSON:\n"
        '- "summary": ~300-token prose summary covering key events\n'
        '- "key_events": Array of key event strings\n'
        '- "emotional_arc": One-sentence emotional trajectory\n'
        '- "cliffhangers": Array of unresolved hooks (empty if none)'
    ),
    response_parser=ChapterSummaryResult,
    temperature=0.3,
    max_tokens=2000,
    required_context_keys=["chapter_number", "chapter_text"],
)


ARC_SUMMARY = PromptTemplate(
    name="arc_summary",
    system_prompt=(
        "You are creating a meta-summary of a completed story arc in a "
        "progression fantasy serial. Capture the arc's overall narrative movement, "
        "character growth, and narrative promises. Output valid JSON only."
    ),
    user_template=(
        'Summarise the completed arc "{arc_title}".\n\n'
        "ARC PLAN:\n{arc_plan}\n\n"
        "CHAPTER SUMMARIES:\n{chapter_summaries}\n\n"
        "Generate JSON:\n"
        '- "arc_summary": 2-3 paragraph summary of the arc\n'
        '- "key_themes": Array of themes explored\n'
        '- "character_growth": Array of character development milestones\n'
        '- "promises_fulfilled": Narrative promises resolved in this arc\n'
        '- "promises_outstanding": Promises still open after this arc'
    ),
    response_parser=ArcSummaryResult,
    temperature=0.3,
    max_tokens=2000,
    required_context_keys=["arc_title", "chapter_summaries"],
)


ENHANCED_RECAP = PromptTemplate(
    name="enhanced_recap",
    system_prompt=(
        'You are generating a structured "Enhanced Recap" of a novel chapter. This '
        "recap will be used as context for writing the NEXT chapter, replacing the "
        "full chapter text. It must capture everything a skilled author would need to "
        "continue the prose seamlessly: sensory continuity, emotional states, open "
        "threads, and the exact shape of the hook.\n\n"
        "Be precise and specific. Vague summaries are useless. Concrete details are "
        "what matter.\n\n"
        "Output valid JSON only. No markdown fences."
    ),
    user_template=(
        "Generate an Enhanced Recap for Chapter {chapter_number}.\n\n"
        "POV character: {pov_character_name}\n"
        "Characters who may appear: {scene_character_names}\n\n"
        "Full chapter text:\n{chapter_text}\n\n"
        "Return a JSON object:\n"
        '"final_scene_snapshot": Dense ~300-token third-person present-tense '
        "description of the final scene. Include: exact location, time of day, "
        "character positions, physical environment, sensory details.\n\n"
        '"emotional_state": Array of per-character emotional states at chapter end. '
        "Each: character, state (2-3 sentences), unresolved_tension.\n\n"
        '"active_dialogue_threads": Object: last_exchange (last 2-4 lines verbatim), '
        "conversation_topic, what_was_left_unsaid, promises_or_oaths. Null fields if "
        "no dialogue was active.\n\n"
        '"cliffhanger": Object or null: description, question_raised, '
        "reader_expectation, stakes.\n\n"
        '"immediate_pending_actions": Array: character, action, constraint.\n\n'
        '"chapter_arc_beat": Object: what_was_accomplished, what_remains, '
        "arc_phase_note."
    ),
    response_parser=EnhancedRecapResult,
    temperature=0.3,
    max_tokens=3000,
    required_context_keys=["chapter_number", "chapter_text"],
)


# ═══════════════════════════════════════════════════════════════════════════
# FINAL ARC (1 template)
# ═══════════════════════════════════════════════════════════════════════════


FINAL_ARC_PLANNING = PromptTemplate(
    name="final_arc_planning",
    system_prompt=(
        "You are planning the FINAL ARC of a progression fantasy serial novel. "
        "This is the culmination of everything. Every open plot thread, every "
        "Chekhov gun, every character arc must be resolved. The story must reach "
        "a satisfying conclusion.\n\n"
        "Output structured JSON matching the requested schema exactly."
    ),
    user_template=(
        "Plan the FINAL ARC for this novel.\n\n"
        "CURRENT STATE:\n"
        "- Current chapter: {current_chapter}\n"
        "- Escalation phase: {escalation_phase}\n"
        "- Scope tier: {scope_tier}\n\n"
        "ALL OPEN PLOT THREADS (MUST be resolved):\n{open_threads}\n\n"
        "ALL ACTIVE CHEKHOV GUNS (MUST be resolved):\n{chekhov_guns}\n\n"
        "CHARACTER ARCS (MUST reach conclusion):\n{character_arcs}\n\n"
        "STORY SUMMARY SO FAR:\n{story_summary}\n\n"
        "REQUIRED STRUCTURAL BEATS:\n"
        "- Climax: The peak confrontation\n"
        "- Falling Action: Consequences of the climax\n"
        "- Resolution: All threads tied off\n"
        "- Epilogue: Where characters end up\n\n"
        "Generate a JSON arc plan with:\n"
        "title, description, target_chapter_start, target_chapter_end, key_events, "
        "character_arcs, themes.\n\n"
        "MANDATORY: Every open thread and Chekhov gun listed above MUST appear in "
        "key_events with a concrete resolution plan."
    ),
    response_parser=ArcPlanResult,
    temperature=0.7,
    max_tokens=5000,
    required_context_keys=["current_chapter", "open_threads", "chekhov_guns"],
)


# ═══════════════════════════════════════════════════════════════════════════
# IMAGE PROMPTING (3 templates)
# ═══════════════════════════════════════════════════════════════════════════


CHARACTER_PORTRAIT = PromptTemplate(
    name="character_portrait",
    system_prompt=(
        "You are translating narrative character descriptions into image generation "
        "prompts. Output structured JSON with a positive prompt (what to include), "
        "negative prompt (what to avoid), style tags, and aspect ratio.\n\n"
        "The positive prompt should be detailed and visual, focusing on physical "
        "appearance, expression, clothing, and atmospheric elements. Do NOT include "
        "text, watermarks, or signatures."
    ),
    user_template=(
        "Create an image prompt for this character portrait.\n\n"
        "CHARACTER:\n{character_description}\n\n"
        "ART STYLE: {art_style}\n\n"
        "Generate JSON:\n"
        '- "positive_prompt": Detailed visual description for image generation\n'
        '- "negative_prompt": Elements to avoid\n'
        '- "style_tags": Array of style descriptors\n'
        '- "aspect_ratio": One of 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3'
    ),
    response_parser=ImagePromptResult,
    temperature=0.6,
    max_tokens=1000,
    required_context_keys=["character_description"],
)


MAP_PROMPT = PromptTemplate(
    name="map_prompt",
    system_prompt=(
        "You are translating geographic descriptions into fantasy map image "
        "generation prompts. Output structured JSON. The prompt should describe "
        "a top-down or perspective fantasy map with clear geographic features."
    ),
    user_template=(
        "Create an image prompt for a fantasy map.\n\n"
        "GEOGRAPHY:\n{geography_description}\n\n"
        "REGIONS TO INCLUDE:\n{regions}\n\n"
        "ART STYLE: {art_style}\n\n"
        "Generate JSON:\n"
        '- "positive_prompt": Detailed map description\n'
        '- "negative_prompt": Elements to avoid\n'
        '- "style_tags": Array of style descriptors\n'
        '- "aspect_ratio": One of 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3'
    ),
    response_parser=ImagePromptResult,
    temperature=0.6,
    max_tokens=1000,
    required_context_keys=["geography_description"],
)


SCENE_ILLUSTRATION = PromptTemplate(
    name="scene_illustration",
    system_prompt=(
        "You are translating a narrative scene into an image generation prompt. "
        "Capture the emotional tone, lighting, composition, and key visual elements. "
        "Output structured JSON."
    ),
    user_template=(
        "Create an image prompt for this scene.\n\n"
        "SCENE DESCRIPTION:\n{scene_description}\n\n"
        "CHARACTERS PRESENT:\n{characters}\n\n"
        "MOOD: {mood}\n\n"
        "ART STYLE: {art_style}\n\n"
        "Generate JSON:\n"
        '- "positive_prompt": Detailed scene description for image generation\n'
        '- "negative_prompt": Elements to avoid\n'
        '- "style_tags": Array of style descriptors\n'
        '- "aspect_ratio": One of 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3'
    ),
    response_parser=ImagePromptResult,
    temperature=0.6,
    max_tokens=1000,
    required_context_keys=["scene_description"],
)


COVER_ART = PromptTemplate(
    name="cover_art",
    system_prompt=(
        "You are designing book cover art for a fantasy novel. Create a dramatic, "
        "evocative image prompt that captures the essence of the story — its world, "
        "protagonist, and power system — in a single striking composition.\n\n"
        "Think like a cover artist: bold composition, strong focal point, atmospheric "
        "lighting, genre-appropriate mood. The image should make someone want to read "
        "the book. Output structured JSON.\n\n"
        "IMPORTANT: The aspect ratio MUST be 2:3 (portrait orientation, like a book cover)."
    ),
    user_template=(
        "Create a book cover art prompt for this fantasy novel.\n\n"
        "GENRE: {genre}\n\n"
        "WORLD ATMOSPHERE:\n{world_summary}\n\n"
        "PROTAGONIST:\n{protagonist_description}\n\n"
        "POWER SYSTEM:\n{power_system}\n\n"
        "ART STYLE: {art_style}\n\n"
        "Design a cover with this composition:\n"
        "- FOREGROUND: Protagonist figure — use their visual description for accuracy\n"
        "- BACKGROUND: The most distinctive world element (landmark, sky, magic)\n"
        "- COMPOSITION: 2:3 portrait orientation, protagonist lower-center, "
        "world feature behind/above\n"
        "- UPPER PORTION: Leave the top ~25% relatively clear/atmospheric for title overlay\n"
        "- Conveys genre and tone immediately at both thumbnail and full size\n"
        "- Uses dramatic lighting and atmospheric depth\n\n"
        "Generate JSON:\n"
        '- "positive_prompt": Detailed cover art description for image generation\n'
        '- "negative_prompt": Elements to avoid (include: text, title, words, '
        "letters, watermark, signature)\n"
        '- "style_tags": Array of style descriptors\n'
        '- "aspect_ratio": Must be "2:3"'
    ),
    response_parser=ImagePromptResult,
    temperature=0.7,
    max_tokens=1000,
    required_context_keys=["genre", "world_summary"],
)


IMAGE_REGENERATION = PromptTemplate(
    name="image_regeneration",
    system_prompt=(
        "You are revising an image generation prompt based on author feedback. "
        "The author has seen the previous image and wants specific changes. "
        "Preserve everything from the original that the author did NOT ask to change. "
        "Apply the requested changes precisely while maintaining visual consistency "
        "with the art style. Output structured JSON."
    ),
    user_template=(
        "Revise this {asset_type} image prompt based on author feedback.\n\n"
        "ORIGINAL CONTEXT:\n{original_context}\n\n"
        "ORIGINAL IMAGE PROMPT:\n{original_prompt}\n\n"
        "AUTHOR FEEDBACK (changes requested):\n{feedback}\n\n"
        "ART STYLE: {art_style}\n\n"
        "Instructions:\n"
        "- Keep all elements the author did NOT mention changing\n"
        "- Apply the requested changes as precisely as possible\n"
        "- Maintain consistency with the art style guide\n"
        "- If the feedback is vague, interpret it generously\n\n"
        "Generate JSON:\n"
        '- "positive_prompt": Revised detailed image description\n'
        '- "negative_prompt": Elements to avoid\n'
        '- "style_tags": Array of style descriptors\n'
        '- "aspect_ratio": Keep same as original unless feedback changes it'
    ),
    response_parser=ImagePromptResult,
    temperature=0.7,
    max_tokens=1000,
    required_context_keys=["asset_type", "original_prompt", "feedback"],
)


# ═══════════════════════════════════════════════════════════════════════════
# READER INFLUENCE (2 templates)
# ═══════════════════════════════════════════════════════════════════════════


ORACLE_QUESTION_FILTER = PromptTemplate(
    name="oracle_question_filter",
    system_prompt=(
        "You are validating whether a reader's question to the 'Oracle' is "
        "appropriate for the story. Valid questions ask about world lore, character "
        "motivations, or mysteries. Invalid questions try to control the plot, "
        "request spoilers, or are off-topic.\n\n"
        "Output valid JSON."
    ),
    user_template=(
        "Is this reader question appropriate for the Oracle?\n\n"
        "QUESTION: {question}\n\n"
        "CURRENT STORY STATE:\n{story_state}\n\n"
        "Generate JSON:\n"
        '- "is_valid": boolean\n'
        '- "reason": Why this is valid or invalid\n'
        '- "suggested_revelation_timing": If valid, when in the story this might be '
        "answered (null if invalid)"
    ),
    response_parser=OracleFilterResult,
    temperature=0.3,
    max_tokens=500,
    required_context_keys=["question", "story_state"],
)


BUTTERFLY_CHOICE_GENERATOR = PromptTemplate(
    name="butterfly_choice_generator",
    system_prompt=(
        "You are creating a thematic binary choice for readers of a progression "
        "fantasy serial. The choice should feel meaningful, connect to the current "
        "narrative, and have genuine consequences -- but should not break the story. "
        "Both options should be interesting.\n\n"
        "Output valid JSON."
    ),
    user_template=(
        "Create a Butterfly Choice for the current narrative state.\n\n"
        "CURRENT NARRATIVE:\n{narrative_state}\n\n"
        "ACTIVE THEMES:\n{active_themes}\n\n"
        "PROTAGONIST STATE:\n{protagonist_state}\n\n"
        "Generate JSON:\n"
        '- "choice_text_a": First option text (2-3 sentences)\n'
        '- "choice_text_b": Second option text (2-3 sentences)\n'
        '- "thematic_tension": What thematic tension this choice embodies\n'
        '- "narrative_consequences_a": What choosing A would influence\n'
        '- "narrative_consequences_b": What choosing B would influence'
    ),
    response_parser=ButterflyChoiceResult,
    temperature=0.7,
    max_tokens=1000,
    required_context_keys=["narrative_state"],
)


# ---------------------------------------------------------------------------
# Registry for easy lookup by name
# ---------------------------------------------------------------------------

ALL_TEMPLATES: dict[str, PromptTemplate] = {
    t.name: t
    for t in [
        COSMOLOGY, POWER_SYSTEM, GEOGRAPHY, HISTORY, CURRENT_STATE,
        PROTAGONIST, ANTAGONISTS, SUPPORTING_CAST,
        NOVEL_TITLE, NOVEL_SYNOPSIS,
        ARC_PLANNING, ARC_REVISION, CHAPTER_PLANNING, PLOT_THREAD_EXTRACTION,
        CHAPTER_GENERATION,
        NARRATIVE_ANALYSIS, SYSTEM_ANALYSIS,
        STANDARD_SUMMARY, ARC_SUMMARY, ENHANCED_RECAP,
        FINAL_ARC_PLANNING,
        CHARACTER_PORTRAIT, MAP_PROMPT, SCENE_ILLUSTRATION, COVER_ART,
        ORACLE_QUESTION_FILTER, BUTTERFLY_CHOICE_GENERATOR,
    ]
}
