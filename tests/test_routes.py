"""Tests for AIWN 2.0 API routes.

Tests key endpoints across all route modules. Uses the shared conftest
fixtures (test_settings, test_client, auth_headers) and mocks external
dependencies (Redis, StoryPipeline).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from aiwebnovel.auth.jwt import create_access_token
from aiwebnovel.config import Settings

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def test_settings() -> Settings:
    """Settings override for route tests — in-memory SQLite, test JWT."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key-for-testing-only",
        debug=True,
        log_level="DEBUG",
        email_verification_required=False,  # tests bypass email verification
    )


@pytest.fixture()
async def client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient wired to the FastAPI test app with lifespan."""

    from aiwebnovel.main import create_app

    app = create_app(settings_override=test_settings)

    # Manually trigger lifespan so DB engine + tables are created
    async with app.router.lifespan_context(app):
        # Flush rate limit keys so tests aren't blocked by stale counters
        redis = getattr(app.state, "redis", None)
        if redis is not None:
            keys = await redis.keys("ratelimit:*")
            if keys:
                await redis.delete(*keys)

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


@pytest.fixture()
def author_headers(test_settings: Settings) -> dict[str, str]:
    """JWT auth headers for a test author (user_id=1)."""
    token = create_access_token(
        data={"sub": "author@test.com", "user_id": 1, "role": "author"},
        secret_key=test_settings.jwt_secret_key,
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def reader_headers(test_settings: Settings) -> dict[str, str]:
    """JWT auth headers for a test reader (user_id=2, role=reader)."""
    token = create_access_token(
        data={"sub": "reader@test.com", "user_id": 2, "role": "reader"},
        secret_key=test_settings.jwt_secret_key,
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


# ── Helpers ───────────────────────────────────────────────────────────────


async def _register_user(
    client: AsyncClient,
    email: str = "newuser@test.com",
    password: str = "securepass123",
    username: str = "testauthor",
) -> dict:
    """Register a user and return the response JSON."""
    resp = await client.post("/auth/register", json={
        "email": email,
        "password": password,
        "username": username,
    })
    return resp


async def _create_novel(
    client: AsyncClient,
    headers: dict[str, str],
    title: str = "Test Novel",
) -> dict:
    """Create a novel and return the response JSON."""
    resp = await client.post("/api/novels/", json={
        "title": title,
        "genre": "progression_fantasy",
    }, headers=headers)
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthCheck:
    """Test /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self, test_settings: Settings) -> None:
        """Health check should return 200 with subsystem metrics when all are healthy."""
        from unittest.mock import AsyncMock

        from aiwebnovel.main import create_app

        app = create_app(settings_override=test_settings)

        async with app.router.lifespan_context(app):
            # Mock Redis so health check exercises the full code path
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_redis.info = AsyncMock(return_value={"used_memory": 10_000_000})
            mock_redis.zcard = AsyncMock(return_value=0)
            app.state.redis = mock_redis

            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://testserver") as c:
                resp = await c.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        # DB subsystem
        assert data["db"]["status"] == "connected"
        assert "response_ms" in data["db"]
        # Redis subsystem
        assert data["redis"]["status"] == "connected"
        assert "used_memory_mb" in data["redis"]
        assert data["redis"]["pending_jobs_main"] == 0
        assert data["redis"]["pending_jobs_images"] == 0
        # Workers subsystem
        assert data["workers"]["status"] == "ok"
        assert "running_jobs" in data["workers"]
        # Cost metrics
        assert "costs_24h" in data

    @pytest.mark.asyncio
    async def test_health_check_503_when_db_down(self, test_settings: Settings) -> None:
        """Health check should return 503 when DB is unreachable."""
        from unittest.mock import AsyncMock, MagicMock

        from aiwebnovel.main import create_app

        app = create_app(settings_override=test_settings)

        async with app.router.lifespan_context(app):
            # Sabotage the DB engine so the SELECT 1 fails
            mock_engine = MagicMock()
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(side_effect=RuntimeError("connection refused"))
            mock_engine.connect = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_conn),
                    __aexit__=AsyncMock(return_value=False),
                ),
            )
            mock_engine.pool = MagicMock(
                size=MagicMock(return_value=0),
                checkedout=MagicMock(return_value=0),
                overflow=MagicMock(return_value=0),
            )
            app.state.db_engine = mock_engine
            app.state.redis = None  # No Redis either

            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://testserver") as c:
                resp = await c.get("/health")

        assert resp.status_code == 503
        data = resp.json()
        assert data["db"]["status"] == "error"


class TestAuthRoutes:
    """Test /auth/* endpoints."""

    @pytest.mark.asyncio
    async def test_register(self, client: AsyncClient) -> None:
        resp = await _register_user(client)
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient) -> None:
        await _register_user(client, email="dup@test.com")
        resp = await _register_user(client, email="dup@test.com")
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_login(self, client: AsyncClient) -> None:
        # First register
        await _register_user(client, email="login@test.com", password="securepass123")
        # Then login
        resp = await client.post("/auth/login", json={
            "email": "login@test.com",
            "password": "securepass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient) -> None:
        await _register_user(client, email="wrong@test.com", password="securepass123")
        resp = await client.post("/auth/login", json={
            "email": "wrong@test.com",
            "password": "badpassword",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_logout(self, client: AsyncClient) -> None:
        resp = await client.post("/auth/logout")
        assert resp.status_code == 200
        assert "Logged out" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_oauth_not_implemented(self, client: AsyncClient) -> None:
        resp = await client.get("/auth/oauth/google")
        assert resp.status_code == 501


class TestNovelRoutes:
    """Test /novels/* endpoints."""

    @pytest.mark.asyncio
    async def test_create_novel_authenticated(self, client: AsyncClient) -> None:
        # Register to get a valid token backed by a real DB user
        reg_resp = await _register_user(client, email="novelist@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await _create_novel(client, headers, title="My Fantasy Novel")
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Fantasy Novel"
        assert data["genre"] == "progression_fantasy"
        assert "share_token" in data

    @pytest.mark.asyncio
    async def test_create_novel_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.post("/api/novels/", json={
            "title": "Unauthorized Novel",
            "genre": "progression_fantasy",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_novels(self, client: AsyncClient) -> None:
        resp = await client.get("/api/novels/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_novel(self, client: AsyncClient) -> None:
        # Register and create novel
        reg_resp = await _register_user(client, email="detail@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        # Novel defaults to is_public=False so auth is required to view it
        resp = await client.get(f"/api/novels/{novel_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == novel_id


class TestChapterRoutes:
    """Test chapter-related endpoints."""

    @pytest.mark.asyncio
    async def test_list_chapters_empty(self, client: AsyncClient) -> None:
        # Register and create novel
        reg_resp = await _register_user(client, email="chapters@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        resp = await client.get(f"/api/novels/{novel_id}/chapters")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_chapter_not_found(self, client: AsyncClient) -> None:
        reg_resp = await _register_user(client, email="nochapter@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        resp = await client.get(f"/api/novels/{novel_id}/chapters/999")
        assert resp.status_code == 404


class TestBrowseRoutes:
    """Test /browse/* public endpoints."""

    @pytest.mark.asyncio
    async def test_browse_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/browse/")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_browse_with_sort(self, client: AsyncClient) -> None:
        resp = await client.get("/api/browse/?sort=newest")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_leaderboard(self, client: AsyncClient) -> None:
        resp = await client.get("/api/browse/leaderboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "most_read" in data
        assert "highest_rated" in data


class TestNotificationRoutes:
    """Test /api/notifications/* endpoints."""

    @pytest.mark.asyncio
    async def test_notifications_require_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/notifications/")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_notifications(self, client: AsyncClient) -> None:
        reg_resp = await _register_user(client, email="notify@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get("/api/notifications/", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_mark_all_read(self, client: AsyncClient) -> None:
        reg_resp = await _register_user(client, email="readall@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.patch("/api/notifications/read-all", headers=headers)
        assert resp.status_code == 200
        assert "count" in resp.json()


class TestRatingRoutes:
    """Test novel rating."""

    @pytest.mark.asyncio
    async def test_rate_novel(self, client: AsyncClient) -> None:
        # Register and create a public novel
        reg_resp = await _register_user(client, email="rater@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        resp = await client.post(f"/api/browse/{novel_id}/rate", json={
            "novel_id": novel_id,
            "rating": 5,
            "review_text": "Excellent progression fantasy!",
        }, headers=headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["rating"] == 5

    @pytest.mark.asyncio
    async def test_rate_novel_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.post("/api/browse/1/rate", json={
            "novel_id": 1,
            "rating": 5,
        })
        assert resp.status_code == 401


class TestOracleRoutes:
    """Test reader influence Oracle endpoint."""

    @pytest.mark.asyncio
    async def test_oracle_submit(self, client: AsyncClient) -> None:
        # Register author and create novel
        reg_resp = await _register_user(client, email="oracle@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        resp = await client.post(f"/novels/{novel_id}/oracle", json={
            "question_text": "Will the protagonist discover the hidden realm?",
        }, headers=headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "queued"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_oracle_status(self, client: AsyncClient) -> None:
        reg_resp = await _register_user(client, email="orstatus@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        resp = await client.get(f"/novels/{novel_id}/oracle/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_questions" in data


class TestStreamRoute:
    """Test SSE streaming endpoint."""

    @pytest.mark.asyncio
    async def test_stream_endpoint_exists(self, client: AsyncClient) -> None:
        """Verify the SSE stream endpoint is registered and requires auth.

        The stream endpoint requires authentication and a valid job_id.
        Without auth it returns 401; with auth but a non-existent job it
        returns 404.  Either proves the endpoint is registered at
        /api/stream/{job_id}.
        """
        # Without auth → 401
        resp = await client.get(
            "/api/stream/999",
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 401

        # With auth but non-existent job → 404
        reg_resp = await _register_user(client, email="stream@test.com")
        token = reg_resp.json()["access_token"]
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        }
        resp = await client.get("/api/stream/999", headers=headers)
        assert resp.status_code == 404


class TestWorldRoutes:
    """Test world-building routes.

    The page router (registered first) shadows the JSON API router on
    /novels/{id}/world, so authenticated requests hit the page route and
    return HTML.  The regions endpoint is only on the API router and
    still returns JSON.
    """

    @pytest.mark.asyncio
    async def test_world_overview(self, client: AsyncClient) -> None:
        reg_resp = await _register_user(client, email="world@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        # Page route takes priority — returns HTML 200 when authenticated
        resp = await client.get(f"/novels/{novel_id}/world", headers=headers)
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type

    @pytest.mark.asyncio
    async def test_list_regions_empty(self, client: AsyncClient) -> None:
        reg_resp = await _register_user(client, email="regions@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        resp = await client.get(f"/novels/{novel_id}/world/regions")
        assert resp.status_code == 200
        assert resp.json() == []


class TestCharacterRoutes:
    """Test character routes.

    The page router (registered first) shadows the JSON API router on
    /novels/{id}/characters, so authenticated requests hit the page route
    and return HTML.  The relationships endpoint is only on the API
    router and still returns JSON.
    """

    @pytest.mark.asyncio
    async def test_list_characters_empty(self, client: AsyncClient) -> None:
        reg_resp = await _register_user(client, email="chars@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        # Page route takes priority — returns HTML 200 when authenticated
        resp = await client.get(f"/novels/{novel_id}/characters", headers=headers)
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type

    @pytest.mark.asyncio
    async def test_relationships_empty(self, client: AsyncClient) -> None:
        reg_resp = await _register_user(client, email="rels@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await _create_novel(client, headers)
        novel_id = create_resp.json()["id"]

        resp = await client.get(f"/novels/{novel_id}/relationships")
        assert resp.status_code == 200
        data = resp.json()
        assert data["relationships"] == []
        assert data["characters"] == []


class TestDashboardRoutes:
    """Test /dashboard/* endpoints."""

    @pytest.mark.asyncio
    async def test_dashboard_requires_author(self, client: AsyncClient) -> None:
        resp = await client.get("/api/dashboard/")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_dashboard(self, client: AsyncClient) -> None:
        reg_resp = await _register_user(client, email="dash@test.com")
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get("/api/dashboard/", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "novels" in data
        assert "novel_count" in data
        assert data["novel_count"] == 0
