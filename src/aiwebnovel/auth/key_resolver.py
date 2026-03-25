"""Per-request API key resolution for BYOK and platform keys.

Resolution chain:
1. If user has BYOK key for model's provider → decrypt and return
2. If free tier with platform model → return None (env var key used)
3. If no valid key → raise KeyResolutionError

On decrypt failure: mark key as invalid, log error, return None
(graceful degradation — caller creates notification).
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.encryption import decrypt_api_key
from aiwebnovel.config import Settings
from aiwebnovel.db.models import AuthorAPIKey

logger = structlog.get_logger(__name__)


class KeyResolutionError(Exception):
    """Raised when no valid API key can be resolved for a request."""


def _provider_for_model(model: str) -> str | None:
    """Extract the provider name from a litellm model string.

    Examples:
        "anthropic/claude-sonnet-4-6" → "anthropic"
        "openai/gpt-4o" → "openai"
    """
    if "/" in model:
        return model.split("/")[0]
    return None


async def resolve_api_key(
    session: AsyncSession,
    user_id: int,
    model: str,
    settings: Settings,
) -> str | None:
    """Resolve the API key to use for a given model.

    Returns:
        - Decrypted BYOK key if user has one for the model's provider
        - None if platform key should be used (free tier / admin)

    On decrypt failure: marks the key as invalid and returns None.
    """
    provider = _provider_for_model(model)
    if not provider:
        return None  # Unknown model format — use platform default

    # Check if user has a BYOK key for this provider
    key_row = (
        await session.execute(
            select(AuthorAPIKey).where(
                AuthorAPIKey.user_id == user_id,
                AuthorAPIKey.provider == provider,
                AuthorAPIKey.is_valid.is_(True),
            )
        )
    ).scalar_one_or_none()

    if key_row is not None:
        try:
            decrypted = decrypt_api_key(
                key_row.encrypted_key, settings.encryption_key,
            )
            logger.debug(
                "byok_key_resolved",
                user_id=user_id,
                provider=provider,
            )
            return decrypted
        except Exception:
            # Mark key as invalid so user is prompted to re-enter
            key_row.is_valid = False
            await session.flush()
            logger.error(
                "byok_key_decrypt_failed_marked_invalid",
                user_id=user_id,
                provider=provider,
            )
            return None  # Graceful degradation — platform key used

    # No BYOK key — use platform key (returns None, litellm uses env var)
    return None


async def resolve_image_key(
    session: AsyncSession,
    user_id: int,
    settings: Settings,
) -> str | None:
    """Resolve the image generation API key.

    Returns:
        - Decrypted BYOK Replicate key if user has one
        - None for platform Replicate key

    On decrypt failure: marks the key as invalid and returns None.
    """
    key_row = (
        await session.execute(
            select(AuthorAPIKey).where(
                AuthorAPIKey.user_id == user_id,
                AuthorAPIKey.provider == "replicate",
                AuthorAPIKey.is_valid.is_(True),
            )
        )
    ).scalar_one_or_none()

    if key_row is not None:
        try:
            return decrypt_api_key(
                key_row.encrypted_key, settings.encryption_key,
            )
        except Exception:
            key_row.is_valid = False
            await session.flush()
            logger.error(
                "byok_image_key_decrypt_failed_marked_invalid",
                user_id=user_id,
            )
    return None
