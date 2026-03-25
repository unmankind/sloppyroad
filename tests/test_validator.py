"""Tests for chapter validation."""

from __future__ import annotations

import pytest

from aiwebnovel.llm.parsers import (
    ConsistencyIssue,
    EarnedPowerEval,
    SystemAnalysisResult,
)
from aiwebnovel.story.analyzer import AnalysisResult
from aiwebnovel.story.validator import ChapterValidator, ValidationResult


def _make_analysis(
    earned_power_evals: list[EarnedPowerEval] | None = None,
    consistency_issues: list[ConsistencyIssue] | None = None,
    has_critical: bool = False,
) -> AnalysisResult:
    """Helper to create AnalysisResult with system data."""
    system = SystemAnalysisResult(
        power_events=[],
        earned_power_evaluations=earned_power_evals or [],
        ability_usages=[],
        consistency_issues=consistency_issues or [],
        chekhov_interactions=[],
        has_critical_violations=has_critical,
    )
    return AnalysisResult(
        system=system,
        system_success=True,
        narrative_success=True,
    )


def _make_good_eval() -> EarnedPowerEval:
    """An approved earned power evaluation."""
    return EarnedPowerEval(
        character_name="Hero",
        event_description="Rank up after training arc",
        struggle_score=0.20,
        struggle_reasoning="Fought hard",
        foundation_score=0.20,
        foundation_reasoning="Trained for chapters",
        cost_score=0.15,
        cost_reasoning="Lost energy",
        buildup_score=0.15,
        buildup_reasoning="Built over 3 chapters",
        total_score=0.70,
        approved=True,
        reasoning="Well earned",
    )


def _make_bad_eval() -> EarnedPowerEval:
    """A rejected earned power evaluation (score < 0.5)."""
    return EarnedPowerEval(
        character_name="Hero",
        event_description="Sudden power gain",
        struggle_score=0.05,
        struggle_reasoning="No struggle shown",
        foundation_score=0.10,
        foundation_reasoning="Minimal foundation",
        cost_score=0.05,
        cost_reasoning="No cost",
        buildup_score=0.10,
        buildup_reasoning="Rushed",
        total_score=0.30,
        approved=False,
        reasoning="Unearned advancement",
    )


class TestValidationPasses:
    """Test validation passes with good data."""

    @pytest.mark.asyncio
    async def test_passes_with_good_scores(self):
        analysis = _make_analysis(earned_power_evals=[_make_good_eval()])
        validator = ChapterValidator()
        result = await validator.validate(analysis)

        assert result.passed
        assert len(result.issues) == 0

    @pytest.mark.asyncio
    async def test_passes_with_no_power_events(self):
        analysis = _make_analysis()
        validator = ChapterValidator()
        result = await validator.validate(analysis)

        assert result.passed

    @pytest.mark.asyncio
    async def test_passes_with_minor_consistency(self):
        ci = ConsistencyIssue(
            description="Minor name inconsistency",
            severity="minor",
            bible_entry_content="Name is X",
            suggested_fix="Use X",
        )
        analysis = _make_analysis(consistency_issues=[ci])
        validator = ChapterValidator()
        result = await validator.validate(analysis)

        assert result.passed  # minor issues don't trigger rejection


class TestValidationFails:
    """Test validation fails on bad data."""

    @pytest.mark.asyncio
    async def test_fails_on_low_earned_power(self):
        analysis = _make_analysis(
            earned_power_evals=[_make_bad_eval()],
            has_critical=True,
        )
        validator = ChapterValidator()
        result = await validator.validate(analysis)

        assert not result.passed
        assert any(i.issue_type == "earned_power" for i in result.issues)

    @pytest.mark.asyncio
    async def test_fails_on_critical_consistency(self):
        ci = ConsistencyIssue(
            description="Character used ability they don't have",
            severity="critical",
            bible_entry_content="Character has no fire magic",
            suggested_fix="Remove fire magic usage",
        )
        analysis = _make_analysis(
            consistency_issues=[ci],
            has_critical=True,
        )
        validator = ChapterValidator()
        result = await validator.validate(analysis)

        assert not result.passed
        assert any(i.issue_type == "consistency" for i in result.issues)


class TestRetryGuidance:
    """Test retry guidance generation."""

    @pytest.mark.asyncio
    async def test_guidance_includes_specific_issues(self):
        analysis = _make_analysis(
            earned_power_evals=[_make_bad_eval()],
            has_critical=True,
        )
        validator = ChapterValidator()
        result = await validator.validate(analysis)

        assert "CRITICAL" in result.retry_guidance
        assert "Sudden power gain" in result.retry_guidance
        assert "POWER ADVANCEMENT GUIDANCE" in result.retry_guidance

    @pytest.mark.asyncio
    async def test_guidance_includes_consistency_advice(self):
        ci = ConsistencyIssue(
            description="Broke power system rules",
            severity="critical",
            bible_entry_content="Hard limit violated",
            suggested_fix="Remove the violation",
        )
        analysis = _make_analysis(
            consistency_issues=[ci],
            has_critical=True,
        )
        validator = ChapterValidator()
        result = await validator.validate(analysis)

        assert "CONSISTENCY GUIDANCE" in result.retry_guidance

    def test_build_retry_guidance_format(self):
        validator = ChapterValidator()
        vr = ValidationResult(
            passed=False,
        )
        from aiwebnovel.story.validator import ValidationIssue
        vr.issues.append(ValidationIssue(
            issue_type="earned_power",
            description="Bad power up",
            severity="critical",
            details="Score was 0.2",
        ))
        vr.issues.append(ValidationIssue(
            issue_type="consistency",
            description="Wrong location",
            severity="critical",
            details="Was in X, now in Y",
        ))

        guidance = validator.build_retry_guidance(vr)

        assert "1." in guidance
        assert "2." in guidance
        assert "POWER ADVANCEMENT GUIDANCE" in guidance
        assert "CONSISTENCY GUIDANCE" in guidance


class TestNoSystemAnalysis:
    """Test behavior when system analysis is missing."""

    @pytest.mark.asyncio
    async def test_passes_when_no_system_analysis(self):
        """If system analysis failed, validation passes with warning."""
        analysis = AnalysisResult(
            narrative_success=True,
            system_success=False,
        )
        validator = ChapterValidator()
        result = await validator.validate(analysis)

        assert result.passed
