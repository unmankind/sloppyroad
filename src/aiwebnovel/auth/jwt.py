"""JWT token creation and validation.

Uses python-jose with HS256 algorithm for signing.
Secret key MUST come from config/environment — never hardcoded.
"""

from datetime import datetime, timedelta, timezone

from jose import jwt

# Default expiry if none specified
DEFAULT_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def create_access_token(
    data: dict,
    secret_key: str,
    algorithm: str = "HS256",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token.

    Args:
        data: Claims to encode in the token (must include "sub").
        secret_key: Secret key for signing.
        algorithm: JWT algorithm (default HS256).
        expires_delta: Custom expiry duration. Defaults to 24 hours.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)

    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=DEFAULT_TOKEN_EXPIRE_MINUTES)

    to_encode["exp"] = expire
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)


def decode_access_token(
    token: str,
    secret_key: str,
    algorithm: str = "HS256",
) -> dict:
    """Decode and validate a JWT access token.

    Args:
        token: The JWT string to decode.
        secret_key: Secret key used for signing.
        algorithm: JWT algorithm (default HS256).

    Returns:
        Decoded claims dictionary.

    Raises:
        jose.JWTError: If the token is invalid, expired, or tampered with.
    """
    return jwt.decode(token, secret_key, algorithms=[algorithm])
