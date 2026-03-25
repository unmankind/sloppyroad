"""FastAPI authentication dependencies.

Provides dependency injection for:
- Extracting authenticated users from JWT tokens
- Role-based access control (author role)
- Novel ownership verification
- Anonymous reader creation/retrieval from cookies
- DB-validated author dependency for write routes
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import TYPE_CHECKING

import structlog
from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.jwt import decode_access_token
from aiwebnovel.db.session import get_db

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


@lru_cache(maxsize=1)
def _get_settings():
    """Lazy import to avoid circular imports at module level.

    Cached so the fallback path only constructs Settings once.
    """
    from aiwebnovel.config import Settings

    return Settings()


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
):
    """Extract and validate the current user from a JWT bearer token or cookie.

    Returns a dict with user claims. When BEDROCK delivers the User model,
    this will be upgraded to return a proper User ORM instance.

    Raises:
        HTTPException 401: If token is missing, invalid, or expired.
    """
    # Fall back to cookie (browser sessions) if no bearer token
    if token is None:
        token = request.cookies.get("aiwn_token")
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Prefer settings from app state (set during create_app); fall back to env
    settings = getattr(request.app.state, "settings", None) or _get_settings()

    try:
        payload = decode_access_token(
            token=token,
            secret_key=settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
    except JWTError as exc:
        logger.warning("jwt_decode_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def require_author(
    user: dict = Depends(get_current_user),
) -> dict:
    """Ensure the current user has the 'author' role.

    Raises:
        HTTPException 403: If user does not have author role.
    """
    role = user.get("role")
    if role != "author":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Author role required",
        )
    return user


async def get_optional_user(request: Request) -> dict | None:
    """Extract user from JWT cookie or Bearer token without raising.

    Returns the decoded JWT payload dict, or None if not authenticated.
    Used by page routes where anonymous access is allowed.
    """
    # Check cookie first (browser sessions)
    token = request.cookies.get("aiwn_token")
    # Fall back to Authorization header (API clients)
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        return None
    try:
        settings = getattr(request.app.state, "settings", None) or _get_settings()
        return decode_access_token(
            token=token,
            secret_key=settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
    except Exception:  # Intentional broad catch: get_optional_user returns None on any auth failure
        return None


async def require_db_author(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Strict auth dependency for write routes: validates User + AuthorProfile exist in DB.

    Use this on mutation endpoints (novel creation, world gen, chapter gen)
    instead of get_optional_user, which only validates the JWT.

    Returns:
        Original JWT claims enriched with author_profile_id.

    Raises:
        HTTPException 401: If not authenticated or user no longer exists in DB.
        HTTPException 403: If user exists but has no AuthorProfile (incomplete registration).
    """
    from aiwebnovel.db.models import AuthorProfile, User

    user_claims = await get_optional_user(request)
    if not user_claims or user_claims.get("role") != "author":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user_id = user_claims.get("user_id")

    # Verify the User row actually exists in the DB
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()
    if db_user is None:
        logger.warning("stale_jwt_user_missing", user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists — please log in again",
        )

    # Verify AuthorProfile exists
    result = await db.execute(
        select(AuthorProfile).where(AuthorProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        logger.warning("author_profile_missing", user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Author profile not found — please complete registration",
        )

    return {**user_claims, "author_profile_id": profile.id}


async def require_novel_owner(
    novel_id: int,
    user: dict = Depends(require_db_author),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify the authenticated author owns the specified novel.

    Uses require_db_author so the user + author profile are DB-validated.

    Raises:
        HTTPException 403: If user does not own the novel.
        HTTPException 404: If novel does not exist.
    """
    from aiwebnovel.db.models import Novel

    result = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = result.scalar_one_or_none()
    if novel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Novel not found",
        )
    if novel.author_id != user.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this novel",
        )
    return user


async def get_or_create_anonymous_reader(
    request: Request,
    aiwn_reader_id: str | None = Cookie(default=None),
) -> dict:
    """Get or create an anonymous reader from cookie.

    If no reader cookie exists, generates a new UUID. The middleware
    will set the cookie on the response.

    When BEDROCK delivers models, this will create/retrieve a ReaderProfile
    from the database.

    Returns:
        Dict with reader_id (UUID string).
    """
    if aiwn_reader_id:
        reader_id = aiwn_reader_id
    else:
        reader_id = str(uuid.uuid4())
        # Store in request state so middleware can set cookie on response
        request.state.new_reader_id = reader_id

    return {"reader_id": reader_id}
