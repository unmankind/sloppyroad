"""Sanitize and humanize error messages.

Applied at ALL exception capture points: LLM provider, worker tasks,
health checks, SSE error events.
"""

from __future__ import annotations

import re

# Patterns that match common API key formats
_KEY_PATTERNS = re.compile(
    r"(sk-ant-api\S+|sk-ant-\S+|sk-proj-\S+|sk-\S{20,}|r8_\S+|key-\S+)"
)


def sanitize_error_message(msg: str) -> str:
    """Strip API key patterns from an error message.

    Examples:
        "Invalid API key: sk-ant-api03-abc123..." → "Invalid API key: [REDACTED]"
        "Auth failed with r8_abc123xyz..." → "Auth failed with [REDACTED]"
    """
    return _KEY_PATTERNS.sub("[REDACTED]", msg)


def friendly_generation_error(exc: Exception) -> str:
    """Convert a raw exception into a user-friendly generation error message."""
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        return (
            "The AI's response didn't match the expected format. "
            "This is usually temporary — please retry."
        )

    # litellm exceptions
    exc_name = type(exc).__name__
    if exc_name in (
        "APIError", "Timeout", "RateLimitError",
        "APIConnectionError", "ServiceUnavailableError",
    ):
        return (
            "The AI service is temporarily unavailable. "
            "Please try again in a few minutes."
        )

    # BudgetExceededError — already user-friendly
    if exc_name == "BudgetExceededError":
        return str(exc)

    return "An unexpected error occurred during generation. Please retry."
