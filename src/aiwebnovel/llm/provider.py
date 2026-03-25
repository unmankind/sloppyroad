"""Provider-agnostic LLM interface via LiteLLM.

LLMProvider wraps litellm.acompletion() and litellm.aembedding() with:
- Automatic retry with exponential backoff
- Token counting and cost calculation
- Budget enforcement before and after calls
- Usage logging to the database
- Model fallback on failure
- Context window overflow detection
- Streaming support
- Structured JSON output with Pydantic parsing
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import litellm
import litellm.exceptions
import structlog
import tiktoken
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiwebnovel.config import Settings
from aiwebnovel.llm.budget import BudgetChecker, BudgetExceededError
from aiwebnovel.llm.sanitize import sanitize_error_message

logger = structlog.get_logger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)(?:\n```\s*)?$", re.DOTALL)


def strip_json_fences(text: str) -> str:
    """Strip markdown code fences and trailing commentary from LLM JSON output.

    Handles:
    - Complete fences (```json ... ```)
    - Truncated responses where the closing fence is missing
    - Trailing text after the closing brace/bracket (common with Haiku)
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        m = _JSON_FENCE_RE.match(stripped)
        stripped = m.group(1).rstrip() if m else stripped

    # Truncate after the last closing brace/bracket to remove trailing commentary
    if stripped.startswith("{"):
        last = stripped.rfind("}")
        if last != -1:
            stripped = stripped[: last + 1]
    elif stripped.startswith("["):
        last = stripped.rfind("]")
        if last != -1:
            stripped = stripped[: last + 1]

    return stripped


# Re-export for consumers
__all__ = [
    "BudgetExceededError",
    "ContextOverflowError",
    "LLMProvider",
    "LLMResponse",
]


class ContextOverflowError(Exception):
    """Raised when the prompt exceeds the model's context window."""

    def __init__(
        self, message: str, estimated_tokens: int = 0, max_tokens: int = 0
    ) -> None:
        super().__init__(message)
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens


@dataclass
class LLMResponse:
    """Structured response from an LLM call."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_cents: float
    duration_ms: int


class LLMProvider:
    """Provider-agnostic LLM interface via LiteLLM."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.budget_checker = BudgetChecker(settings)
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrent)

        # Configure litellm — set Anthropic key via env var.
        # Do NOT set litellm.api_key globally — it overrides per-provider
        # keys and causes Anthropic key to be sent to OpenAI endpoints.
        if settings.litellm_api_key:
            import os
            os.environ.setdefault(
                "ANTHROPIC_API_KEY", settings.litellm_api_key,
            )
        litellm.drop_params = True

        # Tiktoken encoder for token estimation
        try:
            self._encoder = tiktoken.encoding_for_model("gpt-4o")
        except KeyError:
            self._encoder = tiktoken.get_encoding("cl100k_base")

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for a string."""
        return len(self._encoder.encode(text))

    def _estimate_prompt_tokens(self, system: str, user: str) -> int:
        """Estimate total prompt tokens including message framing overhead."""
        # ~4 tokens per message for framing
        return self.estimate_tokens(system) + self.estimate_tokens(user) + 8

    # ------------------------------------------------------------------
    # Cost calculation
    # ------------------------------------------------------------------

    def calculate_cost(
        self, model: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """Calculate cost in cents from the pricing config."""
        pricing = self.settings.model_pricing.get(model)
        if pricing is None:
            logger.warning("unknown_model_pricing", model=model)
            return 0.0
        input_cost = (prompt_tokens / 1000) * pricing["input_cost_per_1k"]
        output_cost = (completion_tokens / 1000) * pricing["output_cost_per_1k"]
        return round(input_cost + output_cost, 6)

    # ------------------------------------------------------------------
    # Context window check
    # ------------------------------------------------------------------

    def _get_model_context_limit(self, model: str) -> int:
        """Get the context window size for a model, capped by settings."""
        try:
            info = litellm.get_model_info(model)
            model_limit = info.get("max_input_tokens") or info.get("max_tokens") or 128000
        except Exception:
            model_limit = 128000
        return min(model_limit, self.settings.context_window_cap)

    def _check_context_window(
        self, model: str, estimated_tokens: int, max_tokens: int
    ) -> None:
        """Raise ContextOverflowError if prompt + max_tokens exceeds limit."""
        context_limit = self._get_model_context_limit(model)
        total_needed = estimated_tokens + max_tokens
        if total_needed > context_limit:
            raise ContextOverflowError(
                f"Prompt ({estimated_tokens} tokens) + max_tokens ({max_tokens}) = "
                f"{total_needed} exceeds model context limit of {context_limit}",
                estimated_tokens=estimated_tokens,
                max_tokens=context_limit,
            )

    # ------------------------------------------------------------------
    # Main generate method
    # ------------------------------------------------------------------

    async def generate(
        self,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        response_format: type[BaseModel] | None = None,
        stream: bool = False,
        novel_id: int | None = None,
        user_id: int | None = None,
        purpose: str = "general",
        api_key: str | None = None,
        is_platform_key: bool = True,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        If stream=True, this collects the full response (use generate_stream
        for token-by-token output). Budget is checked before and updated after.

        Args:
            api_key: Per-request BYOK key override. When set, passed to
                litellm.acompletion() to override environment variables.
            is_platform_key: When True, costs are tracked against the
                platform budget. When False (BYOK), costs are logged but
                don't increment api_spent_cents.
        """
        model = model or self.settings.litellm_default_model

        # Estimate tokens and check context window
        estimated_tokens = self._estimate_prompt_tokens(system, user)
        self._check_context_window(model, estimated_tokens, max_tokens)

        # Budget check
        if novel_id is not None:
            async with self.session_factory() as session:
                await self.budget_checker.check_llm_budget(session, novel_id)

        # Build messages
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        # Build kwargs
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format is not None:
            kwargs["response_format"] = {"type": "json_object"}

        # BYOK key injection — per-request, never stored in env
        if api_key is not None:
            kwargs["api_key"] = api_key

        # Attempt with retry and fallback (semaphore limits concurrency)
        models_to_try = [model]
        fallback = self.settings.litellm_fallback_model
        if fallback and fallback != model:
            models_to_try.append(self.settings.litellm_fallback_model)

        last_error: Exception | None = None
        kwargs["timeout"] = self.settings.llm_timeout_seconds

        async with self._semaphore:
            for current_model in models_to_try:
                kwargs["model"] = current_model
                for attempt in range(3):
                    try:
                        start_time = time.monotonic()
                        response = await litellm.acompletion(**kwargs)
                        duration_ms = int((time.monotonic() - start_time) * 1000)

                        content = response.choices[0].message.content or ""
                        usage = response.usage
                        prompt_tokens = usage.prompt_tokens if usage else estimated_tokens
                        completion_tokens = (
                            usage.completion_tokens
                            if usage
                            else self.estimate_tokens(content)
                        )

                        cost_cents = self.calculate_cost(
                            current_model, prompt_tokens, completion_tokens
                        )

                        llm_response = LLMResponse(
                            content=content,
                            model=current_model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            cost_cents=cost_cents,
                            duration_ms=duration_ms,
                        )

                        # Log usage and update budget (best-effort — never fail the generation)
                        if user_id is not None:
                            try:
                                async with self.session_factory() as session:
                                    await self.budget_checker.log_usage(
                                        session=session,
                                        novel_id=novel_id,
                                        user_id=user_id,
                                        model=current_model,
                                        prompt_tokens=prompt_tokens,
                                        completion_tokens=completion_tokens,
                                        cost_cents=cost_cents,
                                        purpose=purpose,
                                        duration_ms=duration_ms,
                                    )
                                    # Only increment platform budget when using
                                    # platform keys. BYOK costs are logged but
                                    # don't count against the platform budget.
                                    if novel_id is not None and is_platform_key:
                                        await self.budget_checker.update_spent(
                                            session, novel_id, cost_cents
                                        )
                                    await session.commit()
                            # Intentional broad catch: usage logging
                            # best-effort
                            except Exception as log_exc:
                                logger.warning(
                                    "usage_logging_failed",
                                    error=str(log_exc),
                                    model=current_model,
                                    purpose=purpose,
                                    novel_id=novel_id,
                                )

                        # Parse structured output if requested
                        if response_format is not None:
                            clean = strip_json_fences(content)
                            parsed = response_format.model_validate_json(clean)
                            llm_response.content = parsed.model_dump_json()

                        logger.info(
                            "llm_call_complete",
                            model=current_model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            cost_cents=cost_cents,
                            duration_ms=duration_ms,
                            purpose=purpose,
                        )
                        return llm_response

                    except (BudgetExceededError, ContextOverflowError):
                        raise
                    except (
                        litellm.exceptions.APIError,
                        litellm.exceptions.Timeout,
                        litellm.exceptions.RateLimitError,
                        litellm.exceptions.APIConnectionError,
                        litellm.exceptions.ServiceUnavailableError,
                        ValidationError,
                    ) as exc:
                        last_error = exc
                        wait = 2 ** attempt
                        logger.warning(
                            "llm_call_retry",
                            model=current_model,
                            attempt=attempt + 1,
                            error=sanitize_error_message(str(exc)),
                            wait_seconds=wait,
                        )
                        if attempt < 2:
                            await asyncio.sleep(wait)

                logger.warning(
                    "llm_model_exhausted_retries",
                    model=current_model,
                    error=sanitize_error_message(str(last_error)),
                )

        msg = f"All LLM models failed after retries: {sanitize_error_message(str(last_error))}"
        raise RuntimeError(msg) from last_error

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def generate_stream(
        self,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        novel_id: int | None = None,
        user_id: int | None = None,
        purpose: str = "general",
        api_key: str | None = None,
        is_platform_key: bool = True,
    ) -> AsyncIterator[str]:
        """Yield tokens as they arrive from the LLM.

        Callers iterate with ``async for token in provider.generate_stream(...)``.
        """
        model = model or self.settings.litellm_default_model

        estimated_tokens = self._estimate_prompt_tokens(system, user)
        self._check_context_window(model, estimated_tokens, max_tokens)

        if novel_id is not None:
            async with self.session_factory() as session:
                await self.budget_checker.check_llm_budget(session, novel_id)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        start_time = time.monotonic()
        collected_content: list[str] = []

        stream_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "timeout": self.settings.llm_timeout_seconds,
        }
        if api_key is not None:
            stream_kwargs["api_key"] = api_key

        # Acquire semaphore before starting stream; hold until stream completes
        await self._semaphore.acquire()
        try:
            response = await litellm.acompletion(**stream_kwargs)

            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    collected_content.append(delta.content)
                    yield delta.content
        finally:
            self._semaphore.release()

        duration_ms = int((time.monotonic() - start_time) * 1000)
        full_content = "".join(collected_content)
        completion_tokens = self.estimate_tokens(full_content)
        cost_cents = self.calculate_cost(model, estimated_tokens, completion_tokens)

        if user_id is not None:
            async with self.session_factory() as session:
                await self.budget_checker.log_usage(
                    session=session,
                    novel_id=novel_id,
                    user_id=user_id,
                    model=model,
                    prompt_tokens=estimated_tokens,
                    completion_tokens=completion_tokens,
                    cost_cents=cost_cents,
                    purpose=purpose,
                    duration_ms=duration_ms,
                )
                if novel_id is not None and is_platform_key:
                    await self.budget_checker.update_spent(
                        session, novel_id, cost_cents
                    )
                await session.commit()

        logger.info(
            "llm_stream_complete",
            model=model,
            tokens=estimated_tokens + completion_tokens,
            cost_cents=cost_cents,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(
        self,
        text: str | list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for one or more texts."""
        model = model or self.settings.embedding_model
        if isinstance(text, str):
            text = [text]

        kwargs: dict[str, Any] = {
            "model": model,
            "input": text,
            "timeout": self.settings.llm_timeout_seconds,
        }
        # Request specific dimensions if model supports it
        if self.settings.embedding_dimensions:
            kwargs["dimensions"] = self.settings.embedding_dimensions
        async with self._semaphore:
            response = await litellm.aembedding(**kwargs)
        return [item["embedding"] for item in response.data]
