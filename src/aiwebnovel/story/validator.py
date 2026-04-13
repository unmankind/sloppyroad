"""Chapter validation — earned power and consistency checks.

Checks analysis results for rejection criteria and builds retry guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from aiwebnovel.story.analyzer import AnalysisResult

logger = structlog.get_logger(__name__)


@dataclass
class ValidationIssue:
    """A single validation issue."""

    issue_type: str  # "earned_power" or "consistency"
    description: str
    severity: str  # "critical", "moderate", "minor"
    details: str = ""


@dataclass
class ValidationResult:
    """Result of chapter validation."""

    passed: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)
    retry_guidance: str = ""

    @property
    def has_critical(self) -> bool:
        return any(i.severity == "critical" for i in self.issues)


class ChapterValidator:
    """Validates chapter analysis results for rejection criteria."""

    async def validate(
        self,
        analysis: AnalysisResult,
        genre: str = "progression_fantasy",
    ) -> ValidationResult:
        """Check analysis results for rejection criteria.

        Rejection criteria:
        - Any earned_power_evaluation with approved=False (score < 0.5)
          — only for genres with validation_strategy="earned_power"
        - Any consistency_issue with severity='critical' (all genres)
        """
        from aiwebnovel.story.genre_config import get_genre_config

        genre_config = get_genre_config(genre)
        result = ValidationResult()

        if not analysis.system_success or analysis.system is None:
            # If system analysis failed, we can't validate — pass with warning
            logger.warning("validation_skipped_no_system_analysis")
            return result

        system = analysis.system

        # Check earned power evaluations — only for earned_power genres
        if genre_config.validation_strategy == "earned_power":
            for ep_eval in system.earned_power_evaluations:
                if not ep_eval.approved:
                    issue = ValidationIssue(
                        issue_type="earned_power",
                        description=(
                            f"Unearned power advancement for {ep_eval.character_name}: "
                            f"{ep_eval.event_description}"
                        ),
                        severity="critical",
                        details=(
                            f"Score: {ep_eval.total_score:.2f}/1.0 "
                            f"(struggle={ep_eval.struggle_score:.2f}, "
                            f"foundation={ep_eval.foundation_score:.2f}, "
                            f"cost={ep_eval.cost_score:.2f}, "
                            f"buildup={ep_eval.buildup_score:.2f}). "
                            f"Reasoning: {ep_eval.reasoning}"
                        ),
                    )
                    result.issues.append(issue)
                    result.passed = False

        # Check consistency issues — all genres
        for ci in system.consistency_issues:
            if ci.severity == "critical":
                issue = ValidationIssue(
                    issue_type="consistency",
                    description=ci.description,
                    severity="critical",
                    details=f"Bible entry: {ci.bible_entry_content}. Fix: {ci.suggested_fix}",
                )
                result.issues.append(issue)
                result.passed = False

        if not result.passed:
            result.retry_guidance = self.build_retry_guidance(result, genre)

        logger.info(
            "validation_complete",
            passed=result.passed,
            issue_count=len(result.issues),
            genre=genre,
        )

        return result

    def build_retry_guidance(
        self,
        validation: ValidationResult,
        genre: str = "progression_fantasy",
    ) -> str:
        """Build specific guidance for the retry prompt from validation failures."""
        from aiwebnovel.story.genre_config import get_genre_config

        genre_config = get_genre_config(genre)
        lines: list[str] = [
            "CRITICAL: The previous draft was rejected. Fix these issues:\n"
        ]

        for i, issue in enumerate(validation.issues, 1):
            lines.append(f"{i}. [{issue.issue_type.upper()}] {issue.description}")
            if issue.details:
                lines.append(f"   Details: {issue.details}")

        if any(i.issue_type == "earned_power" for i in validation.issues):
            lines.append(
                "\nPOWER ADVANCEMENT GUIDANCE: Show more struggle, establish "
                "clearer foundation, include meaningful cost/sacrifice, and "
                "ensure narrative buildup across multiple chapters before any "
                "power gain. If the advancement can't be earned in this chapter, "
                "defer it to a later chapter."
            )

        if any(i.issue_type == "consistency" for i in validation.issues):
            guidance = (
                "\nCONSISTENCY GUIDANCE: Correct contradictions with established "
                "facts. Do not break the established rules or contradict "
                "previously established character knowledge/locations/events."
            )
            # Add genre-specific consistency guidance
            if (
                genre_config.validation_strategy == "consistency_only"
                and genre_config.system_analysis_addendum
            ):
                guidance += f"\n\nGenre-specific notes ({genre_config.display_name}):\n"
                guidance += genre_config.system_analysis_addendum
            lines.append(guidance)

        return "\n".join(lines)
