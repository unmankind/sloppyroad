"""Auth page routes: login, register, logout, email verification."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

import bcrypt as _bcrypt
import structlog
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.jwt import create_access_token
from aiwebnovel.auth.verification import create_verification, verify_token
from aiwebnovel.db.models import AuthorProfile, User
from aiwebnovel.db.session import get_db
from aiwebnovel.email.provider import send_verification_email

from .helpers import _author_settings_context, _base_context, _templates

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/auth/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    error: Optional[str] = Query(None),
):
    """Render login/register page."""
    ctx = await _base_context(request, db)
    if ctx["current_author"]:
        return RedirectResponse("/dashboard", status_code=303)
    ctx["error"] = error
    return _templates(request).TemplateResponse("pages/login.html", ctx)


@router.post("/auth/login-form")
async def login_form(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Handle login form POST. Sets JWT cookie and redirects to dashboard."""
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.hashed_password:
        return RedirectResponse(
            "/auth/login?error=Invalid+email+or+password", status_code=303,
        )

    if not _bcrypt.checkpw(password.encode(), user.hashed_password.encode()):
        return RedirectResponse(
            "/auth/login?error=Invalid+email+or+password", status_code=303,
        )

    if not user.is_active:
        return RedirectResponse(
            "/auth/login?error=Account+is+disabled", status_code=303,
        )

    settings = request.app.state.settings

    # Email verification gate (when feature flag is on)
    if settings.email_verification_required and not user.email_verified:
        return RedirectResponse(
            "/auth/login?error=Please+verify+your+email+before+logging+in."
            "+Check+your+inbox+or+request+a+new+link.",
            status_code=303,
        )

    token = create_access_token(
        data={"sub": user.email, "user_id": user.id, "role": user.role},
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        "aiwn_token",
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=settings.jwt_access_token_expire_minutes * 60,
    )
    logger.info("user_logged_in_form", user_id=user.id)
    return response


@router.post("/auth/register-form")
async def register_form(
    request: Request,
    email: str = Form(...),
    pen_name: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Handle registration form POST. Creates account, sets cookie, redirects."""
    if password != password_confirm:
        return RedirectResponse(
            "/auth/login?error=Passwords+do+not+match", status_code=303,
        )

    if len(password) < 8:
        return RedirectResponse(
            "/auth/login?error=Password+must+be+at+least+8+characters",
            status_code=303,
        )

    # Check email uniqueness
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        return RedirectResponse(
            "/auth/login?error=Email+already+registered", status_code=303,
        )

    # Create user + profile
    settings = request.app.state.settings
    hashed = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    user = User(
        email=email,
        username=pen_name,
        display_name=pen_name,
        hashed_password=hashed,
        auth_provider="local",
        role="author",
        is_active=True,
        is_anonymous=False,
        email_verified=not settings.email_verification_required,
    )
    db.add(user)
    await db.flush()

    profile = AuthorProfile(
        user_id=user.id,
        display_name=pen_name,
        plan_type="free",
        api_budget_cents=settings.free_tier_lifetime_budget_cents,
        image_budget_cents=100,
    )
    db.add(profile)
    await db.flush()

    # If email verification is required, send email and redirect to pending page
    if settings.email_verification_required:
        verification_token = await create_verification(
            db, user, settings.email_verification_expire_minutes,
        )
        base_url = str(request.base_url).rstrip("/")
        await send_verification_email(
            email,
            verification_token,
            base_url,
            resend_api_key=settings.resend_api_key,
            sender=settings.email_sender,
        )
        await db.commit()
        logger.info("user_registered_verification_pending", user_id=user.id)
        return RedirectResponse("/auth/verify-pending", status_code=303)

    # No verification needed — issue JWT immediately
    token = create_access_token(
        data={"sub": user.email, "user_id": user.id, "role": user.role},
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        "aiwn_token",
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=settings.jwt_access_token_expire_minutes * 60,
    )
    logger.info("user_registered_form", user_id=user.id)
    return response


@router.get("/auth/logout")
async def logout_page():
    """Clear JWT cookie and redirect to homepage."""
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("aiwn_token")
    return response


# ---------------------------------------------------------------------------
# Email Verification
# ---------------------------------------------------------------------------


@router.get("/auth/verify-pending", response_class=HTMLResponse)
async def verify_pending_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Show 'check your email' page after registration."""
    ctx = await _base_context(request, db)
    return _templates(request).TemplateResponse(
        "pages/verify_pending.html", ctx,
    )


@router.get("/auth/verify-email/{token}", response_class=HTMLResponse)
async def verify_email(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle email verification link click."""
    ctx = await _base_context(request, db)
    user = await verify_token(db, token)
    if user is None:
        ctx["verified"] = False
        ctx["error"] = (
            "This verification link is invalid or has expired. "
            "Please request a new one."
        )
    else:
        await db.commit()
        ctx["verified"] = True
        ctx["email"] = user.email
        logger.info("email_verified", user_id=user.id)
    return _templates(request).TemplateResponse(
        "pages/verify_result.html", ctx,
    )


@router.post("/auth/resend-verification")
async def resend_verification(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Resend the verification email. Rate limited to prevent abuse."""
    settings = request.app.state.settings

    stmt = select(User).where(User.email == email)
    user = (await db.execute(stmt)).scalar_one_or_none()

    # Always redirect — don't reveal whether email exists
    if user and not user.email_verified:
        verification_token = await create_verification(
            db, user, settings.email_verification_expire_minutes,
        )
        base_url = str(request.base_url).rstrip("/")
        await send_verification_email(
            email,
            verification_token,
            base_url,
            resend_api_key=settings.resend_api_key,
            sender=settings.email_sender,
        )
        await db.commit()
        logger.info("verification_resent", email=email)

    return RedirectResponse("/auth/verify-pending", status_code=303)


# ---------------------------------------------------------------------------
# Author Settings
# ---------------------------------------------------------------------------


@router.get("/dashboard/settings", response_class=HTMLResponse)
async def author_settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Author settings page: profile, password, billing."""
    ctx = await _author_settings_context(request, db)

    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    return _templates(request).TemplateResponse(
        "pages/author_settings.html", ctx,
    )


@router.post("/dashboard/settings", response_class=HTMLResponse)
async def author_settings_update(
    request: Request,
    display_name: str = Form(""),
    bio: str = Form(""),
    email: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    default_image_generation_enabled: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Handle author settings form submission."""
    ctx = await _author_settings_context(request, db)

    if not ctx["current_author"]:
        return RedirectResponse("/auth/login", status_code=303)

    user_id = ctx["current_author"]["user_id"]
    user = ctx["user"]
    profile = ctx["profile"]
    errors: list[str] = []
    success: list[str] = []

    # --- Profile updates ---
    if profile:
        if display_name and display_name != (profile.display_name or ""):
            profile.display_name = display_name[:200]
            success.append("Display name updated.")
        if bio != (profile.bio or ""):
            profile.bio = bio[:2000] if bio else None
            success.append("Bio updated.")
        # Image generation default (checkbox: "1" if checked, "" if not)
        new_img_default = bool(default_image_generation_enabled)
        if new_img_default != profile.default_image_generation_enabled:
            profile.default_image_generation_enabled = new_img_default
            success.append("Image generation default updated.")

    if user and email and email != (user.email or ""):
        # Check uniqueness
        existing = (
            await db.execute(
                select(User).where(User.email == email, User.id != user_id)
            )
        ).scalar_one_or_none()
        if existing:
            errors.append("That email is already in use.")
        else:
            user.email = email
            success.append("Email updated.")

    # --- Password change ---
    if new_password:
        if not current_password:
            errors.append("Current password is required to set a new one.")
        elif not user or not user.hashed_password:
            errors.append("Cannot change password for this account type.")
        elif not _bcrypt.checkpw(
            current_password.encode(), user.hashed_password.encode()
        ):
            errors.append("Current password is incorrect.")
        elif len(new_password) < 8:
            errors.append("New password must be at least 8 characters.")
        elif new_password != confirm_password:
            errors.append("New passwords do not match.")
        else:
            user.hashed_password = _bcrypt.hashpw(
                new_password.encode(), _bcrypt.gensalt()
            ).decode()
            success.append("Password changed.")

    if not errors:
        await db.flush()

    # Re-fetch context so form shows updated values
    if not errors:
        ctx = await _author_settings_context(request, db)

    ctx["errors"] = errors
    ctx["success"] = success

    return _templates(request).TemplateResponse(
        "pages/author_settings.html", ctx,
    )
