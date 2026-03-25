"""Tests for AIWN 2.0 authentication system."""

from datetime import timedelta

import pytest
from jose import JWTError

from aiwebnovel.auth.jwt import create_access_token, decode_access_token

# ---------------------------------------------------------------------------
# JWT Tests
# ---------------------------------------------------------------------------


class TestJWTCreation:
    """Test JWT token creation."""

    def test_create_token_returns_string(self) -> None:
        token = create_access_token(
            data={"sub": "user@example.com"},
            secret_key="test-secret-key-that-is-long-enough",
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_token_with_custom_expiry(self) -> None:
        token = create_access_token(
            data={"sub": "user@example.com"},
            secret_key="test-secret-key-that-is-long-enough",
            expires_delta=timedelta(minutes=5),
        )
        assert isinstance(token, str)

    def test_create_token_with_additional_claims(self) -> None:
        token = create_access_token(
            data={"sub": "user@example.com", "role": "author", "user_id": 42},
            secret_key="test-secret-key-that-is-long-enough",
        )
        decoded = decode_access_token(
            token=token,
            secret_key="test-secret-key-that-is-long-enough",
        )
        assert decoded["sub"] == "user@example.com"
        assert decoded["role"] == "author"
        assert decoded["user_id"] == 42


class TestJWTDecoding:
    """Test JWT token decoding and validation."""

    def test_decode_valid_token(self) -> None:
        token = create_access_token(
            data={"sub": "user@example.com"},
            secret_key="test-secret-key-that-is-long-enough",
        )
        decoded = decode_access_token(
            token=token,
            secret_key="test-secret-key-that-is-long-enough",
        )
        assert decoded["sub"] == "user@example.com"
        assert "exp" in decoded

    def test_decode_expired_token_raises(self) -> None:
        token = create_access_token(
            data={"sub": "user@example.com"},
            secret_key="test-secret-key-that-is-long-enough",
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(JWTError):
            decode_access_token(
                token=token,
                secret_key="test-secret-key-that-is-long-enough",
            )

    def test_decode_invalid_token_raises(self) -> None:
        with pytest.raises(JWTError):
            decode_access_token(
                token="not.a.valid.jwt.token",
                secret_key="test-secret-key-that-is-long-enough",
            )

    def test_decode_wrong_secret_raises(self) -> None:
        token = create_access_token(
            data={"sub": "user@example.com"},
            secret_key="secret-one",
        )
        with pytest.raises(JWTError):
            decode_access_token(
                token=token,
                secret_key="secret-two",
            )

    def test_decode_tampered_token_raises(self) -> None:
        token = create_access_token(
            data={"sub": "user@example.com"},
            secret_key="test-secret-key-that-is-long-enough",
        )
        # Tamper with the payload
        parts = token.split(".")
        parts[1] = parts[1] + "tampered"
        tampered = ".".join(parts)
        with pytest.raises(JWTError):
            decode_access_token(
                token=tampered,
                secret_key="test-secret-key-that-is-long-enough",
            )


class TestJWTTokenContents:
    """Test that tokens contain expected claims."""

    def test_token_contains_exp_claim(self) -> None:
        token = create_access_token(
            data={"sub": "user@example.com"},
            secret_key="test-secret",
        )
        decoded = decode_access_token(token=token, secret_key="test-secret")
        assert "exp" in decoded

    def test_token_preserves_all_data(self) -> None:
        data = {
            "sub": "user@example.com",
            "user_id": 1,
            "role": "author",
        }
        token = create_access_token(data=data, secret_key="test-secret")
        decoded = decode_access_token(token=token, secret_key="test-secret")
        for key, value in data.items():
            assert decoded[key] == value


# ---------------------------------------------------------------------------
# OAuth Stub Tests
# ---------------------------------------------------------------------------


class TestOAuthStubs:
    """Test that OAuth handlers exist and raise NotImplementedError."""

    def test_google_get_auth_url_raises(self) -> None:
        from aiwebnovel.auth.oauth import GoogleOAuthHandler

        handler = GoogleOAuthHandler()
        with pytest.raises(NotImplementedError):
            handler.get_authorization_url()

    def test_google_handle_callback_raises(self) -> None:
        from aiwebnovel.auth.oauth import GoogleOAuthHandler

        handler = GoogleOAuthHandler()
        with pytest.raises(NotImplementedError):
            handler.handle_callback(code="fake-code")

    def test_github_get_auth_url_raises(self) -> None:
        from aiwebnovel.auth.oauth import GitHubOAuthHandler

        handler = GitHubOAuthHandler()
        with pytest.raises(NotImplementedError):
            handler.get_authorization_url()

    def test_github_handle_callback_raises(self) -> None:
        from aiwebnovel.auth.oauth import GitHubOAuthHandler

        handler = GitHubOAuthHandler()
        with pytest.raises(NotImplementedError):
            handler.handle_callback(code="fake-code")


# ---------------------------------------------------------------------------
# Middleware Tests
# ---------------------------------------------------------------------------


class TestAnonymousReaderMiddleware:
    """Test anonymous reader cookie middleware."""

    def test_middleware_class_exists(self) -> None:
        from aiwebnovel.auth.middleware import AnonymousReaderMiddleware

        assert AnonymousReaderMiddleware is not None

    def test_rate_limit_middleware_class_exists(self) -> None:
        from aiwebnovel.auth.middleware import RateLimitMiddleware

        assert RateLimitMiddleware is not None


# ---------------------------------------------------------------------------
# Auth Bypass Tests (UNM-31) — stale JWT after DB wipe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStaleJWTBypass:
    """Verify that a JWT referencing a non-existent user is rejected at write boundaries."""

    async def _make_lifespan_client(self, test_settings):
        """Create an AsyncClient that runs the app lifespan (DB init)."""
        from contextlib import asynccontextmanager

        from httpx import ASGITransport, AsyncClient

        from aiwebnovel.main import create_app

        app = create_app(settings_override=test_settings)

        @asynccontextmanager
        async def _client():
            transport = ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    yield client

        return _client()

    async def test_novel_creation_rejected_with_nonexistent_user(
        self, test_settings
    ):
        """POST /novels/new with a JWT for user_id=999 (not in DB) should redirect to login."""
        stale_token = create_access_token(
            data={"sub": "ghost@example.com", "user_id": 999, "role": "author"},
            secret_key=test_settings.jwt_secret_key,
        )

        async with await self._make_lifespan_client(test_settings) as client:
            csrf = "test-csrf-token"
            resp = await client.post(
                "/novels/new",
                data={
                    "title": "Exploit Novel",
                    "genre": "progression_fantasy",
                    "csrf_token": csrf,
                },
                cookies={"aiwn_token": stale_token, "csrf_token": csrf},
                follow_redirects=False,
            )
            # Should redirect to login (302/303), NOT create a novel
            assert resp.status_code in (302, 303)
            assert "/auth/login" in resp.headers.get("location", "")

    async def test_novel_creation_rejected_user_exists_but_no_profile(
        self, test_settings
    ):
        """User row exists but no AuthorProfile → should redirect to settings."""
        from aiwebnovel.db.models import User
        from aiwebnovel.db.session import get_db

        async with await self._make_lifespan_client(test_settings) as client:
            # Insert a User row (but no AuthorProfile) via the app's DB session
            async for db in get_db():
                user = User(
                    id=500,
                    email="noprofile@example.com",
                    role="author",
                    auth_provider="local",
                    is_active=True,
                    is_anonymous=False,
                )
                db.add(user)
                await db.flush()
                break  # get_db is a generator; we only need one session

            stale_token = create_access_token(
                data={
                    "sub": "noprofile@example.com",
                    "user_id": 500,
                    "role": "author",
                },
                secret_key=test_settings.jwt_secret_key,
            )

            csrf = "test-csrf-token"
            resp = await client.post(
                "/novels/new",
                data={
                    "title": "No Profile Novel",
                    "genre": "progression_fantasy",
                    "csrf_token": csrf,
                },
                cookies={"aiwn_token": stale_token, "csrf_token": csrf},
                follow_redirects=False,
            )
            assert resp.status_code in (302, 303)
            location = resp.headers.get("location", "")
            # Should redirect to settings or login, NOT create the novel
            assert "/auth/login" in location or "/dashboard/settings" in location
