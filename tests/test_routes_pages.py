"""Smoke tests for HTML page endpoints in routes_pages.py.

Covers homepage, auth pages, dashboard, browse, novel detail, chapter reading,
world overview, settings, and share link — verifying correct HTTP status codes
and redirect behaviour for both anonymous and authenticated users.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from aiwebnovel.config import Settings

# ── Fixtures ──────────────────────────────────────────────────────────────


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
    """httpx client wired to the FastAPI app with lifespan (DB tables created)."""
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


# ── Helpers ───────────────────────────────────────────────────────────────


async def _register(
    client: AsyncClient,
    email: str = "pagetest@test.com",
    password: str = "securepass123",
    username: str = "pagetester",
) -> tuple[str, dict[str, str]]:
    """Register a user via API, return (token, headers_dict)."""
    resp = await client.post("/auth/register", json={
        "email": email,
        "password": password,
        "username": username,
    })
    assert resp.status_code == 201, f"Registration failed: {resp.text}"
    token = resp.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


async def _create_novel(
    client: AsyncClient,
    headers: dict[str, str],
    title: str = "Test Novel",
) -> int:
    """Create a novel via API, return novel_id."""
    resp = await client.post("/api/novels/", json={
        "title": title,
        "genre": "progression_fantasy",
    }, headers=headers)
    assert resp.status_code == 201, f"Novel creation failed: {resp.text}"
    return resp.json()["id"]


def _auth_cookies(token: str) -> dict[str, str]:
    """Build cookie dict for browser-style auth."""
    return {"aiwn_token": token}


# ═══════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestHomepage:
    """GET / — public landing page."""

    @pytest.mark.asyncio
    async def test_homepage_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/", headers={"Accept": "text/html"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_homepage_authenticated(self, client: AsyncClient) -> None:
        token, _ = await _register(client, email="home@test.com")
        resp = await client.get(
            "/",
            headers={"Accept": "text/html"},
            cookies=_auth_cookies(token),
        )
        assert resp.status_code == 200


class TestAuthPages:
    """Auth page routes: login, register-form, logout."""

    @pytest.mark.asyncio
    async def test_login_page(self, client: AsyncClient) -> None:
        resp = await client.get("/auth/login", headers={"Accept": "text/html"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_login_page_redirects_when_authed(self, client: AsyncClient) -> None:
        token, _ = await _register(client, email="loginredir@test.com")
        resp = await client.get(
            "/auth/login",
            cookies=_auth_cookies(token),
        )
        assert resp.status_code == 303
        assert "/dashboard" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_login_form_bad_credentials(self, client: AsyncClient) -> None:
        """POST /auth/login-form with wrong password → 303 redirect to login with error."""
        await _register(client, email="loginform@test.com", password="securepass123")

        # Need a CSRF cookie for form POST
        csrf_token = secrets.token_hex(32)
        resp = await client.post(
            "/auth/login-form",
            data={
                "email": "loginform@test.com",
                "password": "wrongpassword",
                "csrf_token": csrf_token,
            },
            cookies={"csrf_token": csrf_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 303
        assert "error" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_login_form_success(self, client: AsyncClient) -> None:
        """POST /auth/login-form with correct creds → 303 redirect to dashboard."""
        await _register(client, email="loginsuccess@test.com", password="securepass123")

        csrf_token = secrets.token_hex(32)
        resp = await client.post(
            "/auth/login-form",
            data={
                "email": "loginsuccess@test.com",
                "password": "securepass123",
                "csrf_token": csrf_token,
            },
            cookies={"csrf_token": csrf_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 303
        assert "/dashboard" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_register_form_password_mismatch(self, client: AsyncClient) -> None:
        csrf_token = secrets.token_hex(32)
        resp = await client.post(
            "/auth/register-form",
            data={
                "email": "regmismatch@test.com",
                "pen_name": "Tester",
                "password": "securepass123",
                "password_confirm": "differentpass",
                "csrf_token": csrf_token,
            },
            cookies={"csrf_token": csrf_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 303
        assert "error" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_register_form_success(self, client: AsyncClient) -> None:
        csrf_token = secrets.token_hex(32)
        resp = await client.post(
            "/auth/register-form",
            data={
                "email": "regsuccess@test.com",
                "pen_name": "Tester",
                "password": "securepass123",
                "password_confirm": "securepass123",
                "csrf_token": csrf_token,
            },
            cookies={"csrf_token": csrf_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 303
        assert "/dashboard" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_logout(self, client: AsyncClient) -> None:
        resp = await client.get("/auth/logout")
        assert resp.status_code == 303
        location = resp.headers.get("location", "")
        # Redirects to homepage
        assert location.endswith("/") or location == "/"


class TestDashboardPage:
    """GET /dashboard — author dashboard (requires auth)."""

    @pytest.mark.asyncio
    async def test_dashboard_redirects_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/dashboard")
        assert resp.status_code == 303
        assert "/auth/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_dashboard_authed(self, client: AsyncClient) -> None:
        token, _ = await _register(client, email="dash@test.com")
        resp = await client.get(
            "/dashboard",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


class TestBrowsePage:
    """GET /browse — public novel listing."""

    @pytest.mark.asyncio
    async def test_browse_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/browse", headers={"Accept": "text/html"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_browse_with_sort(self, client: AsyncClient) -> None:
        resp = await client.get("/browse?sort=most_read", headers={"Accept": "text/html"})
        assert resp.status_code == 200


class TestNovelDetailPage:
    """GET /novels/{id} — novel overview page."""

    @pytest.mark.asyncio
    async def test_novel_detail_200(self, client: AsyncClient) -> None:
        _, headers = await _register(client, email="detail@test.com")
        novel_id = await _create_novel(client, headers)

        resp = await client.get(
            f"/novels/{novel_id}",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_novel_detail_404(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/novels/99999",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 404


class TestNovelNewPage:
    """GET /novels/new — create novel form (requires auth)."""

    @pytest.mark.asyncio
    async def test_novel_new_redirects_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/novels/new")
        assert resp.status_code == 303
        assert "/auth/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_novel_new_authed(self, client: AsyncClient) -> None:
        token, _ = await _register(client, email="newnovel@test.com")
        resp = await client.get(
            "/novels/new",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200


class TestWorldOverviewPage:
    """GET /novels/{id}/world — world overview (author-only)."""

    @pytest.mark.asyncio
    async def test_world_redirects_anonymous(self, client: AsyncClient) -> None:
        _, headers = await _register(client, email="worldanon@test.com")
        novel_id = await _create_novel(client, headers)

        resp = await client.get(f"/novels/{novel_id}/world")
        assert resp.status_code == 303
        assert "/auth/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_world_200_for_author(self, client: AsyncClient) -> None:
        token, headers = await _register(client, email="worldauth@test.com")
        novel_id = await _create_novel(client, headers)

        resp = await client.get(
            f"/novels/{novel_id}/world",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_world_404_nonexistent(self, client: AsyncClient) -> None:
        token, _ = await _register(client, email="worldmissing@test.com")
        resp = await client.get(
            "/novels/99999/world",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 404


class TestChapterReadPage:
    """GET /novels/{id}/chapters/{num} — chapter reading page."""

    @pytest.mark.asyncio
    async def test_chapter_404_no_chapter(self, client: AsyncClient) -> None:
        _, headers = await _register(client, email="chread@test.com")
        novel_id = await _create_novel(client, headers)

        resp = await client.get(
            f"/novels/{novel_id}/chapters/1",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_chapter_404_no_novel(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/novels/99999/chapters/1",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 404


class TestCharacterGalleryPage:
    """GET /novels/{id}/characters — character gallery page (author-only)."""

    @pytest.mark.asyncio
    async def test_characters_redirects_anonymous(self, client: AsyncClient) -> None:
        _, headers = await _register(client, email="charsanon@test.com")
        novel_id = await _create_novel(client, headers)

        resp = await client.get(f"/novels/{novel_id}/characters")
        assert resp.status_code == 303
        assert "/auth/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_characters_200_authed(self, client: AsyncClient) -> None:
        token, headers = await _register(client, email="chars@test.com")
        novel_id = await _create_novel(client, headers)

        resp = await client.get(
            f"/novels/{novel_id}/characters",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200


class TestSettingsPage:
    """GET /dashboard/settings — author settings page."""

    @pytest.mark.asyncio
    async def test_settings_redirects_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/dashboard/settings")
        assert resp.status_code == 303
        assert "/auth/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_settings_200_authed(self, client: AsyncClient) -> None:
        token, _ = await _register(client, email="settings@test.com")
        resp = await client.get(
            "/dashboard/settings",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200


class TestShareLinkPage:
    """GET /s/{share_token} — share link redirect."""

    @pytest.mark.asyncio
    async def test_share_link_valid(self, client: AsyncClient) -> None:
        """Valid share token → 303 redirect to novel detail."""
        _, headers = await _register(client, email="share@test.com")
        # Create novel and get its share_token from API
        resp = await client.post("/api/novels/", json={
            "title": "Shared Novel",
            "genre": "progression_fantasy",
        }, headers=headers)
        share_token = resp.json()["share_token"]

        resp = await client.get(f"/s/{share_token}")
        assert resp.status_code == 303
        assert "/novels/" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_share_link_invalid(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/s/nonexistent_token",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 404


class TestUsagePage:
    """GET /dashboard/usage — usage/billing page."""

    @pytest.mark.asyncio
    async def test_usage_redirects_anonymous(self, client: AsyncClient) -> None:
        resp = await client.get("/dashboard/usage")
        assert resp.status_code == 303
        assert "/auth/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_usage_200_authed(self, client: AsyncClient) -> None:
        token, _ = await _register(client, email="usage@test.com")
        resp = await client.get(
            "/dashboard/usage",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200


class TestArcPage:
    """GET /novels/{id}/arcs — arcs page."""

    @pytest.mark.asyncio
    async def test_arcs_200(self, client: AsyncClient) -> None:
        token, headers = await _register(client, email="arcs@test.com")
        novel_id = await _create_novel(client, headers)

        resp = await client.get(
            f"/novels/{novel_id}/arcs",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200


class TestGalleryPage:
    """GET /novels/{id}/gallery — image gallery page."""

    @pytest.mark.asyncio
    async def test_gallery_200(self, client: AsyncClient) -> None:
        token, headers = await _register(client, email="gallery@test.com")
        novel_id = await _create_novel(client, headers)

        resp = await client.get(
            f"/novels/{novel_id}/gallery",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200


class TestNovelSettingsPage:
    """GET /novels/{id}/settings — novel settings page."""

    @pytest.mark.asyncio
    async def test_novel_settings_200(self, client: AsyncClient) -> None:
        token, headers = await _register(client, email="nsettings@test.com")
        novel_id = await _create_novel(client, headers)

        resp = await client.get(
            f"/novels/{novel_id}/settings",
            cookies=_auth_cookies(token),
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200
