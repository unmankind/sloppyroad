"""Pydantic v2 response parsers for all LLM output shapes.

Every structured response from an LLM call is parsed into one of these models.
Validators enforce domain-specific constraints (score ranges, required fields,
cross-field consistency).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _coerce_to_str(v: Any) -> str:
    """Coerce dicts/lists to JSON string, pass strings through."""
    if isinstance(v, str):
        return v
    return json.dumps(v)


# ═══════════════════════════════════════════════════════════════════════════
# WORLD PIPELINE PARSERS (8 stages)
# ═══════════════════════════════════════════════════════════════════════════


class FundamentalForce(BaseModel):
    name: str
    description: str
    mortal_interaction: str
    extreme_concentration_effect: str


class PlaneOfExistence(BaseModel):
    name: str
    description: str
    accessibility_requirements: str
    native_inhabitants: str


class CosmicLaw(BaseModel):
    description: str


class EnergyType(BaseModel):
    name: str
    source: str
    properties: str
    fundamental_force: str
    interactions: str


class RealityTier(BaseModel):
    tier_name: str
    description: str
    power_ceiling_description: str
    beings: str
    qualitative_change: str


class CosmologyResponse(BaseModel):
    """Stage 1: Cosmology and metaphysics of the world."""

    fundamental_forces: list[FundamentalForce] = Field(min_length=1)
    planes_of_existence: list[PlaneOfExistence] = Field(min_length=1)
    cosmic_laws: list[CosmicLaw] = Field(min_length=1)
    energy_types: list[EnergyType] = Field(min_length=1)
    reality_tiers: list[RealityTier] = Field(min_length=1)

    @model_validator(mode="after")
    def truncate_lists(self) -> CosmologyResponse:
        """Gracefully cap list lengths — never crash on LLM overgeneration."""
        self.fundamental_forces = self.fundamental_forces[:8]
        self.planes_of_existence = self.planes_of_existence[:8]
        self.cosmic_laws = self.cosmic_laws[:6]
        self.energy_types = self.energy_types[:8]
        self.reality_tiers = self.reality_tiers[:10]
        return self


class PowerRank(BaseModel):
    rank_name: str
    rank_order: int
    description: str
    typical_capabilities: str
    advancement_requirements: str
    advancement_bottleneck: str
    population_ratio: str
    qualitative_shift: str

    @field_validator("population_ratio", mode="before")
    @classmethod
    def coerce_population_ratio(cls, v: Any) -> str:
        if isinstance(v, (int, float)):
            return f"~{v * 100:.2g}%" if v < 1 else str(v)
        return str(v)


class Discipline(BaseModel):
    name: str
    philosophy: str
    source_energy: str
    strengths: Any = ""
    weaknesses: Any = ""
    typical_practitioners: Any = ""
    synergies_with: Any = Field(default_factory=list)

    @field_validator("strengths", "weaknesses", "typical_practitioners", mode="before")
    @classmethod
    def coerce_str_fields(cls, v: Any) -> str:
        return _coerce_to_str(v)

    @field_validator("synergies_with", mode="before")
    @classmethod
    def coerce_synergies(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [_coerce_to_str(item) for item in v]
        return [str(v)]


class AdvancementMechanics(BaseModel):
    training_methods: Any = ""
    breakthrough_triggers: Any = ""
    failure_modes: Any = ""
    regression_conditions: Any = ""

    @field_validator(
        "training_methods",
        "breakthrough_triggers",
        "failure_modes",
        "regression_conditions",
        mode="before",
    )
    @classmethod
    def coerce_str_fields(cls, v: Any) -> str:
        return _coerce_to_str(v)


class PowerSystemResponse(BaseModel):
    """Stage 2: Power/magic system design."""

    system_name: str
    core_mechanic: str
    energy_source: str
    ranks: list[PowerRank] = Field(min_length=1)
    disciplines: list[Discipline] = Field(min_length=1)
    advancement_mechanics: AdvancementMechanics
    hard_limits: list[Any] = Field(min_length=1)
    soft_limits: list[Any] = Field(min_length=1)

    @model_validator(mode="after")
    def truncate_lists(self) -> PowerSystemResponse:
        self.ranks = self.ranks[:15]
        self.disciplines = self.disciplines[:10]
        return self
    power_ceiling: Any = ""

    @field_validator("hard_limits", "soft_limits", mode="before")
    @classmethod
    def coerce_limit_lists(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [_coerce_to_str(item) for item in v]
        return [str(v)]

    @field_validator("power_ceiling", mode="before")
    @classmethod
    def coerce_power_ceiling(cls, v: Any) -> str:
        return _coerce_to_str(v)


class RegionEntry(BaseModel):
    name: str
    description: str
    parent_region: str | None = None
    climate: str = ""
    notable_features: Any = ""
    political_entity: str | None = None
    stub: bool = False

    @field_validator("climate", mode="before")
    @classmethod
    def coerce_climate(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator("notable_features", mode="before")
    @classmethod
    def coerce_notable_features(cls, v: Any) -> str:
        return _coerce_to_str(v)


class FactionEntry(BaseModel):
    name: str
    description: str
    territory: Any = None
    goals: Any = ""
    resources: Any = ""
    relationships: Any = ""

    @field_validator("territory", "goals", "resources", "relationships", mode="before")
    @classmethod
    def coerce_str_fields(cls, v: Any) -> str | None:
        if v is None:
            return None
        return _coerce_to_str(v)


class PoliticalEntity(BaseModel):
    name: str
    government_type: str
    description: str
    factions: Any = Field(default_factory=list)

    @field_validator("factions", mode="before")
    @classmethod
    def coerce_factions(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [_coerce_to_str(item) for item in v]
        return [str(v)]


class GeographyResponse(BaseModel):
    """Stage 3: Geography, regions, factions, political entities."""

    regions: list[RegionEntry] = Field(min_length=1)
    factions: list[FactionEntry] = Field(default_factory=list)
    political_entities: list[PoliticalEntity] = Field(default_factory=list)


class HistoricalEra(BaseModel):
    era_name: str
    duration: str
    description: str
    defining_events: Any = Field(default_factory=list)

    @field_validator("defining_events", mode="before")
    @classmethod
    def coerce_events(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [_coerce_to_str(item) for item in v]
        return [str(v)]


class HistoricalEventEntry(BaseModel):
    name: str
    era: str
    description: str
    consequences: Any = ""
    key_figures: Any = Field(default_factory=list)

    @field_validator("consequences", mode="before")
    @classmethod
    def coerce_consequences(cls, v: Any) -> str:
        return _coerce_to_str(v)

    @field_validator("key_figures", mode="before")
    @classmethod
    def coerce_key_figures(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [_coerce_to_str(item) for item in v]
        return [str(v)]


class KeyFigure(BaseModel):
    name: str
    era: str
    role: str
    legacy: str


class HistoryResponse(BaseModel):
    """Stage 4: Historical eras, events, and key figures."""

    eras: list[HistoricalEra] = Field(min_length=1)
    events: list[HistoricalEventEntry] = Field(min_length=1)
    key_figures: list[KeyFigure] = Field(min_length=1)


class ActiveConflict(BaseModel):
    name: str
    parties: list[str]
    description: str
    stakes: str


class CurrentStateResponse(BaseModel):
    """Stage 5: Current political and power landscape."""

    active_conflicts: list[ActiveConflict] = Field(min_length=1)
    political_landscape: str
    power_balance: str


class Personality(BaseModel):
    core_traits: list[str]
    flaws: list[str]
    strengths: list[str]
    fears: list[str]
    desires: list[str]


class StartingPower(BaseModel):
    current_rank: str
    discipline: str | None = None
    latent_abilities: Any = None

    @field_validator("latent_abilities", mode="before")
    @classmethod
    def coerce_latent(cls, v: Any) -> str | None:
        if v is None:
            return None
        return _coerce_to_str(v)


class Motivation(BaseModel):
    surface_motivation: str
    deep_motivation: str


class ProtagonistResponse(BaseModel):
    """Stage 6: Protagonist design."""

    name: str
    age: int
    background: str
    personality: Personality
    starting_power: StartingPower
    disadvantage: Any = ""
    unusual_trait: Any = ""
    hidden_connection: Any = ""
    motivation: Motivation
    initial_circumstances: Any = ""
    arc_trajectory: Any = ""
    visual_appearance: Any = ""

    @field_validator(
        "disadvantage", "unusual_trait", "hidden_connection",
        "initial_circumstances", "arc_trajectory", "visual_appearance",
        mode="before",
    )
    @classmethod
    def coerce_str_fields(cls, v: Any) -> str:
        return _coerce_to_str(v)


class AntagonistEntry(BaseModel):
    name: str
    role: str
    power_level: Any = ""
    motivation: Any = ""
    relationship_to_protagonist: Any = ""
    threat_type: Any = ""
    visual_appearance: Any = ""

    @field_validator(
        "power_level", "motivation", "relationship_to_protagonist", "threat_type",
        "visual_appearance",
        mode="before",
    )
    @classmethod
    def coerce_str_fields(cls, v: Any) -> str:
        return _coerce_to_str(v)


class AntagonistsResponse(BaseModel):
    """Stage 7: Antagonist designs."""

    antagonists: list[AntagonistEntry] = Field(min_length=1)


class SupportingCharacterEntry(BaseModel):
    name: str
    role: str
    connection_to_protagonist: Any = ""
    narrative_purpose: Any = ""
    personality_sketch: Any = ""
    visual_appearance: Any = ""

    @field_validator(
        "connection_to_protagonist", "narrative_purpose", "personality_sketch",
        "visual_appearance",
        mode="before",
    )
    @classmethod
    def coerce_str_fields(cls, v: Any) -> str:
        return _coerce_to_str(v)


class SupportingCastResponse(BaseModel):
    """Stage 8: Supporting cast."""

    characters: list[SupportingCharacterEntry] = Field(min_length=1)


# ═══════════════════════════════════════════════════════════════════════════
# CONSOLIDATED POST-CHAPTER ANALYSIS PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class KeyEvent(BaseModel):
    description: str
    emotional_beat: str
    characters_involved: list[str]
    narrative_importance: str

    @field_validator("narrative_importance")
    @classmethod
    def validate_importance(cls, v: str) -> str:
        allowed = {"minor", "moderate", "major", "pivotal"}
        if v not in allowed:
            msg = f"narrative_importance must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class ForeshadowingSeed(BaseModel):
    description: str
    seed_type: str
    target_scope_tier: int | None = None
    subtlety: str

    @field_validator("seed_type")
    @classmethod
    def validate_seed_type(cls, v: str) -> str:
        allowed = {
            "rumor", "artifact", "character_mention",
            "event_echo", "power_anomaly", "mystery",
        }
        if v not in allowed:
            msg = f"seed_type must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v

    @field_validator("subtlety")
    @classmethod
    def validate_subtlety(cls, v: str) -> str:
        allowed = {"subtle", "moderate", "overt"}
        if v not in allowed:
            msg = f"subtlety must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class ForeshadowingReference(BaseModel):
    existing_seed_description: str
    reference_type: str
    payoff_description: str | None = None

    @field_validator("reference_type")
    @classmethod
    def validate_reference_type(cls, v: str) -> str:
        allowed = {"reinforced", "partially_paid_off", "fully_paid_off"}
        if v not in allowed:
            msg = f"reference_type must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class BibleEntryExtract(BaseModel):
    entry_type: str
    content: str
    entity_types: list[str]
    entity_names: list[str]
    is_public_knowledge: bool = True
    supersedes_description: str | None = None

    @field_validator("entry_type")
    @classmethod
    def validate_entry_type(cls, v: str) -> str:
        allowed = {
            "character_fact", "relationship", "world_rule",
            "historical_event", "power_interaction", "location_detail",
            "foreshadowing", "promise", "mystery", "theme",
        }
        if v in allowed:
            return v
        # Map common LLM variants to canonical types
        mapping = {
            "character": "character_fact",
            "location": "location_detail",
            "artifact": "world_rule",
            "faction": "world_rule",
            "organization": "world_rule",
            "power_system": "power_interaction",
            "concept": "world_rule",
            "lore": "historical_event",
            "event": "historical_event",
        }
        return mapping.get(v, "world_rule")


class NarrativeAnalysisResult(BaseModel):
    """Call 1 output: narrative events, tension, foreshadowing, bible entries."""

    key_events: list[KeyEvent]
    overall_emotional_arc: str
    tension_level: float = Field(ge=0.0, le=1.0)
    tension_phase: str
    new_foreshadowing_seeds: list[ForeshadowingSeed] = Field(default_factory=list)
    foreshadowing_references: list[ForeshadowingReference] = Field(default_factory=list)
    bible_entries_to_extract: list[BibleEntryExtract] = Field(default_factory=list)
    cliffhanger_description: str | None = None

    @field_validator("tension_phase")
    @classmethod
    def validate_tension_phase(cls, v: str) -> str:
        allowed = {"rest", "buildup", "confrontation", "climax", "resolution", "aftermath"}
        if v not in allowed:
            msg = f"tension_phase must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class PowerEvent(BaseModel):
    character_name: str
    event_type: str
    description: str
    struggle_context: str
    sacrifice_or_cost: str | None = None
    foundation: str
    narrative_buildup_chapters: Any = Field(default_factory=list)
    new_rank: str | None = None
    ability_name: str | None = None
    training_progress_delta: Any = 0.0

    @field_validator("narrative_buildup_chapters", mode="before")
    @classmethod
    def coerce_buildup_chapters(cls, v: Any) -> list[int]:
        if isinstance(v, list):
            return v
        if isinstance(v, int):
            return [v] if v > 0 else []
        return []

    @field_validator("training_progress_delta", mode="before")
    @classmethod
    def clamp_training_delta(cls, v: Any) -> float:
        try:
            val = float(v)
        except (TypeError, ValueError):
            return 0.0
        # LLM sometimes returns percentage (5) instead of fraction (0.05)
        if val > 0.1:
            val = val / 100.0
        return max(0.0, min(0.1, val))

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        allowed = {
            "rank_up", "new_ability", "ability_mastery",
            "insight", "power_loss", "training_progress",
        }
        if v not in allowed:
            msg = f"event_type must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class EarnedPowerEval(BaseModel):
    """Embedded 4-rule earned power evaluation."""

    character_name: str
    event_description: str
    struggle_score: float = Field(ge=0.0, le=0.25)
    struggle_reasoning: str
    foundation_score: float = Field(ge=0.0, le=0.25)
    foundation_reasoning: str
    cost_score: float = Field(ge=0.0, le=0.25)
    cost_reasoning: str
    buildup_score: float = Field(ge=0.0, le=0.25)
    buildup_reasoning: str
    total_score: float = Field(ge=0.0, le=1.0)
    approved: bool
    reasoning: str

    @model_validator(mode="after")
    def validate_total_and_approved(self) -> EarnedPowerEval:
        expected = round(
            self.struggle_score + self.foundation_score
            + self.cost_score + self.buildup_score, 4
        )
        if abs(self.total_score - expected) > 0.02:
            msg = (
                f"total_score ({self.total_score}) must equal sum of "
                f"sub-scores ({expected})"
            )
            raise ValueError(msg)
        if self.approved != (self.total_score >= 0.5):
            msg = (
                f"approved must be True when total_score >= 0.5, "
                f"got approved={self.approved} with total_score={self.total_score}"
            )
            raise ValueError(msg)
        return self


class AbilityUsage(BaseModel):
    character_name: str
    ability_name: str
    context: str
    proficiency_indication: str

    @field_validator("proficiency_indication")
    @classmethod
    def validate_proficiency(cls, v: str) -> str:
        allowed = {"improving", "stable", "struggling"}
        if v not in allowed:
            msg = f"proficiency_indication must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class ConsistencyIssue(BaseModel):
    description: str
    severity: str
    bible_entry_content: str
    suggested_fix: str

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"minor", "moderate", "critical"}
        if v not in allowed:
            msg = f"severity must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class ChekhovInteraction(BaseModel):
    gun_description: str
    interaction_type: str
    details: str
    resolution_description: str | None = None
    subversion_description: str | None = None

    @field_validator("interaction_type")
    @classmethod
    def validate_interaction_type(cls, v: str) -> str:
        allowed = {"new_gun", "touched", "advanced", "resolved", "subverted"}
        if v not in allowed:
            msg = f"interaction_type must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class SystemAnalysisResult(BaseModel):
    """Call 2 output: power events, earned power eval, consistency, Chekhov."""

    power_events: list[PowerEvent] = Field(default_factory=list)
    earned_power_evaluations: list[EarnedPowerEval] = Field(default_factory=list)
    ability_usages: list[AbilityUsage] = Field(default_factory=list)
    consistency_issues: list[ConsistencyIssue] = Field(default_factory=list)
    chekhov_interactions: list[ChekhovInteraction] = Field(default_factory=list)
    has_critical_violations: bool

    @model_validator(mode="after")
    def validate_critical_flag(self) -> SystemAnalysisResult:
        has_critical = any(
            issue.severity == "critical" for issue in self.consistency_issues
        )
        has_rejected = any(
            not ep.approved for ep in self.earned_power_evaluations
        )
        expected = has_critical or has_rejected
        if self.has_critical_violations != expected:
            msg = (
                f"has_critical_violations should be {expected} based on "
                f"consistency issues and earned power evaluations"
            )
            raise ValueError(msg)
        return self


# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class ChapterSummaryResult(BaseModel):
    """Standard chapter summary (~300 tokens)."""

    summary: str
    key_events: list[str]
    emotional_arc: str
    cliffhangers: list[str] = Field(default_factory=list)


class EmotionalStateEntry(BaseModel):
    character: str
    state: str
    unresolved_tension: str | None = None


class DialogueThread(BaseModel):
    last_exchange: Any = None
    conversation_topic: str | None = None
    what_was_left_unsaid: str | None = None
    promises_or_oaths: str | None = None

    @field_validator("last_exchange", mode="before")
    @classmethod
    def coerce_last_exchange(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, list):
            return "\n".join(str(x) for x in v)
        return str(v)


class CliffhangerDetail(BaseModel):
    description: str
    question_raised: str
    reader_expectation: str
    stakes: str


class PendingAction(BaseModel):
    character: str
    action: str
    constraint: str | None = None


class ArcBeat(BaseModel):
    what_was_accomplished: str
    what_remains: str
    arc_phase_note: str


class EnhancedRecapResult(BaseModel):
    """Enhanced recap (~1200 tokens) for next-chapter context."""

    final_scene_snapshot: str
    emotional_state: list[EmotionalStateEntry]
    active_dialogue_threads: DialogueThread
    cliffhanger: CliffhangerDetail | None = None
    immediate_pending_actions: list[PendingAction] = Field(default_factory=list)
    chapter_arc_beat: ArcBeat


class ArcSummaryResult(BaseModel):
    """Meta-summary of an entire arc."""

    arc_summary: str
    key_themes: list[str]
    character_growth: list[str]
    promises_fulfilled: list[str] = Field(default_factory=list)
    promises_outstanding: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# PLANNING PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class ArcKeyEvent(BaseModel):
    event_order: int
    description: str
    chapter_target: int | None = None
    characters_involved: list[str]


class CharacterArc(BaseModel):
    character_name: str
    arc_goal: str
    starting_state: str
    ending_state: str


class ThemeEntry(BaseModel):
    theme: str
    how_explored: str


class ArcPlanResult(BaseModel):
    """Arc plan proposal."""

    title: str
    description: str
    target_chapter_start: int
    target_chapter_end: int
    key_events: list[ArcKeyEvent] = Field(min_length=1)
    character_arcs: list[CharacterArc] = Field(min_length=1)
    themes: list[ThemeEntry] = Field(min_length=1)


class SceneBeat(BaseModel):
    description: str
    beats: list[str]
    emotional_trajectory: str


class ChapterPlanResult(BaseModel):
    """Scene-by-scene chapter outline."""

    title: str
    scenes: list[SceneBeat] = Field(min_length=1)
    target_tension: float = Field(ge=0.0, le=1.0)


class PlotThreadEntry(BaseModel):
    name: str
    description: str
    thread_type: str
    related_characters: list[str]

    @field_validator("thread_type")
    @classmethod
    def validate_thread_type(cls, v: str) -> str:
        allowed = {"main", "subplot", "character_arc", "mystery", "relationship"}
        if v not in allowed:
            msg = f"thread_type must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class PlotThreadResult(BaseModel):
    """Extracted plot threads from chapter analysis."""

    threads: list[PlotThreadEntry]


# ═══════════════════════════════════════════════════════════════════════════
# IMAGE PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class ImagePromptResult(BaseModel):
    """Image generation prompt output."""

    positive_prompt: str
    negative_prompt: str
    style_tags: list[str]
    aspect_ratio: str

    @field_validator("aspect_ratio")
    @classmethod
    def validate_aspect_ratio(cls, v: str) -> str:
        allowed = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
        if v not in allowed:
            msg = f"aspect_ratio must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


# ═══════════════════════════════════════════════════════════════════════════
# READER INFLUENCE PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class OracleFilterResult(BaseModel):
    """Validates whether a reader's oracle question is appropriate."""

    is_valid: bool
    reason: str
    suggested_revelation_timing: str | None = None


class ButterflyChoiceResult(BaseModel):
    """A thematic binary choice for readers."""

    choice_text_a: str
    choice_text_b: str
    thematic_tension: str
    narrative_consequences_a: str
    narrative_consequences_b: str
