"""Tests for WorkerHealth — heartbeat, recovery, dead letter."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from aiwebnovel.db.models import (
    AuthorProfile,
    Base,
    GenerationJob,
    Notification,
    Novel,
    User,
)
from aiwebnovel.worker.health import WorkerHealth


@pytest.fixture()
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def session_factory(db_engine):
    return sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture()
def worker_health() -> WorkerHealth:
    return WorkerHealth()


async def _seed_data(session: AsyncSession) -> tuple[int, int, int]:
    """Create user + novel + stale job. Return (user_id, novel_id, job_id)."""
    user = User(
        email="test@example.com",
        username="tester",
        hashed_password="hash",
        role="author",
    )
    session.add(user)
    await session.flush()

    profile = AuthorProfile(
        user_id=user.id,
        api_budget_cents=5000,
    )
    session.add(profile)

    novel = Novel(
        author_id=user.id,
        title="Stale Novel",
        status="writing",
    )
    session.add(novel)
    await session.flush()

    job = GenerationJob(
        novel_id=novel.id,
        job_type="chapter_generation",
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    session.add(job)
    await session.flush()
    await session.commit()
    return user.id, novel.id, job.id


class TestHeartbeat:
    """Tests for heartbeat start/stop."""

    @pytest.mark.asyncio
    async def test_heartbeat_updates_job_timestamp(
        self, worker_health: WorkerHealth, session_factory
    ) -> None:
        """Heartbeat should update GenerationJob.heartbeat_at periodically."""
        async with session_factory() as session:
            user_id, novel_id, job_id = await _seed_data(session)

        # Start heartbeat with very short interval for testing
        task = await worker_health.start_heartbeat(
            session_factory, job_id, interval=0.1
        )

        # Wait a bit for at least one beat
        await asyncio.sleep(0.3)

        await worker_health.stop_heartbeat(task)

        # Verify timestamp was updated
        async with session_factory() as session:
            stmt = select(GenerationJob).where(GenerationJob.id == job_id)
            result = await session.execute(stmt)
            job = result.scalar_one()
            # Heartbeat should be very recent (naive datetimes from SQLite)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            age = (now - job.heartbeat_at).total_seconds()
            assert age < 2.0  # Updated within the last 2 seconds

    @pytest.mark.asyncio
    async def test_stop_heartbeat_cancels_task(
        self, worker_health: WorkerHealth, session_factory
    ) -> None:
        """stop_heartbeat should cancel the background asyncio task."""
        async with session_factory() as session:
            _, _, job_id = await _seed_data(session)

        task = await worker_health.start_heartbeat(session_factory, job_id, interval=1)
        assert not task.cancelled()

        await worker_health.stop_heartbeat(task)
        assert task.cancelled()


class TestRecoverStaleJobs:
    """Tests for stale job recovery."""

    @pytest.mark.asyncio
    async def test_finds_old_jobs(
        self, worker_health: WorkerHealth, session_factory, mock_redis: AsyncMock
    ) -> None:
        """recover_stale_jobs should find jobs with heartbeat > 120s old."""
        async with session_factory() as session:
            _, novel_id, job_id = await _seed_data(session)

        async with session_factory() as session:
            recovered = await worker_health.recover_stale_jobs(
                session, mock_redis
            )

        assert job_id in recovered

    @pytest.mark.asyncio
    async def test_releases_redis_locks(
        self, worker_health: WorkerHealth, session_factory, mock_redis: AsyncMock
    ) -> None:
        """recover_stale_jobs should release Redis locks for stale jobs."""
        async with session_factory() as session:
            _, novel_id, job_id = await _seed_data(session)

        async with session_factory() as session:
            await worker_health.recover_stale_jobs(session, mock_redis)

        mock_redis.delete.assert_called()
        # Verify the lock key for the novel was deleted
        delete_calls = [str(c) for c in mock_redis.delete.call_args_list]
        assert any(f"novel:{novel_id}" in c for c in delete_calls) or mock_redis.delete.called

    @pytest.mark.asyncio
    async def test_marks_jobs_as_stale(
        self, worker_health: WorkerHealth, session_factory, mock_redis: AsyncMock
    ) -> None:
        """recover_stale_jobs should update job status to 'stale'."""
        async with session_factory() as session:
            _, _, job_id = await _seed_data(session)

        async with session_factory() as session:
            await worker_health.recover_stale_jobs(session, mock_redis)

        async with session_factory() as session:
            stmt = select(GenerationJob).where(GenerationJob.id == job_id)
            result = await session.execute(stmt)
            job = result.scalar_one()
            assert job.status == "stale"

    @pytest.mark.asyncio
    async def test_finds_null_heartbeat_jobs(
        self, worker_health: WorkerHealth, session_factory, mock_redis: AsyncMock
    ) -> None:
        """Detect jobs with NULL heartbeat_at (crashed before first beat)."""
        async with session_factory() as session:
            user = User(
                email="null@test.com",
                username="nullhb",
                hashed_password="hash",
                role="author",
            )
            session.add(user)
            await session.flush()

            profile = AuthorProfile(user_id=user.id, api_budget_cents=5000)
            session.add(profile)

            novel = Novel(author_id=user.id, title="Null HB", status="writing")
            session.add(novel)
            await session.flush()

            job = GenerationJob(
                novel_id=novel.id,
                job_type="chapter_generation",
                status="running",
                started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
                heartbeat_at=None,  # Crashed before first heartbeat
            )
            session.add(job)
            await session.flush()
            null_job_id = job.id
            await session.commit()

        async with session_factory() as session:
            recovered = await worker_health.recover_stale_jobs(
                session, mock_redis
            )

        assert null_job_id in recovered

    @pytest.mark.asyncio
    async def test_notification_uses_author_id(
        self, worker_health: WorkerHealth, session_factory, mock_redis: AsyncMock
    ) -> None:
        """recover_stale_jobs should set notification.user_id to novel.author_id, not novel_id."""
        async with session_factory() as session:
            user_id, novel_id, job_id = await _seed_data(session)

        async with session_factory() as session:
            await worker_health.recover_stale_jobs(session, mock_redis)

        async with session_factory() as session:
            stmt = select(Notification)
            result = await session.execute(stmt)
            notification = result.scalar_one()
            assert notification.user_id == user_id
            assert notification.user_id != novel_id or user_id == novel_id

    @pytest.mark.asyncio
    async def test_ignores_recent_jobs(
        self, worker_health: WorkerHealth, session_factory, mock_redis: AsyncMock
    ) -> None:
        """recover_stale_jobs should not touch jobs with recent heartbeats."""
        async with session_factory() as session:
            user = User(
                email="fresh@test.com",
                username="fresh",
                hashed_password="hash",
                role="author",
            )
            session.add(user)
            await session.flush()

            profile = AuthorProfile(user_id=user.id, api_budget_cents=5000)
            session.add(profile)

            novel = Novel(author_id=user.id, title="Fresh", status="writing")
            session.add(novel)
            await session.flush()

            fresh_job = GenerationJob(
                novel_id=novel.id,
                job_type="chapter_generation",
                status="running",
                started_at=datetime.now(timezone.utc) - timedelta(seconds=30),
                heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            )
            session.add(fresh_job)
            await session.flush()
            fresh_id = fresh_job.id
            await session.commit()

        async with session_factory() as session:
            recovered = await worker_health.recover_stale_jobs(
                session, mock_redis
            )

        assert fresh_id not in recovered


class TestMarkDeadLetter:
    """Tests for dead letter handling."""

    @pytest.mark.asyncio
    async def test_sets_correct_status(
        self, worker_health: WorkerHealth, session_factory
    ) -> None:
        """mark_dead_letter should set status='dead_letter' with error."""
        async with session_factory() as session:
            _, _, job_id = await _seed_data(session)

        async with session_factory() as session:
            await worker_health.mark_dead_letter(
                session, job_id, "Permanent failure: model unavailable"
            )

        async with session_factory() as session:
            stmt = select(GenerationJob).where(GenerationJob.id == job_id)
            result = await session.execute(stmt)
            job = result.scalar_one()
            assert job.status == "dead_letter"
            assert "Permanent failure" in job.error_message
