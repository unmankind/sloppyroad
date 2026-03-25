"""Shared test fixtures for AIWN 2.0."""

from collections.abc import AsyncGenerator
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from aiwebnovel.auth.jwt import create_access_token
from aiwebnovel.config import Settings


@pytest.fixture()
def test_settings() -> Settings:
    """Settings override for tests — all defaults, no .env file."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key-for-testing-only",
        debug=True,
        log_level="DEBUG",
        email_verification_required=False,  # tests bypass email verification
    )


@pytest.fixture()
async def db_engine(test_settings: Settings) -> AsyncGenerator:
    """Async in-memory SQLite engine for tests."""
    engine = create_async_engine(
        test_settings.database_url,
        echo=test_settings.database_echo,
    )

    # Import Base and create all tables
    # BEDROCK will provide the canonical Base. For now, use a minimal one.
    try:
        from aiwebnovel.db.models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except ImportError:
        pass

    yield engine

    async with engine.begin() as conn:
        try:
            from aiwebnovel.db.models import Base

            await conn.run_sync(Base.metadata.drop_all)
        except ImportError:
            pass

    await engine.dispose()


@pytest.fixture()
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Async session for tests, rolled back after each test."""
    async_session_factory = sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture()
async def test_client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient wired to the FastAPI test app."""
    from aiwebnovel.main import create_app

    app = create_app(settings_override=test_settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture()
def auth_headers(test_settings: Settings) -> dict[str, str]:
    """Generate JWT auth headers for a test user (no DB row — use for API-only tests)."""
    token = create_access_token(
        data={"sub": "testuser@example.com", "user_id": 1, "role": "author"},
        secret_key=test_settings.jwt_secret_key,
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
async def test_author(db_session: AsyncSession) -> dict:
    """Create User + AuthorProfile DB rows matching auth_headers (user_id=1).

    Returns a dict with the created user and author_profile objects.
    """
    from aiwebnovel.db.models import AuthorProfile, User

    user = User(
        id=1,
        email="testuser@example.com",
        username="testauthor",
        display_name="Test Author",
        auth_provider="local",
        hashed_password="hashed_placeholder",
        role="author",
        is_active=True,
        is_anonymous=False,
    )
    db_session.add(user)
    await db_session.flush()

    author_profile = AuthorProfile(
        user_id=user.id,
        display_name="Test Author",
        payment_status="trial",
        plan_type="trial",
    )
    db_session.add(author_profile)
    await db_session.commit()

    return {"user": user, "author_profile": author_profile}


def make_auth_headers(
    test_settings: Settings,
    email: str = "testuser@example.com",
    user_id: int = 1,
    role: str = "author",
) -> dict[str, str]:
    """Helper to generate JWT headers for arbitrary test users."""
    token = create_access_token(
        data={"sub": email, "user_id": user_id, "role": role},
        secret_key=test_settings.jwt_secret_key,
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}
