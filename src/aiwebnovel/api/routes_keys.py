"""BYOK API key management routes: add, remove, list, validate."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import require_db_author
from aiwebnovel.auth.encryption import (
    encrypt_api_key,
    extract_key_suffix,
    validate_key_format,
    validate_provider,
)
from aiwebnovel.db.models import APIKeyAuditLog, AuthorAPIKey, AuthorProfile
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────


class AddKeyRequest(BaseModel):
    provider: str
    api_key: str


class APIKeyRead(BaseModel):
    provider: str
    key_suffix: str
    is_valid: bool
    validated_at: datetime | None
    created_at: datetime


class KeyListResponse(BaseModel):
    keys: list[APIKeyRead]
    plan_type: str


class MessageResponse(BaseModel):
    message: str


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("/dashboard/keys", response_model=KeyListResponse)
async def list_keys(
    user: dict = Depends(require_db_author),
    db: AsyncSession = Depends(get_db),
) -> KeyListResponse:
    """List the author's configured API keys (masked)."""
    keys = (
        await db.execute(
            select(AuthorAPIKey)
            .where(AuthorAPIKey.user_id == user["user_id"])
            .order_by(AuthorAPIKey.created_at)
        )
    ).scalars().all()

    profile = (
        await db.execute(
            select(AuthorProfile).where(
                AuthorProfile.user_id == user["user_id"]
            )
        )
    ).scalar_one_or_none()

    return KeyListResponse(
        keys=[
            APIKeyRead(
                provider=k.provider,
                key_suffix=f"...{k.key_suffix}",
                is_valid=k.is_valid,
                validated_at=k.validated_at,
                created_at=k.created_at,
            )
            for k in keys
        ],
        plan_type=profile.plan_type if profile else "free",
    )


@router.post("/dashboard/keys", response_model=APIKeyRead)
async def add_key(
    body: AddKeyRequest,
    request: Request,
    user: dict = Depends(require_db_author),
    db: AsyncSession = Depends(get_db),
) -> APIKeyRead:
    """Add or update a BYOK API key. Validates the key before saving."""
    settings = request.app.state.settings

    # Validate provider
    valid, err = validate_provider(body.provider)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=err
        )

    # Validate key format
    valid, err = validate_key_format(body.provider, body.api_key)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=err
        )

    # Validate key works by making a test API call
    is_valid = await _validate_key_live(body.provider, body.api_key)
    if not is_valid:
        # Audit the failed attempt
        db.add(
            APIKeyAuditLog(
                user_id=user["user_id"],
                action="failed",
                provider=body.provider,
                ip_address=request.client.host if request.client else None,
            )
        )
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Key validation failed for {body.provider}. "
                "Please check that the key is correct and active."
            ),
        )

    # Encrypt and store (upsert — one key per provider)
    encrypted = encrypt_api_key(body.api_key, settings.encryption_key)
    suffix = extract_key_suffix(body.api_key)
    now = datetime.now(tz=UTC).replace(tzinfo=None)

    existing = (
        await db.execute(
            select(AuthorAPIKey).where(
                AuthorAPIKey.user_id == user["user_id"],
                AuthorAPIKey.provider == body.provider,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.encrypted_key = encrypted
        existing.key_suffix = suffix
        existing.is_valid = True
        existing.validated_at = now
        existing.updated_at = now
        key_row = existing
    else:
        key_row = AuthorAPIKey(
            user_id=user["user_id"],
            provider=body.provider,
            encrypted_key=encrypted,
            key_suffix=suffix,
            is_valid=True,
            validated_at=now,
        )
        db.add(key_row)

    # Update plan_type to byok
    profile = (
        await db.execute(
            select(AuthorProfile).where(
                AuthorProfile.user_id == user["user_id"]
            )
        )
    ).scalar_one_or_none()
    if profile and profile.plan_type == "free":
        profile.plan_type = "byok"

    # Audit log
    db.add(
        APIKeyAuditLog(
            user_id=user["user_id"],
            action="added",
            provider=body.provider,
            ip_address=request.client.host if request.client else None,
        )
    )

    await db.flush()
    logger.info(
        "byok_key_added",
        user_id=user["user_id"],
        provider=body.provider,
    )

    return APIKeyRead(
        provider=key_row.provider,
        key_suffix=f"...{key_row.key_suffix}",
        is_valid=key_row.is_valid,
        validated_at=key_row.validated_at,
        created_at=key_row.created_at,
    )


@router.delete("/dashboard/keys/{provider}", response_model=MessageResponse)
async def remove_key(
    provider: str,
    request: Request,
    user: dict = Depends(require_db_author),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Remove a BYOK API key."""
    key_row = (
        await db.execute(
            select(AuthorAPIKey).where(
                AuthorAPIKey.user_id == user["user_id"],
                AuthorAPIKey.provider == provider,
            )
        )
    ).scalar_one_or_none()

    if key_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No key configured for {provider}",
        )

    await db.delete(key_row)

    # Check if any keys remain — if not, revert to free
    remaining = (
        await db.execute(
            select(AuthorAPIKey).where(
                AuthorAPIKey.user_id == user["user_id"]
            )
        )
    ).scalars().all()

    if not remaining:
        profile = (
            await db.execute(
                select(AuthorProfile).where(
                    AuthorProfile.user_id == user["user_id"]
                )
            )
        ).scalar_one_or_none()
        if profile and profile.plan_type == "byok":
            profile.plan_type = "free"

    # Audit log
    db.add(
        APIKeyAuditLog(
            user_id=user["user_id"],
            action="removed",
            provider=provider,
            ip_address=request.client.host if request.client else None,
        )
    )

    await db.flush()
    logger.info(
        "byok_key_removed",
        user_id=user["user_id"],
        provider=provider,
    )

    return MessageResponse(
        message=f"{provider.title()} key removed."
    )


# ── Key validation helpers ─────────────────────────────────────────────────


async def _validate_key_live(provider: str, api_key: str) -> bool:
    """Validate an API key by making a minimal test call.

    Returns True if the key is valid, False otherwise.
    """
    try:
        if provider in ("anthropic", "openai"):
            import litellm

            model = {
                "anthropic": "anthropic/claude-haiku-4-5-20251001",
                "openai": "openai/gpt-4o-mini",
            }[provider]
            await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                api_key=api_key,
            )
            return True

        elif provider == "replicate":
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.replicate.com/v1/account",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10,
                )
                return resp.status_code == 200

    except Exception:
        logger.debug(
            "key_validation_failed",
            provider=provider,
        )
    return False
