"""Tests for LLMProvider.

All litellm calls are mocked — no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import litellm.exceptions
import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.config import Settings
from aiwebnovel.db.models import AuthorProfile, Novel, User
from aiwebnovel.llm.budget import BudgetExceededError
from aiwebnovel.llm.provider import ContextOverflowError, LLMProvider, LLMResponse

# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def provider_settings() -> Settings:
    return Settings(
        jwt_secret_key="test-secret",
        litellm_default_model="anthropic/claude-sonnet-4-6",
        litellm_fallback_model="openai/gpt-4o-mini",
        context_window_cap=30000,
        model_pricing={
            "anthropic/claude-sonnet-4-6": {
                "input_cost_per_1k": 0.3,
                "output_cost_per_1k": 1.5,
            },
            "openai/gpt-4o-mini": {
                "input_cost_per_1k": 0.015,
                "output_cost_per_1k": 0.06,
            },
        },
    )


@pytest.fixture()
def mock_session_factory(db_session: AsyncSession):
    """Create a session factory that returns the test session.

    async_sessionmaker.__call__ returns a context manager (not a coroutine),
    so we replicate that with a simple callable class.
    """

    class FakeContextManager:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            pass

    class FakeSessionFactory:
        """Mimics async_sessionmaker: calling it returns an async CM."""

        def __call__(self):
            return FakeContextManager()

    return FakeSessionFactory()


@pytest.fixture()
def provider(provider_settings: Settings, mock_session_factory) -> LLMProvider:
    return LLMProvider(provider_settings, mock_session_factory)


def _mock_litellm_response(
    content: str = "Test response",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "anthropic/claude-sonnet-4-6",
):
    """Create a mock litellm response object."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage = MagicMock()
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    response.model = model
    return response


# ═══════════════════════════════════════════════════════════════════════════
# INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════


class TestLLMProviderInit:
    def test_creates_with_settings(self, provider: LLMProvider) -> None:
        assert provider.settings.litellm_default_model == "anthropic/claude-sonnet-4-6"

    def test_has_encoder(self, provider: LLMProvider) -> None:
        assert provider._encoder is not None

    def test_has_budget_checker(self, provider: LLMProvider) -> None:
        assert provider.budget_checker is not None


# ═══════════════════════════════════════════════════════════════════════════
# COST CALCULATION
# ═══════════════════════════════════════════════════════════════════════════


class TestCostCalculation:
    def test_known_model(self, provider: LLMProvider) -> None:
        cost = provider.calculate_cost(
            "anthropic/claude-sonnet-4-6",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        # (1000/1000 * 0.3) + (500/1000 * 1.5) = 0.3 + 0.75 = 1.05
        assert abs(cost - 1.05) < 0.001

    def test_cheap_model(self, provider: LLMProvider) -> None:
        cost = provider.calculate_cost(
            "openai/gpt-4o-mini",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        # (1000/1000 * 0.015) + (500/1000 * 0.06) = 0.015 + 0.03 = 0.045
        assert abs(cost - 0.045) < 0.001

    def test_unknown_model_returns_zero(self, provider: LLMProvider) -> None:
        cost = provider.calculate_cost(
            "unknown/model", prompt_tokens=1000, completion_tokens=500
        )
        assert cost == 0.0

    def test_zero_tokens(self, provider: LLMProvider) -> None:
        cost = provider.calculate_cost(
            "anthropic/claude-sonnet-4-6",
            prompt_tokens=0,
            completion_tokens=0,
        )
        assert cost == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# TOKEN ESTIMATION
# ═══════════════════════════════════════════════════════════════════════════


class TestTokenEstimation:
    def test_basic_estimation(self, provider: LLMProvider) -> None:
        tokens = provider.estimate_tokens("Hello, world!")
        assert tokens > 0
        assert tokens < 10

    def test_empty_string(self, provider: LLMProvider) -> None:
        tokens = provider.estimate_tokens("")
        assert tokens == 0

    def test_longer_text(self, provider: LLMProvider) -> None:
        text = "This is a longer piece of text that should produce more tokens. " * 10
        tokens = provider.estimate_tokens(text)
        assert tokens > 50


# ═══════════════════════════════════════════════════════════════════════════
# CONTEXT OVERFLOW
# ═══════════════════════════════════════════════════════════════════════════


class TestContextOverflow:
    def test_raises_on_overflow(self, provider: LLMProvider) -> None:
        """If prompt + max_tokens exceeds the limit, should raise."""
        # Force a small context limit
        with patch.object(provider, "_get_model_context_limit", return_value=1000):
            with pytest.raises(ContextOverflowError) as exc_info:
                provider._check_context_window("test-model", 800, 400)
            assert exc_info.value.estimated_tokens == 800

    def test_passes_within_limit(self, provider: LLMProvider) -> None:
        with patch.object(provider, "_get_model_context_limit", return_value=10000):
            # Should not raise
            provider._check_context_window("test-model", 2000, 4000)


# ═══════════════════════════════════════════════════════════════════════════
# GENERATE
# ═══════════════════════════════════════════════════════════════════════════


class TestGenerate:
    @pytest.mark.asyncio
    async def test_basic_generate(self, provider: LLMProvider) -> None:
        mock_response = _mock_litellm_response(content="Generated text")
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            with patch.object(provider, "_get_model_context_limit", return_value=100000):
                result = await provider.generate(
                    system="You are helpful.",
                    user="Say hello.",
                )
        assert isinstance(result, LLMResponse)
        assert result.content == "Generated text"
        assert result.model == "anthropic/claude-sonnet-4-6"
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50

    @pytest.mark.asyncio
    async def test_generate_with_cost(self, provider: LLMProvider) -> None:
        mock_response = _mock_litellm_response(
            prompt_tokens=1000, completion_tokens=500
        )
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            with patch.object(provider, "_get_model_context_limit", return_value=100000):
                result = await provider.generate(
                    system="System", user="User"
                )
        assert abs(result.cost_cents - 1.05) < 0.001

    @pytest.mark.asyncio
    async def test_generate_context_overflow(self, provider: LLMProvider) -> None:
        with patch.object(provider, "_get_model_context_limit", return_value=100):
            with pytest.raises(ContextOverflowError):
                await provider.generate(
                    system="System prompt " * 100,
                    user="User prompt " * 100,
                )

    @pytest.mark.asyncio
    async def test_budget_check_before_call(
        self, provider: LLMProvider, db_session: AsyncSession
    ) -> None:
        """When novel_id is provided, budget should be checked."""
        # Create test data with exhausted budget
        user = User(
            email="test@test.com", username="test", role="author",
            is_anonymous=False, auth_provider="local",
        )
        db_session.add(user)
        await db_session.flush()

        profile = AuthorProfile(
            user_id=user.id, api_budget_cents=500, api_spent_cents=500
        )
        db_session.add(profile)
        await db_session.flush()

        novel = Novel(
            author_id=user.id, title="Test", genre="progression_fantasy"
        )
        db_session.add(novel)
        await db_session.flush()

        with patch.object(provider, "_get_model_context_limit", return_value=100000):
            with pytest.raises(BudgetExceededError):
                await provider.generate(
                    system="System",
                    user="User",
                    novel_id=novel.id,
                    user_id=user.id,
                )


# ═══════════════════════════════════════════════════════════════════════════
# RETRY LOGIC
# ═══════════════════════════════════════════════════════════════════════════


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retries_on_failure(self, provider: LLMProvider) -> None:
        """Should retry up to 3 times before falling back to next model."""
        mock_response = _mock_litellm_response(
            content="Fallback response",
            model="openai/gpt-4o-mini",
        )
        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:  # First model fails all 3 times
                raise litellm.exceptions.APIError(
                    message="API error",
                    status_code=500,
                    llm_provider="test",
                    model="test",
                )
            return mock_response

        with patch("litellm.acompletion", side_effect=mock_acompletion):
            with patch.object(provider, "_get_model_context_limit", return_value=100000):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await provider.generate(
                        system="System", user="User"
                    )

        assert result.content == "Fallback response"
        # 3 failures on primary + 1 success on fallback = 4 calls
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(
        self, provider: LLMProvider
    ) -> None:
        """If all models fail all retries, should raise RuntimeError."""

        async def always_fail(**kwargs):
            raise litellm.exceptions.APIError(
                message="Permanent failure",
                status_code=500,
                llm_provider="test",
                model="test",
            )

        with patch("litellm.acompletion", side_effect=always_fail):
            with patch.object(provider, "_get_model_context_limit", return_value=100000):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(RuntimeError, match="All LLM models failed"):
                        await provider.generate(
                            system="System", user="User"
                        )


# ═══════════════════════════════════════════════════════════════════════════
# STRUCTURED OUTPUT
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuredOutput:
    @pytest.mark.asyncio
    async def test_parses_json_response(self, provider: LLMProvider) -> None:
        class TestModel(BaseModel):
            name: str
            value: int

        json_content = '{"name": "test", "value": 42}'
        mock_response = _mock_litellm_response(content=json_content)

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            with patch.object(provider, "_get_model_context_limit", return_value=100000):
                result = await provider.generate(
                    system="System",
                    user="User",
                    response_format=TestModel,
                )
        # Content should be the re-serialised model
        parsed = TestModel.model_validate_json(result.content)
        assert parsed.name == "test"
        assert parsed.value == 42


# ═══════════════════════════════════════════════════════════════════════════
# USAGE LOGGING
# ═══════════════════════════════════════════════════════════════════════════


class TestUsageLogging:
    @pytest.mark.asyncio
    async def test_logs_usage_when_user_id_provided(
        self, provider: LLMProvider, db_session: AsyncSession
    ) -> None:
        """When user_id is set, usage should be logged to DB."""
        user = User(
            email="log_test@test.com", username="logtest", role="author",
            is_anonymous=False, auth_provider="local",
        )
        db_session.add(user)
        await db_session.flush()

        profile = AuthorProfile(
            user_id=user.id, api_budget_cents=10000, api_spent_cents=0
        )
        db_session.add(profile)
        await db_session.flush()

        novel = Novel(
            author_id=user.id, title="Log Test", genre="progression_fantasy"
        )
        db_session.add(novel)
        await db_session.flush()

        mock_response = _mock_litellm_response(
            prompt_tokens=100, completion_tokens=50
        )

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            with patch.object(provider, "_get_model_context_limit", return_value=100000):
                result = await provider.generate(
                    system="System",
                    user="User",
                    novel_id=novel.id,
                    user_id=user.id,
                    purpose="test_purpose",
                )

        assert result.cost_cents > 0


# ═══════════════════════════════════════════════════════════════════════════
# STREAMING
# ═══════════════════════════════════════════════════════════════════════════


class TestStreaming:
    @pytest.mark.asyncio
    async def test_generate_stream_yields_tokens(
        self, provider: LLMProvider
    ) -> None:
        """generate_stream should yield individual token chunks."""
        chunks = []
        for word in ["Hello", " ", "world", "!"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock()
            chunk.choices[0].delta.content = word
            chunks.append(chunk)

        async def mock_stream():
            for c in chunks:
                yield c

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_stream()):
            with patch.object(provider, "_get_model_context_limit", return_value=100000):
                collected = []
                async for token in provider.generate_stream(
                    system="System", user="User"
                ):
                    collected.append(token)

        assert "".join(collected) == "Hello world!"


# ═══════════════════════════════════════════════════════════════════════════
# LLMRESPONSE DATACLASS
# ═══════════════════════════════════════════════════════════════════════════


class TestLLMResponse:
    def test_fields(self) -> None:
        r = LLMResponse(
            content="test",
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            cost_cents=1.5,
            duration_ms=500,
        )
        assert r.content == "test"
        assert r.model == "test-model"
        assert r.prompt_tokens == 100
        assert r.completion_tokens == 50
        assert r.cost_cents == 1.5
        assert r.duration_ms == 500
