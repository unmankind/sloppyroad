"""Tests for AIWN 2.0 configuration system."""

import os
from unittest.mock import patch

import pytest

from aiwebnovel.config import Settings


@pytest.fixture(autouse=True)
def _clean_aiwn_env(monkeypatch):
    """Remove all AIWN_ env vars so defaults are tested accurately."""
    for key in list(os.environ):
        if key.startswith("AIWN_"):
            monkeypatch.delenv(key)


class TestSettingsDefaults:
    """Test that all settings have sane defaults for local development."""

    def test_default_database_url(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.database_url == "sqlite+aiosqlite:///./aiwebnovel.db"

    def test_default_database_echo(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.database_echo is False

    def test_default_redis_url(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.redis_url == "redis://localhost:6379"

    def test_default_litellm_model(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.litellm_default_model == "anthropic/claude-sonnet-4-6"

    def test_default_app_port(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.app_port == 8003

    def test_default_debug(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.debug is False

    def test_default_log_level(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.log_level == "INFO"

    def test_default_cors_origins(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert "http://localhost:8003" in settings.cors_origins

    def test_default_image_enabled(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.image_enabled is False

    def test_default_vector_db_path(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.vector_db_path == "./vector_store"

    def test_default_embedding_dimensions(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.embedding_dimensions == 768

    def test_default_worker_concurrency(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.worker_concurrency == 3

    def test_default_worker_retry_max(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.worker_retry_max == 3

    def test_default_jwt_algorithm(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.jwt_algorithm == "HS256"

    def test_default_jwt_expire_minutes(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.jwt_access_token_expire_minutes == 60 * 24

    def test_default_context_window_cap(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.context_window_cap == 200000

    def test_default_max_chapter_tokens(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.max_chapter_tokens == 8000

    def test_default_trial_budget_cents(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.trial_budget_cents == 500

    def test_default_autonomous_daily_budget_cents(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.autonomous_daily_budget_cents == 100


class TestSettingsEnvOverride:
    """Test that settings can be overridden via environment variables."""

    def test_env_override_database_url(self) -> None:
        with patch.dict(
            os.environ,
            {"AIWN_DATABASE_URL": "postgresql+asyncpg://localhost/aiwn"},
        ):
            settings = Settings(jwt_secret_key="test-secret")
            assert settings.database_url == (
                "postgresql+asyncpg://localhost/aiwn"
            )

    def test_env_override_debug(self) -> None:
        with patch.dict(os.environ, {"AIWN_DEBUG": "true"}):
            settings = Settings(jwt_secret_key="test-secret")
            assert settings.debug is True

    def test_env_override_app_port(self) -> None:
        with patch.dict(os.environ, {"AIWN_APP_PORT": "9000"}):
            settings = Settings(jwt_secret_key="test-secret")
            assert settings.app_port == 9000

    def test_env_override_redis_url(self) -> None:
        with patch.dict(
            os.environ, {"AIWN_REDIS_URL": "redis://custom:6380"},
        ):
            settings = Settings(jwt_secret_key="test-secret")
            assert settings.redis_url == "redis://custom:6380"

    def test_env_override_log_level(self) -> None:
        with patch.dict(os.environ, {"AIWN_LOG_LEVEL": "DEBUG"}):
            settings = Settings(jwt_secret_key="test-secret")
            assert settings.log_level == "DEBUG"


class TestSettingsModelPricing:
    """Test that model pricing defaults are populated."""

    def test_model_pricing_has_entries(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert len(settings.model_pricing) > 0

    def test_model_pricing_has_claude(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert any("claude" in key for key in settings.model_pricing)

    def test_model_pricing_has_input_output_costs(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        for model_name, costs in settings.model_pricing.items():
            assert "input_cost_per_1k" in costs, (
                f"{model_name} missing input_cost_per_1k"
            )
            assert "output_cost_per_1k" in costs, (
                f"{model_name} missing output_cost_per_1k"
            )

    def test_image_pricing_has_entries(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert len(settings.image_pricing) > 0


class TestSettingsRateLimiting:
    """Test rate limiting defaults."""

    def test_rate_limit_auth(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.rate_limit_auth == 3

    def test_rate_limit_generation(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.rate_limit_generation == 5

    def test_rate_limit_reader(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.rate_limit_reader == 60

    def test_rate_limit_browse(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.rate_limit_browse == 600

    def test_rate_limit_api(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.rate_limit_api == 200


class TestSettingsEnvPrefix:
    """Test that the AIWN_ prefix is properly applied."""

    def test_env_prefix(self) -> None:
        settings = Settings(jwt_secret_key="test-secret")
        assert settings.model_config.get("env_prefix") == "AIWN_"
