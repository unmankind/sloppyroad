"""Authentication routes: register, login, logout, OAuth stubs, reader claim.

All endpoints are async. JWT tokens are stateless — logout is client-side.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import bcrypt as _bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import get_or_create_anonymous_reader
from aiwebnovel.auth.jwt import create_access_token
from aiwebnovel.db.models import AuthorProfile, User
from aiwebnovel.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    username: str = Field(..., min_length=2, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    message: str


class ReaderClaimRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    username: str = Field(..., min_length=2, max_length=100)


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse | MessageResponse:
    """Register a new author account."""
    # Check if email already exists
    stmt = select(User).where(User.email == body.email)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create user
    settings = request.app.state.settings
    hashed = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode()
    user = User(
        email=body.email,
        username=body.username,
        display_name=body.username,
        hashed_password=hashed,
        auth_provider="local",
        role="author",
        is_active=True,
        is_anonymous=False,
        email_verified=not settings.email_verification_required,
    )
    db.add(user)
    await db.flush()

    # Create author profile with free tier defaults
    profile = AuthorProfile(
        user_id=user.id,
        display_name=body.username,
        plan_type="free",
        api_budget_cents=settings.free_tier_lifetime_budget_cents,
        image_budget_cents=100,
    )
    db.add(profile)
    await db.flush()

    # If email verification required, send email instead of returning JWT
    if settings.email_verification_required:
        from aiwebnovel.auth.verification import create_verification
        from aiwebnovel.email.provider import send_verification_email

        verification_token = await create_verification(
            db, user, settings.email_verification_expire_minutes,
        )
        base_url = str(request.base_url).rstrip("/")
        await send_verification_email(
            str(body.email),
            verification_token,
            base_url,
            resend_api_key=settings.resend_api_key,
            sender=settings.email_sender,
        )
        await db.commit()
        logger.info("user_registered_verification_pending", user_id=user.id)
        return MessageResponse(
            message="Account created. Please check your email to verify."
        )

    # Generate JWT
    token = create_access_token(
        data={"sub": user.email, "user_id": user.id, "role": user.role},
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )

    logger.info("user_registered", user_id=user.id, email=user.email)

    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate and return JWT access token."""
    stmt = select(User).where(User.email == body.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not _bcrypt.checkpw(body.password.encode(), user.hashed_password.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    settings = request.app.state.settings

    # Email verification gate
    if settings.email_verification_required and not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )

    token = create_access_token(
        data={"sub": user.email, "user_id": user.id, "role": user.role},
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )

    logger.info("user_logged_in", user_id=user.id)

    return TokenResponse(access_token=token)


@router.post("/logout", response_model=MessageResponse)
async def logout() -> MessageResponse:
    """Logout placeholder — JWT is stateless, client deletes token."""
    return MessageResponse(message="Logged out successfully. Please discard your token.")


@router.get("/oauth/{provider}")
async def oauth_redirect(provider: str) -> dict[str, Any]:
    """OAuth redirect URL stub."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"OAuth provider '{provider}' not yet implemented",
    )


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str) -> dict[str, Any]:
    """OAuth callback stub."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"OAuth callback for '{provider}' not yet implemented",
    )


@router.post("/reader/claim", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def reader_claim(
    body: ReaderClaimRequest,
    request: Request,
    reader: dict = Depends(get_or_create_anonymous_reader),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Upgrade anonymous reader to a registered author account."""
    # Check email not taken
    stmt = select(User).where(User.email == body.email)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    hashed = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode()
    user = User(
        email=body.email,
        username=body.username,
        display_name=body.username,
        hashed_password=hashed,
        auth_provider="local",
        role="author",
        is_active=True,
        is_anonymous=False,
        cookie_token=reader.get("reader_id"),
    )
    db.add(user)
    await db.flush()

    profile = AuthorProfile(
        user_id=user.id,
        display_name=body.username,
    )
    db.add(profile)
    await db.flush()

    settings = request.app.state.settings
    token = create_access_token(
        data={"sub": user.email, "user_id": user.id, "role": user.role},
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )

    logger.info("reader_claimed", user_id=user.id, reader_id=reader.get("reader_id"))

    return TokenResponse(access_token=token)
