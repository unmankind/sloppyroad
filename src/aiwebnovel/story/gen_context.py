"""GenerationContext — carries per-request auth context through the pipeline.

Resolved once at pipeline entry, passed to all sub-calls. Avoids threading
api_key through 40+ method signatures.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.tier import AuthorTier, resolve_model, resolve_tier
from aiwebnovel.config import Settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GenerationContext:
    """Immutable per-request context for generation pipelines."""

    user_id: int
    tier: AuthorTier
    model: str
    api_key: str | None  # decrypted BYOK key, or None for platform key
    image_key: str | None  # decrypted BYOK Replicate key, or None
    is_platform_key: bool  # True when using platform key (costs counted)

    @classmethod
    async def resolve(
        cls,
        session: AsyncSession,
        user_id: int,
        novel_id: int | None,
        settings: Settings,
        requested_model: str | None = None,
    ) -> GenerationContext:
        """Resolve tier, model, and keys for a generation request."""
        # Avoid circular imports
        from aiwebnovel.auth.key_resolver import (
            resolve_api_key,
            resolve_image_key,
        )

        tier_info = await resolve_tier(session, user_id, settings)
        model = await resolve_model(
            session, user_id, requested_model, settings,
        )
        api_key = await resolve_api_key(
            session, user_id, model, settings,
        )
        image_key = await resolve_image_key(session, user_id, settings)

        # Notify BYOK user if their key failed (using platform fallback)
        if tier_info.tier == AuthorTier.BYOK and api_key is None:
            try:
                from aiwebnovel.db.models import Notification

                notification = Notification(
                    user_id=user_id,
                    notification_type="key_error",
                    title="API key error",
                    message=(
                        "Your API key could not be used. "
                        "Please re-enter it in Settings. "
                        "Using platform key as fallback for this generation."
                    ),
                    action_url="/dashboard/settings#api-keys",
                )
                session.add(notification)
                await session.flush()
            except Exception:
                logger.warning("key_error_notification_failed", user_id=user_id)

        ctx = cls(
            user_id=user_id,
            tier=tier_info.tier,
            model=model,
            api_key=api_key,
            image_key=image_key,
            is_platform_key=(api_key is None),
        )

        logger.info(
            "generation_context_resolved",
            user_id=user_id,
            tier=ctx.tier.value,
            model=ctx.model,
            is_platform_key=ctx.is_platform_key,
        )
        return ctx
