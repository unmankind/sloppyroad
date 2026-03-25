"""Tests for LLM response parsers.

Each parser is tested with valid data (should parse) and invalid data
(should reject with clear errors).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aiwebnovel.llm.parsers import (
    AntagonistsResponse,
    ArcPlanResult,
    ArcSummaryResult,
    ButterflyChoiceResult,
    ChapterPlanResult,
    ChapterSummaryResult,
    ConsistencyIssue,
    CosmologyResponse,
    CurrentStateResponse,
    EarnedPowerEval,
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

# ═══════════════════════════════════════════════════════════════════════════
# WORLD PIPELINE PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class TestCosmologyResponse:
    def test_valid(self) -> None:
        data = {
            "fundamental_forces": [
                {
                    "name": "Aether",
                    "description": "Primal energy",
                    "mortal_interaction": "Meditation",
                    "extreme_concentration_effect": "Reality warps",
                },
                {
                    "name": "Void",
                    "description": "Absence of energy",
                    "mortal_interaction": "Stillness",
                    "extreme_concentration_effect": "Annihilation",
                },
            ],
            "planes_of_existence": [
                {
                    "name": f"Plane {i}",
                    "description": "A plane",
                    "accessibility_requirements": "Rank 1",
                    "native_inhabitants": "Spirits",
                }
                for i in range(3)
            ],
            "cosmic_laws": [
                {"description": f"Law {i}"} for i in range(3)
            ],
            "energy_types": [
                {
                    "name": f"Energy {i}",
                    "source": "Cosmos",
                    "properties": "Malleable",
                    "fundamental_force": "Aether",
                    "interactions": "Synergy",
                }
                for i in range(2)
            ],
            "reality_tiers": [
                {
                    "tier_name": f"Tier {i}",
                    "description": "A tier",
                    "power_ceiling_description": "Peak",
                    "beings": "Mortals",
                    "qualitative_change": "Different",
                }
                for i in range(5)
            ],
        }
        result = CosmologyResponse.model_validate(data)
        assert len(result.fundamental_forces) == 2
        assert len(result.reality_tiers) == 5

    def test_too_few_forces(self) -> None:
        data = {
            "fundamental_forces": [],
            "planes_of_existence": [
                {
                    "name": f"P{i}",
                    "description": "d",
                    "accessibility_requirements": "r",
                    "native_inhabitants": "n",
                }
                for i in range(3)
            ],
            "cosmic_laws": [
                {"description": f"L{i}"} for i in range(3)
            ],
            "energy_types": [
                {
                    "name": f"E{i}",
                    "source": "s",
                    "properties": "p",
                    "fundamental_force": "f",
                    "interactions": "i",
                }
                for i in range(2)
            ],
            "reality_tiers": [
                {
                    "tier_name": f"T{i}",
                    "description": "d",
                    "power_ceiling_description": "p",
                    "beings": "b",
                    "qualitative_change": "q",
                }
                for i in range(5)
            ],
        }
        with pytest.raises(ValidationError, match="too_short"):
            CosmologyResponse.model_validate(data)


class TestPowerSystemResponse:
    def test_valid_minimal(self) -> None:
        data = {
            "system_name": "Qi Cultivation",
            "core_mechanic": "Absorb and refine ambient qi.",
            "energy_source": "Ambient qi from the world",
            "ranks": [
                {
                    "rank_name": f"Rank {i}",
                    "rank_order": i,
                    "description": "A rank",
                    "typical_capabilities": "Can fight",
                    "advancement_requirements": "Train hard",
                    "advancement_bottleneck": "Resources",
                    "population_ratio": "1 in 1000",
                    "qualitative_shift": "See qi",
                }
                for i in range(7)
            ],
            "disciplines": [
                {
                    "name": f"Path {i}",
                    "philosophy": "Power through sacrifice",
                    "source_energy": "Qi",
                    "strengths": "Strong attacks",
                    "weaknesses": "Low defence",
                    "typical_practitioners": "Warriors",
                    "synergies_with": [],
                }
                for i in range(3)
            ],
            "advancement_mechanics": {
                "training_methods": "Meditation",
                "breakthrough_triggers": "Near-death",
                "failure_modes": "Qi deviation",
                "regression_conditions": "Soul damage",
            },
            "hard_limits": ["Cannot resurrect the dead"],
            "soft_limits": ["Time reversal is theoretically possible but fatal"],
            "power_ceiling": "Ascension to higher plane",
        }
        result = PowerSystemResponse.model_validate(data)
        assert result.system_name == "Qi Cultivation"
        assert len(result.ranks) == 7

    def test_too_few_ranks(self) -> None:
        data = {
            "system_name": "X",
            "core_mechanic": "X",
            "energy_source": "X",
            "ranks": [],
            "disciplines": [
                {
                    "name": "D", "philosophy": "p",
                    "source_energy": "s",
                    "strengths": "s", "weaknesses": "w",
                    "typical_practitioners": "t",
                    "synergies_with": [],
                }
                for _ in range(3)
            ],
            "advancement_mechanics": {
                "training_methods": "t",
                "breakthrough_triggers": "b",
                "failure_modes": "f",
                "regression_conditions": "r",
            },
            "hard_limits": ["x"],
            "soft_limits": ["x"],
            "power_ceiling": "x",
        }
        with pytest.raises(ValidationError, match="too_short"):
            PowerSystemResponse.model_validate(data)


class TestGeographyResponse:
    def test_valid(self) -> None:
        data = {
            "regions": [
                {
                    "name": f"Region {i}",
                    "description": "d",
                    "climate": "c",
                    "notable_features": "f",
                }
                for i in range(3)
            ],
            "factions": [
                {
                    "name": f"Faction {i}",
                    "description": "d",
                    "goals": "g",
                    "resources": "r",
                    "relationships": "rel",
                }
                for i in range(2)
            ],
            "political_entities": [
                {
                    "name": "Empire",
                    "government_type": "monarchy",
                    "description": "d",
                    "factions": ["Faction 0"],
                }
            ],
        }
        result = GeographyResponse.model_validate(data)
        assert len(result.regions) == 3


class TestHistoryResponse:
    def test_valid(self) -> None:
        data = {
            "eras": [
                {
                    "era_name": f"Era {i}",
                    "duration": "1000 years",
                    "description": "d",
                    "defining_events": ["war"],
                }
                for i in range(3)
            ],
            "events": [
                {
                    "name": f"Event {i}",
                    "era": "Era 0",
                    "description": "d",
                    "consequences": "c",
                    "key_figures": ["Figure 0"],
                }
                for i in range(3)
            ],
            "key_figures": [
                {"name": f"Figure {i}", "era": "Era 0", "role": "ruler", "legacy": "great"}
                for i in range(2)
            ],
        }
        result = HistoryResponse.model_validate(data)
        assert len(result.eras) == 3


class TestCurrentStateResponse:
    def test_valid(self) -> None:
        data = {
            "active_conflicts": [
                {"name": "Border War", "parties": ["A", "B"], "description": "d", "stakes": "s"}
            ],
            "political_landscape": "Fragile peace",
            "power_balance": "Uneven",
        }
        result = CurrentStateResponse.model_validate(data)
        assert result.active_conflicts[0].name == "Border War"


class TestProtagonistResponse:
    def test_valid(self) -> None:
        data = {
            "name": "Kael Ashborne",
            "age": 17,
            "background": "Orphaned at six...",
            "personality": {
                "core_traits": ["determined"],
                "flaws": ["reckless"],
                "strengths": ["adaptable"],
                "fears": ["abandonment"],
                "desires": ["belonging"],
            },
            "starting_power": {"current_rank": "Unranked", "discipline": None},
            "disadvantage": "Damaged meridians",
            "unusual_trait": "Can see qi currents",
            "hidden_connection": "Descended from the First Sage",
            "motivation": {
                "surface_motivation": "Get strong enough to survive",
                "deep_motivation": "Find where he belongs",
            },
            "initial_circumstances": "Working as a servant in an academy",
            "arc_trajectory": "From nobody to world-shaker",
        }
        result = ProtagonistResponse.model_validate(data)
        assert result.name == "Kael Ashborne"
        assert result.age == 17


class TestAntagonistsResponse:
    def test_valid(self) -> None:
        data = {
            "antagonists": [
                {
                    "name": "Lord Vex", "role": "primary",
                    "power_level": "Rank 8",
                    "motivation": "Control",
                    "relationship_to_protagonist": "Nemesis",
                    "threat_type": "physical",
                },
                {
                    "name": "Shade", "role": "rival",
                    "power_level": "Rank 5",
                    "motivation": "Jealousy",
                    "relationship_to_protagonist": "Foil",
                    "threat_type": "political",
                },
            ]
        }
        result = AntagonistsResponse.model_validate(data)
        assert len(result.antagonists) == 2

    def test_too_few(self) -> None:
        data = {"antagonists": []}
        with pytest.raises(ValidationError, match="too_short"):
            AntagonistsResponse.model_validate(data)


class TestSupportingCastResponse:
    def test_valid(self) -> None:
        data = {
            "characters": [
                {
                    "name": f"Char {i}",
                    "role": "mentor" if i == 0 else "friend",
                    "connection_to_protagonist": "c",
                    "narrative_purpose": "n",
                    "personality_sketch": "p",
                }
                for i in range(3)
            ]
        }
        result = SupportingCastResponse.model_validate(data)
        assert len(result.characters) == 3


# ═══════════════════════════════════════════════════════════════════════════
# NARRATIVE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════


class TestNarrativeAnalysisResult:
    def _make_valid(self) -> dict:
        return {
            "key_events": [
                {
                    "description": "Kael discovers a hidden chamber beneath the academy",
                    "emotional_beat": "curiosity -> awe -> dread",
                    "characters_involved": ["Kael", "Master Ren"],
                    "narrative_importance": "major",
                }
            ],
            "overall_emotional_arc": "tension -> revelation -> unease",
            "tension_level": 0.7,
            "tension_phase": "buildup",
            "new_foreshadowing_seeds": [
                {
                    "description": "Ancient runes glow faintly on the chamber walls",
                    "seed_type": "artifact",
                    "target_scope_tier": 2,
                    "subtlety": "moderate",
                }
            ],
            "foreshadowing_references": [
                {
                    "existing_seed_description": "Strange dreams of a dark tower",
                    "reference_type": "reinforced",
                    "payoff_description": None,
                }
            ],
            "bible_entries_to_extract": [
                {
                    "entry_type": "location_detail",
                    "content": "A hidden chamber exists beneath the academy.",
                    "entity_types": ["location"],
                    "entity_names": ["Academy Chamber"],
                    "is_public_knowledge": False,
                }
            ],
            "cliffhanger_description": "The runes begin to pulse as Kael reaches for the door.",
        }

    def test_valid(self) -> None:
        data = self._make_valid()
        result = NarrativeAnalysisResult.model_validate(data)
        assert result.tension_level == 0.7
        assert result.tension_phase == "buildup"
        assert len(result.key_events) == 1

    def test_invalid_tension_phase(self) -> None:
        data = self._make_valid()
        data["tension_phase"] = "exploding"
        with pytest.raises(ValidationError, match="tension_phase"):
            NarrativeAnalysisResult.model_validate(data)

    def test_tension_out_of_range(self) -> None:
        data = self._make_valid()
        data["tension_level"] = 1.5
        with pytest.raises(ValidationError):
            NarrativeAnalysisResult.model_validate(data)

    def test_invalid_seed_type(self) -> None:
        data = self._make_valid()
        data["new_foreshadowing_seeds"][0]["seed_type"] = "banana"
        with pytest.raises(ValidationError, match="seed_type"):
            NarrativeAnalysisResult.model_validate(data)

    def test_invalid_reference_type(self) -> None:
        data = self._make_valid()
        data["foreshadowing_references"][0]["reference_type"] = "destroyed"
        with pytest.raises(ValidationError, match="reference_type"):
            NarrativeAnalysisResult.model_validate(data)

    def test_unknown_entry_type_maps_to_world_rule(self) -> None:
        data = self._make_valid()
        data["bible_entries_to_extract"][0]["entry_type"] = "random_stuff"
        result = NarrativeAnalysisResult.model_validate(data)
        assert result.bible_entries_to_extract[0].entry_type == "world_rule"

    def test_entry_type_mapping(self) -> None:
        data = self._make_valid()
        data["bible_entries_to_extract"][0]["entry_type"] = "character"
        result = NarrativeAnalysisResult.model_validate(data)
        assert result.bible_entries_to_extract[0].entry_type == "character_fact"

    def test_invalid_event_importance(self) -> None:
        data = self._make_valid()
        data["key_events"][0]["narrative_importance"] = "legendary"
        with pytest.raises(ValidationError, match="narrative_importance"):
            NarrativeAnalysisResult.model_validate(data)


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════


class TestSystemAnalysisResult:
    def _make_valid(self, approved: bool = True) -> dict:
        return {
            "power_events": [
                {
                    "character_name": "Kael",
                    "event_type": "rank_up",
                    "description": "Advanced to Rank 3",
                    "struggle_context": "Nearly died fighting the shadow beast",
                    "sacrifice_or_cost": "Lost use of right arm for a week",
                    "foundation": "Built on 3 chapters of qi refinement training",
                    "narrative_buildup_chapters": [10, 11, 12],
                    "new_rank": "Rank 3",
                    "ability_name": None,
                    "training_progress_delta": 0.0,
                }
            ],
            "earned_power_evaluations": [
                {
                    "character_name": "Kael",
                    "event_description": "Rank up to Rank 3",
                    "struggle_score": 0.20 if approved else 0.10,
                    "struggle_reasoning": "Near-death battle with shadow beast",
                    "foundation_score": 0.25 if approved else 0.10,
                    "foundation_reasoning": "Direct progression from Rank 2 training",
                    "cost_score": 0.15 if approved else 0.10,
                    "cost_reasoning": "Physical injury is meaningful but temporary",
                    "buildup_score": 0.20 if approved else 0.10,
                    "buildup_reasoning": (
                        "3 chapters of buildup is solid"
                        if approved else "Minimal"
                    ),
                    "total_score": 0.80 if approved else 0.40,
                    "approved": approved,
                    "reasoning": (
                        "Well-earned advancement"
                        if approved
                        else "Insufficient narrative support"
                    ),
                }
            ],
            "ability_usages": [
                {
                    "character_name": "Kael",
                    "ability_name": "Qi Shield",
                    "context": "Used to block shadow beast's attack",
                    "proficiency_indication": "improving",
                }
            ],
            "consistency_issues": [],
            "chekhov_interactions": [
                {
                    "gun_description": "The mysterious crystal in Kael's pack",
                    "interaction_type": "touched",
                    "details": "Crystal glowed during the fight",
                }
            ],
            "has_critical_violations": not approved,
        }

    def test_valid_approved(self) -> None:
        data = self._make_valid(approved=True)
        result = SystemAnalysisResult.model_validate(data)
        assert not result.has_critical_violations
        assert result.earned_power_evaluations[0].approved

    def test_valid_rejected(self) -> None:
        data = self._make_valid(approved=False)
        result = SystemAnalysisResult.model_validate(data)
        assert result.has_critical_violations
        assert not result.earned_power_evaluations[0].approved

    def test_critical_flag_mismatch(self) -> None:
        data = self._make_valid(approved=True)
        data["has_critical_violations"] = True  # Should be False
        with pytest.raises(ValidationError, match="has_critical_violations"):
            SystemAnalysisResult.model_validate(data)

    def test_invalid_event_type(self) -> None:
        data = self._make_valid()
        data["power_events"][0]["event_type"] = "magic_poof"
        with pytest.raises(ValidationError, match="event_type"):
            SystemAnalysisResult.model_validate(data)

    def test_invalid_proficiency(self) -> None:
        data = self._make_valid()
        data["ability_usages"][0]["proficiency_indication"] = "amazing"
        with pytest.raises(ValidationError, match="proficiency_indication"):
            SystemAnalysisResult.model_validate(data)

    def test_consistency_with_critical(self) -> None:
        data = self._make_valid(approved=True)
        data["consistency_issues"] = [
            {
                "description": "Kael used fire qi but is a water cultivator",
                "severity": "critical",
                "bible_entry_content": "Kael is a water-path cultivator",
                "suggested_fix": "Change to water qi technique",
            }
        ]
        data["has_critical_violations"] = True
        result = SystemAnalysisResult.model_validate(data)
        assert result.has_critical_violations


class TestEarnedPowerEval:
    def test_valid_approved(self) -> None:
        data = {
            "character_name": "Kael",
            "event_description": "Rank up",
            "struggle_score": 0.20,
            "struggle_reasoning": "Hard fight",
            "foundation_score": 0.20,
            "foundation_reasoning": "Solid foundation",
            "cost_score": 0.15,
            "cost_reasoning": "Meaningful cost",
            "buildup_score": 0.20,
            "buildup_reasoning": "Good buildup",
            "total_score": 0.75,
            "approved": True,
            "reasoning": "Earned",
        }
        result = EarnedPowerEval.model_validate(data)
        assert result.approved
        assert result.total_score == 0.75

    def test_total_must_equal_sum(self) -> None:
        data = {
            "character_name": "Kael",
            "event_description": "Rank up",
            "struggle_score": 0.10,
            "struggle_reasoning": "r",
            "foundation_score": 0.10,
            "foundation_reasoning": "r",
            "cost_score": 0.10,
            "cost_reasoning": "r",
            "buildup_score": 0.10,
            "buildup_reasoning": "r",
            "total_score": 0.99,  # Should be 0.40
            "approved": True,
            "reasoning": "r",
        }
        with pytest.raises(ValidationError, match="total_score"):
            EarnedPowerEval.model_validate(data)

    def test_approved_must_match_threshold(self) -> None:
        data = {
            "character_name": "Kael",
            "event_description": "Rank up",
            "struggle_score": 0.05,
            "struggle_reasoning": "r",
            "foundation_score": 0.05,
            "foundation_reasoning": "r",
            "cost_score": 0.05,
            "cost_reasoning": "r",
            "buildup_score": 0.05,
            "buildup_reasoning": "r",
            "total_score": 0.20,
            "approved": True,  # Should be False (0.20 < 0.5)
            "reasoning": "r",
        }
        with pytest.raises(ValidationError, match="approved"):
            EarnedPowerEval.model_validate(data)

    def test_score_out_of_range(self) -> None:
        data = {
            "character_name": "Kael",
            "event_description": "Rank up",
            "struggle_score": 0.50,  # Max is 0.25
            "struggle_reasoning": "r",
            "foundation_score": 0.10,
            "foundation_reasoning": "r",
            "cost_score": 0.10,
            "cost_reasoning": "r",
            "buildup_score": 0.10,
            "buildup_reasoning": "r",
            "total_score": 0.80,
            "approved": True,
            "reasoning": "r",
        }
        with pytest.raises(ValidationError):
            EarnedPowerEval.model_validate(data)


class TestConsistencyIssue:
    def test_valid_severities(self) -> None:
        for sev in ("minor", "moderate", "critical"):
            issue = ConsistencyIssue(
                description="Some issue",
                severity=sev,
                bible_entry_content="Fact",
                suggested_fix="Fix it",
            )
            assert issue.severity == sev

    def test_invalid_severity(self) -> None:
        with pytest.raises(ValidationError, match="severity"):
            ConsistencyIssue(
                description="Some issue",
                severity="catastrophic",
                bible_entry_content="Fact",
                suggested_fix="Fix it",
            )


# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class TestChapterSummaryResult:
    def test_valid(self) -> None:
        data = {
            "summary": "Kael entered the ancient library...",
            "key_events": ["Found the hidden scroll", "Fought a guardian"],
            "emotional_arc": "Curiosity to determination",
        }
        result = ChapterSummaryResult.model_validate(data)
        assert len(result.key_events) == 2
        assert result.cliffhangers == []


class TestEnhancedRecapResult:
    def test_valid(self) -> None:
        data = {
            "final_scene_snapshot": "Kael stands at the cliff edge...",
            "emotional_state": [
                {
                    "character": "Kael",
                    "state": "Exhausted but determined",
                    "unresolved_tension": "Guilt over leaving Mira behind",
                },
            ],
            "active_dialogue_threads": {
                "last_exchange": '"I will return," Kael said. "You better," Mira replied.',
                "conversation_topic": "Kael's departure",
                "what_was_left_unsaid": "Kael wanted to confess his fear",
                "promises_or_oaths": "Kael promised to return within a month",
            },
            "cliffhanger": {
                "description": "A dark figure appeared on the horizon",
                "question_raised": "Who or what is approaching?",
                "reader_expectation": "Confrontation or flight",
                "stakes": "Kael is exhausted and alone",
            },
            "immediate_pending_actions": [
                {
                    "character": "Kael",
                    "action": "Face the approaching figure",
                    "constraint": "Too exhausted to run",
                },
            ],
            "chapter_arc_beat": {
                "what_was_accomplished": "Kael escaped the academy",
                "what_remains": "Reaching the mountain shrine",
                "arc_phase_note": "Mid-arc, rising action",
            },
        }
        result = EnhancedRecapResult.model_validate(data)
        assert result.cliffhanger is not None
        assert len(result.emotional_state) == 1

    def test_valid_no_cliffhanger(self) -> None:
        data = {
            "final_scene_snapshot": "Kael rests by the fire...",
            "emotional_state": [{"character": "Kael", "state": "At peace"}],
            "active_dialogue_threads": {},
            "cliffhanger": None,
            "immediate_pending_actions": [],
            "chapter_arc_beat": {
                "what_was_accomplished": "Rest",
                "what_remains": "Journey continues",
                "arc_phase_note": "Rest beat",
            },
        }
        result = EnhancedRecapResult.model_validate(data)
        assert result.cliffhanger is None


class TestArcSummaryResult:
    def test_valid(self) -> None:
        data = {
            "arc_summary": "The Academy arc saw Kael grow...",
            "key_themes": ["belonging", "sacrifice"],
            "character_growth": ["Kael advanced to Rank 2"],
            "promises_fulfilled": ["Kael proved himself to Master Ren"],
            "promises_outstanding": ["The mysterious crystal remains unexplained"],
        }
        result = ArcSummaryResult.model_validate(data)
        assert len(result.key_themes) == 2


# ═══════════════════════════════════════════════════════════════════════════
# PLANNING PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class TestArcPlanResult:
    def test_valid(self) -> None:
        data = {
            "title": "The Crimson Trial",
            "description": "Kael faces the academy's trials...",
            "target_chapter_start": 5,
            "target_chapter_end": 12,
            "key_events": [
                {
                    "event_order": 1,
                    "description": "Trial begins",
                    "chapter_target": 5,
                    "characters_involved": ["Kael"],
                },
            ],
            "character_arcs": [
                {
                    "character_name": "Kael",
                    "arc_goal": "Prove worth",
                    "starting_state": "Outsider",
                    "ending_state": "Acknowledged",
                },
            ],
            "themes": [
                {"theme": "Merit vs privilege", "how_explored": "Through trial competition"},
            ],
        }
        result = ArcPlanResult.model_validate(data)
        assert result.title == "The Crimson Trial"


class TestChapterPlanResult:
    def test_valid(self) -> None:
        data = {
            "title": "The First Test",
            "scenes": [
                {
                    "description": "Morning preparation",
                    "beats": ["Kael wakes early", "Practices qi exercises"],
                    "emotional_trajectory": "Anxiety to focus",
                },
                {
                    "description": "The test begins",
                    "beats": ["Enter the arena"],
                    "emotional_trajectory": "Focus to determination",
                },
                {
                    "description": "Aftermath",
                    "beats": ["Results announced"],
                    "emotional_trajectory": "Determination to surprise",
                },
            ],
            "target_tension": 0.6,
        }
        result = ChapterPlanResult.model_validate(data)
        assert len(result.scenes) == 3

    def test_invalid_tension(self) -> None:
        data = {
            "title": "X",
            "scenes": [{"description": "d", "beats": ["b"], "emotional_trajectory": "e"}],
            "target_tension": 1.5,
        }
        with pytest.raises(ValidationError):
            ChapterPlanResult.model_validate(data)


class TestPlotThreadResult:
    def test_valid(self) -> None:
        data = {
            "threads": [
                {
                    "name": "The Crystal Mystery",
                    "description": "Unknown crystal glows",
                    "thread_type": "mystery",
                    "related_characters": ["Kael"],
                },
            ]
        }
        result = PlotThreadResult.model_validate(data)
        assert result.threads[0].thread_type == "mystery"

    def test_invalid_thread_type(self) -> None:
        data = {
            "threads": [
                {
                    "name": "X",
                    "description": "d",
                    "thread_type": "adventure",
                    "related_characters": [],
                },
            ]
        }
        with pytest.raises(ValidationError, match="thread_type"):
            PlotThreadResult.model_validate(data)


# ═══════════════════════════════════════════════════════════════════════════
# IMAGE PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class TestImagePromptResult:
    def test_valid(self) -> None:
        data = {
            "positive_prompt": "A young warrior with silver hair...",
            "negative_prompt": "text, watermark, signature",
            "style_tags": ["fantasy", "portrait", "dramatic lighting"],
            "aspect_ratio": "3:4",
        }
        result = ImagePromptResult.model_validate(data)
        assert result.aspect_ratio == "3:4"

    def test_invalid_aspect_ratio(self) -> None:
        data = {
            "positive_prompt": "p",
            "negative_prompt": "n",
            "style_tags": [],
            "aspect_ratio": "5:7",
        }
        with pytest.raises(ValidationError, match="aspect_ratio"):
            ImagePromptResult.model_validate(data)


# ═══════════════════════════════════════════════════════════════════════════
# READER INFLUENCE PARSERS
# ═══════════════════════════════════════════════════════════════════════════


class TestOracleFilterResult:
    def test_valid_positive(self) -> None:
        data = {
            "is_valid": True,
            "reason": "Asks about world lore",
            "suggested_revelation_timing": "Within next 5 chapters",
        }
        result = OracleFilterResult.model_validate(data)
        assert result.is_valid

    def test_valid_negative(self) -> None:
        data = {
            "is_valid": False,
            "reason": "Tries to control the plot",
            "suggested_revelation_timing": None,
        }
        result = OracleFilterResult.model_validate(data)
        assert not result.is_valid


class TestButterflyChoiceResult:
    def test_valid(self) -> None:
        data = {
            "choice_text_a": "Kael helps the stranger at the crossroads.",
            "choice_text_b": "Kael ignores the stranger and presses onward.",
            "thematic_tension": "Compassion vs pragmatism",
            "narrative_consequences_a": "Gains an unexpected ally but loses time",
            "narrative_consequences_b": "Arrives early but misses a crucial connection",
        }
        result = ButterflyChoiceResult.model_validate(data)
        assert result.thematic_tension == "Compassion vs pragmatism"
