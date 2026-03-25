"""Email verification token generation and validation."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import User


def generate_verification_token() -> str:
    """Generate a cryptographically secure 32-byte hex token."""
    return secrets.token_hex(32)


async def create_verification(
    session: AsyncSession,
    user: User,
    expire_minutes: int = 1440,
) -> str:
    """Create a verification token for the user and return it.

    Stores the token and expiry on the User record.
    """
    token = generate_verification_token()
    user.email_verification_token = token
    user.email_verification_token_expires_at = datetime.now(
        tz=UTC
    ).replace(tzinfo=None) + timedelta(minutes=expire_minutes)
    session.add(user)
    await session.flush()
    return token


async def verify_token(
    session: AsyncSession,
    token: str,
) -> User | None:
    """Validate a verification token and activate the user.

    Returns the User if successful, None if token is invalid or expired.
    """
    stmt = select(User).where(User.email_verification_token == token)
    user = (await session.execute(stmt)).scalar_one_or_none()

    if user is None:
        return None

    # Check expiry
    if user.email_verification_token_expires_at is not None:
        now = datetime.now(tz=UTC).replace(tzinfo=None)
        if now > user.email_verification_token_expires_at:
            return None

    # Mark verified
    user.email_verified = True
    user.email_verified_at = datetime.now(tz=UTC).replace(
        tzinfo=None
    )
    user.email_verification_token = None
    user.email_verification_token_expires_at = None
    session.add(user)
    await session.flush()
    return user
