"""Security-focused tests for AIWN 2.0 (UNM-98).

Covers:
- CSRF token validation (double-submit cookie)
- Rate limiting (Redis sliding window, 429 + Retry-After)
- Auth bypass attempts (expired/malformed tokens, role escalation, cross-tenant)
- Input validation (length limits, type coercion, XSS escaping)
"""

import secrets
from collections.abc import AsyncGenerator
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from aiwebnovel.auth.jwt import create_access_token
from aiwebnovel.config import Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key-for-testing-only",
        debug=True,
        log_level="DEBUG",
        email_verification_required=False,
    )


@pytest.fixture()
async def client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    """httpx client with lifespan (DB initialised, raise_app_exceptions=False)."""
    from aiwebnovel.main import create_app

    app = create_app(settings_override=test_settings)

    async with app.router.lifespan_context(app):
        # Clear rate limit keys if Redis is available
        redis = getattr(app.state, "redis", None)
        if redis is not None:
            keys = await redis.keys("ratelimit:*")
            if keys:
                await redis.delete(*keys)

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        ) as c:
            yield c


def _auth_headers(settings: Settings, **overrides) -> dict[str, str]:
    data = {"sub": "testuser@example.com", "user_id": 1, "role": "author"}
    data.update(overrides)
    token = create_access_token(
        data=data,
        secret_key=settings.jwt_secret_key,
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# CSRF Tests
# ---------------------------------------------------------------------------


class TestCsrf:
    @pytest.mark.asyncio
    async def test_form_post_without_csrf_cookie_returns_403(
        self, client: AsyncClient
    ):
        """POST with form content-type but no csrf_token cookie → 403."""
        resp = await client.post(
            "/auth/login-form",
            data={"email": "a@b.com", "password": "secret"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_form_post_with_wrong_csrf_token_returns_403(
        self, client: AsyncClient
    ):
        """POST with mismatched cookie/form csrf_token → 403."""
        resp = await client.post(
            "/auth/login-form",
            data={
                "email": "a@b.com",
                "password": "secret",
                "csrf_token": "wrong-token",
            },
            cookies={"csrf_token": secrets.token_hex(32)},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_form_post_with_valid_csrf_token_succeeds(
        self, client: AsyncClient
    ):
        """POST with matching cookie + form csrf_token passes CSRF check.

        The request may still fail downstream (e.g. 422 from Pydantic if the
        endpoint expects JSON), but it must NOT be a 403 CSRF rejection.
        """
        token = secrets.token_hex(32)
        resp = await client.post(
            "/auth/register",
            data={
                "email": "csrfok@test.com",
                "password": "securepass123",
                "username": "csrfokuser",
                "csrf_token": token,
            },
            cookies={"csrf_token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_json_post_bypasses_csrf(self, client: AsyncClient):
        """JSON content-type POST should not require CSRF (CORS-gated)."""
        resp = await client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpassword"},
        )
        # Should reach the handler (not blocked by CSRF) — expect 401, not 403
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Auth Tests
# ---------------------------------------------------------------------------


class TestAuth:
    @pytest.mark.asyncio
    async def test_malformed_token_returns_401(self, client: AsyncClient):
        """Garbage JWT token → 401."""
        resp = await client.get(
            "/api/dashboard/",
            headers={"Authorization": "Bearer not-a-real-jwt-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self, client: AsyncClient):
        """No token at all on protected endpoint → 401."""
        resp = await client.get("/api/dashboard/")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(
        self, test_settings: Settings, client: AsyncClient
    ):
        """Token with negative expiry (already expired) → 401."""
        token = create_access_token(
            data={"sub": "user@example.com", "user_id": 1, "role": "author"},
            secret_key=test_settings.jwt_secret_key,
            expires_delta=timedelta(seconds=-1),
        )
        resp = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_secret_returns_401(self, client: AsyncClient):
        """JWT signed with the wrong secret → 401."""
        token = create_access_token(
            data={"sub": "hacker@test.com", "user_id": 1, "role": "author"},
            secret_key="wrong-secret-key-not-the-real-one",
        )
        resp = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_reader_cannot_access_author_routes(
        self, test_settings: Settings, client: AsyncClient
    ):
        """A reader-role JWT cannot create novels (require_db_author checks role)."""
        resp = await client.post(
            "/api/novels/",
            json={"title": "Reader Should Not Create"},
            headers=_auth_headers(test_settings, role="reader", user_id=99,
                                  sub="reader@test.com"),
        )
        # require_db_author rejects non-author role with 401
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_author_cannot_access_other_authors_novels(
        self, client: AsyncClient
    ):
        """An author must not be able to read another author's novel settings."""
        # Register author 1 and create a novel
        reg1 = await client.post("/auth/register", json={
            "email": "author1@test.com",
            "password": "securepass123",
            "username": "authorone",
        })
        assert reg1.status_code == 201
        headers1 = {"Authorization": f"Bearer {reg1.json()['access_token']}"}

        novel_resp = await client.post(
            "/api/novels/",
            json={"title": "Author1 Novel"},
            headers=headers1,
        )
        assert novel_resp.status_code == 201
        novel_id = novel_resp.json()["id"]

        # Register author 2
        reg2 = await client.post("/auth/register", json={
            "email": "author2@test.com",
            "password": "securepass123",
            "username": "authortwo",
        })
        assert reg2.status_code == 201
        headers2 = {"Authorization": f"Bearer {reg2.json()['access_token']}"}

        # Author 2 tries to read author 1's novel settings
        resp = await client.get(
            f"/api/novels/{novel_id}/settings",
            headers=headers2,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_token_missing_sub_claim_returns_401(
        self, test_settings: Settings, client: AsyncClient
    ):
        """JWT without a 'sub' claim → 401."""
        token = create_access_token(
            data={"user_id": 1, "role": "author"},  # no "sub" key
            secret_key=test_settings.jwt_secret_key,
        )
        resp = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_novel_title_max_length_rejected(self, client: AsyncClient):
        """Title exceeding schema max_length (500) should be rejected."""
        # Register a real user so require_db_author passes
        reg = await client.post("/auth/register", json={
            "email": "titletest@test.com",
            "password": "securepass123",
            "username": "titletest",
        })
        assert reg.status_code == 201
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

        resp = await client.post(
            "/api/novels/",
            json={"title": "A" * 501},
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rating_non_numeric_graceful(
        self, test_settings: Settings, client: AsyncClient
    ):
        """Non-numeric rating should not cause a 500."""
        resp = await client.post(
            "/api/browse/999/rate",
            json={"novel_id": 999, "rating": "abc"},
            headers=_auth_headers(test_settings),
        )
        assert resp.status_code != 500
        # Expect 422 (validation error) from Pydantic
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_xss_in_title_is_escaped(
        self, test_settings: Settings, client: AsyncClient
    ):
        """<script> in title must be returned as data, not rendered as HTML."""
        # First register an author so require_db_author passes
        reg = await client.post(
            "/auth/register",
            json={
                "email": "xssauthor@test.com",
                "password": "securepass123",
                "username": "xssauthor",
            },
        )
        assert reg.status_code == 201
        author_token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {author_token}"}

        xss_title = '<script>alert("xss")</script>My Novel'
        resp = await client.post(
            "/api/novels/",
            json={"title": xss_title},
            headers=headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        # Title stored verbatim but served as JSON (not text/html)
        assert body["title"] == xss_title
        assert "application/json" in resp.headers.get("content-type", "")

        # Detail endpoint also returns safe JSON (auth required — novel is private)
        detail = await client.get(f"/api/novels/{body['id']}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["title"] == xss_title
        assert "application/json" in detail.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_register_password_too_short(self, client: AsyncClient):
        """Password under 8 chars should be rejected."""
        resp = await client.post(
            "/auth/register",
            json={
                "email": "short@test.com",
                "password": "short",
                "username": "shortpass",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        """Invalid email format should be rejected."""
        resp = await client.post(
            "/auth/register",
            json={
                "email": "not-an-email",
                "password": "securepass123",
                "username": "bademail",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rating_out_of_range_rejected(
        self, test_settings: Settings, client: AsyncClient
    ):
        """Rating outside 1-5 range should be rejected."""
        headers = _auth_headers(test_settings)
        resp = await client.post(
            "/api/browse/999/rate",
            json={"novel_id": 999, "rating": 0},
            headers=headers,
        )
        assert resp.status_code == 422

        resp = await client.post(
            "/api/browse/999/rate",
            json={"novel_id": 999, "rating": 6},
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_pagination_invalid_page_rejected(
        self, client: AsyncClient
    ):
        """Page < 1 should be rejected."""
        resp = await client.get("/api/browse/?page=0")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_pagination_excessive_per_page_rejected(
        self, client: AsyncClient
    ):
        """per_page > 100 should be rejected."""
        resp = await client.get("/api/browse/?per_page=101")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Rate Limiting Tests (mock Redis)
# ---------------------------------------------------------------------------


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_returns_429_with_retry_after(
        self, test_settings: Settings
    ):
        """Mock Redis to simulate exceeded limit → 429 + Retry-After."""
        from aiwebnovel.main import create_app

        # Rate limiting is bypassed in debug mode, so use debug=False
        rl_settings = Settings(
            database_url=test_settings.database_url,
            redis_url=test_settings.redis_url,
            jwt_secret_key=test_settings.jwt_secret_key,
            debug=False,
            log_level="DEBUG",
        )
        app = create_app(settings_override=rl_settings)

        # Mock Redis: incr returns count > limit, ttl returns remaining seconds
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=999)
        mock_redis.expire = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=42)
        mock_redis.ping = AsyncMock()
        mock_redis.close = AsyncMock()

        app.state.redis = mock_redis

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.get("/api/dashboard/")

        assert resp.status_code == 429
        assert resp.headers.get("retry-after") == "42"

    @pytest.mark.asyncio
    async def test_rate_limit_different_tiers(self, test_settings: Settings):
        """Verify tier classification maps paths correctly and limits differ."""
        from aiwebnovel.auth.middleware import RateLimitMiddleware

        # Auth tier requires POST method (login/register are mutations)
        assert RateLimitMiddleware._classify_tier("/auth/login", "POST") == "auth"
        assert RateLimitMiddleware._classify_tier("/api/auth/register", "POST") == "auth"
        # Generation tier also requires POST
        assert RateLimitMiddleware._classify_tier("/api/novels/1/generate", "POST") == "generation"
        # All /api/* paths classify as "api" tier (including /api/browse)
        assert RateLimitMiddleware._classify_tier("/api/browse") == "api"
        assert RateLimitMiddleware._classify_tier("/api/browse/leaderboard") == "api"
        assert RateLimitMiddleware._classify_tier("/api/novels/") == "api"
        assert RateLimitMiddleware._classify_tier("/api/dashboard") == "api"
        # Non-/api/ HTML page paths classify as "browse" tier
        assert RateLimitMiddleware._classify_tier("/auth/login") == "browse"
        assert RateLimitMiddleware._classify_tier("/novels/1/world") == "browse"

        # Configured limits differ per tier — auth and generation are most restrictive
        assert test_settings.rate_limit_auth < test_settings.rate_limit_api
        assert test_settings.rate_limit_auth <= test_settings.rate_limit_generation
        assert test_settings.rate_limit_generation < test_settings.rate_limit_browse

    @pytest.mark.asyncio
    async def test_rate_limit_graceful_without_redis(
        self, test_settings: Settings
    ):
        """When Redis is None, requests pass through (no 429)."""
        from aiwebnovel.main import create_app

        app = create_app(settings_override=test_settings)
        app.state.redis = None

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.get("/health")

        assert resp.status_code != 429
