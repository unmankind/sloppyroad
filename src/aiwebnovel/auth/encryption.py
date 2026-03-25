"""Fernet-based encryption for storing user API keys at rest.

Keys are encrypted before DB write and decrypted only at the moment of use.
The encryption key comes from AIWN_ENCRYPTION_KEY environment variable.
"""

from __future__ import annotations

import re

from cryptography.fernet import Fernet

_fernet: Fernet | None = None


def _get_fernet(encryption_key: str) -> Fernet:
    """Return a cached Fernet instance for the given key."""
    global _fernet  # noqa: PLW0603
    if _fernet is None:
        if not encryption_key:
            raise RuntimeError(
                "AIWN_ENCRYPTION_KEY is not set. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        _fernet = Fernet(encryption_key.encode())
    return _fernet


def encrypt_api_key(plaintext: str, encryption_key: str) -> str:
    """Encrypt an API key and return base64-encoded ciphertext."""
    f = _get_fernet(encryption_key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str, encryption_key: str) -> str:
    """Decrypt an API key from base64-encoded ciphertext.

    Raises ``InvalidToken`` if the ciphertext is corrupt or the key is wrong.
    """
    f = _get_fernet(encryption_key)
    return f.decrypt(ciphertext.encode()).decode()


def mask_api_key(plaintext: str) -> str:
    """Return a masked version of the key showing only the last 4 chars.

    Example: "sk-ant-api03-abc123xyz" → "...xyz"
    """
    if len(plaintext) <= 4:
        return "..." + plaintext
    return "..." + plaintext[-4:]


def extract_key_suffix(plaintext: str) -> str:
    """Extract the last 4 characters for storage as key_suffix."""
    return plaintext[-4:] if len(plaintext) >= 4 else plaintext


# ── Key format validation ──────────────────────────────────────────────────

_KEY_PATTERNS: dict[str, re.Pattern[str]] = {
    "anthropic": re.compile(r"^sk-ant-"),
    "openai": re.compile(r"^sk-"),
    "replicate": re.compile(r"^r8_"),
}


def validate_key_format(provider: str, api_key: str) -> tuple[bool, str]:
    """Validate that a key matches expected format for its provider.

    Returns (is_valid, error_message).
    """
    if not api_key or len(api_key) > 256:
        return False, "API key must be between 1 and 256 characters"

    if any(c.isspace() or ord(c) < 32 for c in api_key):
        return False, "API key must not contain whitespace or control characters"

    pattern = _KEY_PATTERNS.get(provider)
    if pattern and not pattern.match(api_key):
        prefixes = {
            "anthropic": "sk-ant-",
            "openai": "sk-",
            "replicate": "r8_",
        }
        return False, f"{provider.title()} keys should start with '{prefixes[provider]}'"

    return True, ""


ALLOWED_PROVIDERS = frozenset({"anthropic", "openai", "replicate"})


def validate_provider(provider: str) -> tuple[bool, str]:
    """Validate that provider is one of the allowed values."""
    if provider not in ALLOWED_PROVIDERS:
        return False, f"Provider must be one of: {', '.join(sorted(ALLOWED_PROVIDERS))}"
    return True, ""
