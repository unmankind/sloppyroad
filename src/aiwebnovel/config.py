"""Application settings via pydantic-settings.

All settings have sane defaults for local development.
Override via environment variables with AIWN_ prefix or via .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for AIWN 2.0."""

    model_config = SettingsConfigDict(
        env_prefix="AIWN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./aiwebnovel.db"
    database_echo: bool = False
    db_pool_size: int = 5
    db_pool_max_overflow: int = 10
    db_pool_recycle: int = 3600  # seconds; recycle connections after 1 hour
    db_pool_pre_ping: bool = True  # verify connections before checkout

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── LiteLLM ───────────────────────────────────────────────────────────
    litellm_api_key: str = ""
    llm_timeout_seconds: int = 300
    litellm_default_model: str = "anthropic/claude-sonnet-4-6"
    litellm_fallback_model: str = "openai/gpt-5.4-nano"
    litellm_eval_model: str = "anthropic/claude-3-haiku-20240307"
    litellm_world_gen_model: str = "anthropic/claude-haiku-4-5-20251001"

    # ── Image Generation ──────────────────────────────────────────────────
    # NOTE: When False (default), NO images generate — including cover art.
    # Set AIWN_IMAGE_ENABLED=true and configure a provider to enable covers.
    image_enabled: bool = False
    image_provider: str = "comfyui"  # comfyui, replicate, dall-e-3, hf-space
    image_asset_path: str = "./assets/images"

    # ── Replicate (image_provider=replicate) ─────────────────────────────
    replicate_api_token: str = ""
    replicate_model: str = "black-forest-labs/flux-schnell"  # or flux-dev
    replicate_poll_interval: float = 0.5  # seconds between status polls
    replicate_timeout: float = 120.0  # max wait for generation

    # ── HuggingFace Space (image_provider=hf-space) ──────────────────────
    hf_space_id: str = "mrfakename/Z-Image-Turbo"
    hf_space_inference_steps: int = 9
    hf_token: str = ""

    # ── Vector DB ─────────────────────────────────────────────────────────
    vector_db_path: str = "./vector_store"
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = 768

    # ── Worker ────────────────────────────────────────────────────────────
    worker_concurrency: int = 3
    worker_retry_max: int = 3
    worker_stale_threshold_seconds: int = 600  # 10 min — Sonnet chapters take ~4 min
    worker_heartbeat_interval_seconds: int = 30
    generation_stale_display_seconds: int = 300

    # ── Auth / JWT ────────────────────────────────────────────────────────
    jwt_secret_key: str  # REQUIRED — no default for security
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24 hours

    # ── OAuth ─────────────────────────────────────────────────────────────
    oauth_google_client_id: str = ""
    oauth_github_client_id: str = ""

    # ── Stripe ────────────────────────────────────────────────────────────
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""

    # ── Encryption (BYOK key storage) ────────────────────────────────────
    encryption_key: str = ""  # Fernet key — REQUIRED in production

    # ── Free Tier Limits ─────────────────────────────────────────────────
    free_tier_max_worlds: int = 2
    free_tier_max_chapters: int = 3
    free_tier_model: str = "anthropic/claude-haiku-4-5-20251001"
    free_tier_lifetime_budget_cents: int = 500  # $5 hard cap

    # ── Email Verification ───────────────────────────────────────────────
    resend_api_key: str = ""
    email_sender: str = "noreply@sloppyroad.com"
    email_verification_expire_minutes: int = 240  # 4 hours
    email_verification_required: bool = True  # required for public launch

    # ── LLM Concurrency ───────────────────────────────────────────────────
    llm_max_concurrent: int = 10  # max simultaneous LLM API calls

    # ── App ───────────────────────────────────────────────────────────────
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:8003"]
    app_port: int = 8003
    sentry_dsn: str = ""  # Sentry error tracking DSN (empty = disabled)

    # ── Model Pricing (cents per 1k tokens) ───────────────────────────────
    model_pricing: dict[str, dict[str, float]] = {
        "anthropic/claude-sonnet-4-6": {
            "input_cost_per_1k": 0.3,
            "output_cost_per_1k": 1.5,
        },
        "anthropic/claude-3-haiku-20240307": {
            "input_cost_per_1k": 0.025,
            "output_cost_per_1k": 0.125,
        },
        "anthropic/claude-haiku-4-5-20251001": {
            "input_cost_per_1k": 0.08,
            "output_cost_per_1k": 0.4,
        },
        "openai/gpt-5.4": {
            "input_cost_per_1k": 0.0025,
            "output_cost_per_1k": 0.015,
        },
        "openai/gpt-5.4-mini": {
            "input_cost_per_1k": 0.00075,
            "output_cost_per_1k": 0.0045,
        },
        "openai/gpt-5.4-nano": {
            "input_cost_per_1k": 0.0002,
            "output_cost_per_1k": 0.00125,
        },
    }

    # ── Image Pricing (cents per image) ───────────────────────────────────
    image_pricing: dict[str, float] = {
        "comfyui": 0.0,
        "replicate": 1.0,
        "dall-e-3": 4.0,
        "hf-space": 0.0,
    }

    # ── Context Window ────────────────────────────────────────────────────
    context_window_cap: int = 200000
    max_chapter_tokens: int = 8000

    # ── Budget ────────────────────────────────────────────────────────────
    trial_budget_cents: int = 500
    autonomous_daily_budget_cents: int = 100

    # ── Rate Limiting (requests per minute per tier) ──────────────────────
    rate_limit_auth: int = 3  # low to prevent brute-force (3 attempts/min)
    rate_limit_generation: int = 5
    rate_limit_reader: int = 60
    rate_limit_browse: int = 600
    rate_limit_api: int = 200
    rate_limit_key_validation: int = 5


# ── Curated Model List for BYOK ─────────────────────────────────────────

AVAILABLE_MODELS: dict[str, list[dict[str, str]]] = {
    "anthropic": [
        {"id": "anthropic/claude-haiku-4-5-20251001", "name": "Haiku 4.5 (fast, cheap)"},
        {"id": "anthropic/claude-sonnet-4-6", "name": "Sonnet 4.6 (balanced)"},
    ],
    "openai": [
        {"id": "openai/gpt-5.4-nano", "name": "GPT-5.4 Nano (fast, cheap)"},
        {"id": "openai/gpt-5.4-mini", "name": "GPT-5.4 Mini (balanced)"},
        {"id": "openai/gpt-5.4", "name": "GPT-5.4 (best quality)"},
    ],
}

ALL_MODEL_IDS: set[str] = {
    m["id"] for models in AVAILABLE_MODELS.values() for m in models
}
