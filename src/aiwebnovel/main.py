"""FastAPI application factory with lifespan management.

Creates the AIWN 2.0 web application with:
- Async lifespan (DB engine + Redis init/shutdown)
- Health check endpoint
- CORS middleware
- Static file serving + Jinja2 templates
- Structured logging with request IDs
- Clean JSON error handlers
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from aiwebnovel.auth.middleware import (
    AnonymousReaderMiddleware,
    CsrfMiddleware,
    RateLimitMiddleware,
)
from aiwebnovel.config import Settings
from aiwebnovel.logging import configure_logging

logger = structlog.get_logger()

# Paths for static files and templates
_PACKAGE_DIR = Path(__file__).parent
_STATIC_DIR = _PACKAGE_DIR / "static"
_TEMPLATE_DIR = _PACKAGE_DIR / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle: startup and shutdown.

    On startup:
    - Initialize async DB engine
    - Initialize Redis connection pool

    On shutdown:
    - Close DB engine
    - Close Redis connection
    """
    settings: Settings = app.state.settings

    # ── Startup ───────────────────────────────────────────────────────
    logger.info(
        "app_starting",
        debug=settings.debug,
        database=settings.database_url.split("@")[-1] if "@" in settings.database_url else "sqlite",
    )

    # Warn about missing production config
    if not settings.encryption_key:
        logger.warning(
            "encryption_key_not_set",
            msg="AIWN_ENCRYPTION_KEY is empty — BYOK key storage will fail at runtime. "
            "Set it to a valid Fernet key for production.",
        )

    # Init DB engine and session factory

    from aiwebnovel.db.session import init_db

    engine = await init_db(
        settings.database_url,
        echo=settings.database_echo,
        pool_size=settings.db_pool_size,
        pool_max_overflow=settings.db_pool_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=settings.db_pool_pre_ping,
    )
    app.state.db_engine = engine

    # Create tables in dev/test (SQLite)
    if settings.database_url.startswith("sqlite"):
        try:
            from aiwebnovel.db.models import Base

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception as exc:  # Intentional broad catch: startup graceful degradation
            logger.warning("table_creation_skipped", error=str(exc))

    # Initialize vector store (auto-selects SQLite or PGVector)
    app.state.vector_store = None
    try:
        from aiwebnovel.db.vector import create_vector_store

        app.state.vector_store = await create_vector_store(settings)
        if app.state.vector_store is None:
            logger.warning(
                "vector_store_unavailable",
                msg="Story bible features will be degraded",
            )
    except Exception as exc:
        logger.warning("vector_store_init_skipped", error=str(exc))

    # Init Redis (optional — graceful if not available)
    app.state.redis = None
    app.state.arq_pool = None
    try:
        import redis.asyncio as aioredis

        app.state.redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        await app.state.redis.ping()
        logger.info("redis_connected", url=settings.redis_url)

        # Create ArqRedis pool for enqueuing background tasks
        from arq.connections import RedisSettings, create_pool

        arq_settings = RedisSettings.from_dsn(settings.redis_url)
        app.state.arq_pool = await create_pool(arq_settings)
        logger.info("arq_pool_created")
    except Exception as exc:  # Intentional broad catch: Redis is optional, graceful degradation
        logger.warning("redis_unavailable", error=str(exc))
        app.state.redis = None
        app.state.arq_pool = None

    logger.info("app_started")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────
    logger.info("app_shutting_down")

    if (
        hasattr(app.state, "vector_store")
        and app.state.vector_store is not None
        and hasattr(app.state.vector_store, "close")
    ):
        await app.state.vector_store.close()
        logger.info("vector_store_closed")

    if app.state.arq_pool:
        await app.state.arq_pool.close()
        logger.info("arq_pool_closed")

    if app.state.redis:
        await app.state.redis.close()
        logger.info("redis_closed")

    from aiwebnovel.db.session import close_db

    await close_db()
    logger.info("db_engine_disposed")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to each request for tracing."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        structlog.contextvars.unbind_contextvars("request_id")
        return response


def create_app(settings_override: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings_override: Optional settings for testing. If None,
            loads from environment / .env file.

    Returns:
        Configured FastAPI application instance.
    """
    settings = settings_override or Settings()

    # Configure structlog before anything logs
    configure_logging(settings)

    # Initialize Sentry error tracking (if DSN configured)
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,  # 10% of requests for performance monitoring
            environment="production" if not settings.debug else "development",
            send_default_pii=False,  # don't send emails/IPs to Sentry
        )

    app = FastAPI(
        title="SloppyRoad — Certified AI Slop",
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    # Store settings in app state for access from dependencies
    app.state.settings = settings

    # ── Middleware (applied in reverse order) ──────────────────────────
    # Rate limiting (outermost — applied first)
    app.add_middleware(RateLimitMiddleware)

    # Anonymous reader cookies
    app.add_middleware(AnonymousReaderMiddleware)

    # CSRF protection (double-submit cookie)
    app.add_middleware(CsrfMiddleware)

    # Request ID for structured logging
    app.add_middleware(RequestIDMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-CSRF-Token",
            "HX-Request",
            "HX-Target",
            "HX-Trigger",
        ],
    )

    # ── Static files ──────────────────────────────────────────────────
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # robots.txt at root (search engines expect /robots.txt)
    _robots_path = _STATIC_DIR / "robots.txt"
    if _robots_path.exists():
        from starlette.responses import FileResponse

        @app.get("/robots.txt", include_in_schema=False)
        async def robots_txt():
            return FileResponse(str(_robots_path), media_type="text/plain")

    # ── Image assets ─────────────────────────────────────────────────
    _image_asset_dir = Path(settings.image_asset_path)
    if _image_asset_dir.exists():
        app.mount(
            "/assets/images",
            StaticFiles(directory=str(_image_asset_dir)),
            name="image_assets",
        )

    # ── Templates ─────────────────────────────────────────────────────
    if _TEMPLATE_DIR.exists():
        app.state.templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
        # Jinja2Templates defaults to autoescape=True for .html templates

        # Custom Jinja2 filters
        def _timeago(dt: datetime | str | None) -> str:
            """Format a datetime as relative time (e.g. '2 hours ago')."""
            if dt is None:
                return ""
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt)
                except (ValueError, TypeError):
                    return str(dt)
            now = datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            diff = now - dt
            seconds = int(diff.total_seconds())
            if seconds < 60:
                return "just now"
            minutes = seconds // 60
            if minutes < 60:
                return f"{minutes}m ago"
            hours = minutes // 60
            if hours < 24:
                return f"{hours}h ago"
            days = hours // 24
            if days < 30:
                return f"{days}d ago"
            months = days // 30
            if months < 12:
                return f"{months}mo ago"
            return dt.strftime("%b %d, %Y")

        def _format_genre(genre: str | None) -> str:
            """Format genre slug to display name.

            e.g. 'progression_fantasy' -> 'Progression Fantasy'
            """
            if not genre:
                return ""
            return genre.replace("_", " ").title()

        def _reading_time(word_count: int) -> str:
            """Estimate reading time from word count (avg 250 wpm)."""
            if not word_count:
                return ""
            minutes = max(1, word_count // 250)
            if minutes < 60:
                return f"{minutes} min read"
            hours = minutes // 60
            remaining = minutes % 60
            if remaining:
                return f"{hours}h {remaining}m read"
            return f"{hours}h read"

        import json as _json

        def _tojson(value: object) -> str:
            """Serialize a value to JSON for safe use in templates."""
            return _json.dumps(value, default=str, indent=2)

        def _format_value(v: object) -> str:
            """Render a value nicely — parse JSON-coerced strings, join lists."""
            if v is None:
                return ""
            if isinstance(v, dict):
                parts = []
                for k, val in v.items():
                    label = str(k).replace("_", " ").title()
                    parts.append(f"{label}: {_format_value(val)}")
                return "; ".join(parts)
            if isinstance(v, list):
                return ", ".join(_format_value(item) for item in v)
            s = str(v)
            if s.startswith(("[", "{")):
                try:
                    parsed = _json.loads(s)
                    return _format_value(parsed)
                except (_json.JSONDecodeError, TypeError):
                    pass
            return s

        _STATUS_LABELS = {
            "skeleton_pending": "New",
            "skeleton_in_progress": "Building World",
            "skeleton_complete": "World Ready",
            "building_world": "Building World",
            "world_ready": "World Ready",
            "writing": "Writing",
            "writing_paused": "Paused",
            "writing_complete": "Complete",
            "complete": "Complete",
            "completed": "Complete",
            "abandoned": "Abandoned",
            "active": "Writing",
        }

        _STATUS_BADGES = {
            "skeleton_pending": "badge-default",
            "skeleton_in_progress": "badge-default",
            "skeleton_complete": "badge-success",
            "building_world": "badge-default",
            "world_ready": "badge-success",
            "writing": "badge-success",
            "writing_paused": "badge-default",
            "writing_complete": "badge-arcane",
            "complete": "badge-arcane",
            "completed": "badge-arcane",
            "abandoned": "badge-default",
            "active": "badge-success",
        }

        def _format_status(status: str | None) -> str:
            """Map novel status enum to human-readable label."""
            if not status:
                return "Active"
            return _STATUS_LABELS.get(status.lower(), status.replace("_", " ").title())

        def _status_badge_class(status: str | None) -> str:
            """Return CSS badge class for a novel status."""
            if not status:
                return "badge-default"
            return _STATUS_BADGES.get(status.lower(), "badge-default")

        def _pluralize(count: object, singular: str = "", plural: str = "s") -> str:
            """Return singular or plural suffix based on count."""
            if isinstance(count, (list, tuple)):
                count = len(count)
            try:
                return singular if int(count) == 1 else plural
            except (TypeError, ValueError):
                return plural

        env = app.state.templates.env
        env.filters["timeago"] = _timeago
        env.filters["format_genre"] = _format_genre
        env.filters["reading_time"] = _reading_time
        env.filters["tojson"] = _tojson
        env.filters["format_value"] = _format_value
        env.filters["format_status"] = _format_status
        env.filters["status_badge_class"] = _status_badge_class
        env.filters["pluralize"] = _pluralize

    # ── Exception handlers ────────────────────────────────────────────
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: Exception) -> Response:
        accept = request.headers.get("accept", "")
        if "text/html" in accept and hasattr(app.state, "templates"):
            # Resolve auth so 404 pages show the correct navbar state
            from aiwebnovel.auth.dependencies import get_optional_user

            current_author = None
            try:
                user = await get_optional_user(request)
                if user and user.get("role") == "author":
                    current_author = user
            except Exception:
                pass
            return app.state.templates.TemplateResponse(
                "pages/404.html",
                {"request": request, "current_author": current_author, "message": None},
                status_code=404,
            )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Not found"},
        )

    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc: Exception) -> Response:
        logger.error("unhandled_error", error=str(exc), path=request.url.path)
        accept = request.headers.get("accept", "")
        if "text/html" in accept and hasattr(app.state, "templates"):
            return app.state.templates.TemplateResponse(
                "pages/500.html",
                {"request": request, "current_author": None},
                status_code=500,
            )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # ── Health check ──────────────────────────────────────────────────
    @app.get("/health", tags=["system"])
    async def health_check(request: Request) -> dict:
        """Report health status of all subsystems with metrics."""
        import time as _time

        from sqlalchemy import func, select, text

        from aiwebnovel.db.models import GenerationJob, ImageUsageLog, LLMUsageLog

        health: dict[str, Any] = {
            "status": "ok",
            "version": "0.1.0",
            "db": {"status": "unknown"},
            "redis": {"status": "unknown"},
            "workers": {"status": "unknown"},
        }

        # ── DB check ──
        try:
            engine = request.app.state.db_engine
            t0 = _time.monotonic()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_ms = round((_time.monotonic() - t0) * 1000, 1)

            db_info: dict[str, Any] = {
                "status": "connected",
                "response_ms": db_ms,
            }
            # Pool stats only available on QueuePool (PostgreSQL), not StaticPool (SQLite)
            pool = engine.pool
            if hasattr(pool, "size"):
                db_info["pool_size"] = pool.size()
                db_info["checked_out"] = pool.checkedout()
                db_info["overflow"] = pool.overflow()
            health["db"] = db_info
        except Exception as exc:
            logger.warning("health_check_db_error", error=str(exc))
            health["db"] = {"status": "error", "error": str(exc)[:200]}
            health["status"] = "degraded"

        # ── Redis check ──
        try:
            redis_conn = request.app.state.redis
            if redis_conn:
                t0 = _time.monotonic()
                await redis_conn.ping()
                redis_ms = round((_time.monotonic() - t0) * 1000, 1)

                info = await redis_conn.info("memory")
                # arq uses sorted sets (zset) for queues, not lists
                pending_main = await redis_conn.zcard("arq:queue")
                pending_images = await redis_conn.zcard("arq:queue:images")

                health["redis"] = {
                    "status": "connected",
                    "response_ms": redis_ms,
                    "used_memory_mb": round(
                        info.get("used_memory", 0) / 1024 / 1024, 1,
                    ),
                    "pending_jobs_main": pending_main,
                    "pending_jobs_images": pending_images,
                }
            else:
                health["redis"] = {"status": "not_configured"}
        except Exception as exc:
            logger.warning("health_check_redis_error", error=str(exc))
            health["redis"] = {"status": "error", "error": str(exc)[:200]}
            health["status"] = "degraded"

        # ── Worker / generation job metrics ──
        try:
            from aiwebnovel.db.session import get_session_factory

            session_factory = get_session_factory(request.app.state.db_engine)
            async with session_factory() as session:
                # Job counts by status
                job_rows = (
                    await session.execute(
                        select(
                            GenerationJob.status,
                            func.count(),
                        ).group_by(GenerationJob.status)
                    )
                ).all()
                job_counts = {row[0]: row[1] for row in job_rows}

                running = job_counts.get("running", 0)
                queued = job_counts.get("queued", 0)
                stale = job_counts.get("stale", 0)
                failed = job_counts.get("failed", 0)

                worker_status = "ok"
                if stale > 0:
                    worker_status = "degraded"
                    health["status"] = "degraded"

                health["workers"] = {
                    "status": worker_status,
                    "running_jobs": running,
                    "queued_jobs": queued,
                    "stale_jobs": stale,
                    "failed_jobs_total": failed,
                }

                # Cost metrics (last 24h)
                from datetime import datetime, timedelta, timezone

                cutoff = datetime.now(timezone.utc).replace(
                    tzinfo=None,
                ) - timedelta(hours=24)

                llm_cost = (
                    await session.execute(
                        select(func.coalesce(func.sum(LLMUsageLog.cost_cents), 0))
                        .where(LLMUsageLog.created_at >= cutoff)
                    )
                ).scalar_one()
                img_cost = (
                    await session.execute(
                        select(func.coalesce(func.sum(ImageUsageLog.cost_cents), 0))
                        .where(ImageUsageLog.created_at >= cutoff)
                    )
                ).scalar_one()

                health["costs_24h"] = {
                    "llm_cents": round(float(llm_cost), 2),
                    "image_cents": round(float(img_cost), 2),
                }

        except Exception as exc:
            logger.warning("health_check_workers_error", error=str(exc))
            health["workers"] = {"status": "error", "error": str(exc)[:200]}

        # Final status: 503 if critical subsystems are down
        status_code = 200
        if health["db"].get("status") == "error" or health["redis"].get("status") == "error":
            status_code = 503

        if status_code != 200:
            from starlette.responses import JSONResponse as _JSONResponse

            return _JSONResponse(content=health, status_code=status_code)
        return health

    # ── Page Routes (HTML rendering — registered first for priority) ──
    from aiwebnovel.api.pages import router as pages_router

    app.include_router(pages_router, tags=["pages"])

    # ── API Routes (JSON — for HTMX POST/PATCH/DELETE and API clients) ─
    from aiwebnovel.api.routes_auth import router as auth_router
    from aiwebnovel.api.routes_browse import router as browse_router
    from aiwebnovel.api.routes_chapter import router as chapter_router
    from aiwebnovel.api.routes_characters import router as characters_router
    from aiwebnovel.api.routes_chekhov import router as chekhov_router
    from aiwebnovel.api.routes_dashboard import router as dashboard_router
    from aiwebnovel.api.routes_gallery import router as gallery_router
    from aiwebnovel.api.routes_keys import router as keys_router
    from aiwebnovel.api.routes_notifications import router as notifications_router
    from aiwebnovel.api.routes_planning import router as planning_router
    from aiwebnovel.api.routes_reader import router as reader_router
    from aiwebnovel.api.routes_seeds import router as seeds_router
    from aiwebnovel.api.routes_story import router as story_router
    from aiwebnovel.api.routes_stream import router as stream_router
    from aiwebnovel.api.routes_world import router as world_router

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
    app.include_router(keys_router, prefix="/api", tags=["keys"])
    app.include_router(story_router, prefix="/api/novels", tags=["novels"])
    app.include_router(seeds_router, prefix="/api/novels", tags=["seeds"])
    app.include_router(gallery_router, prefix="/api/novels", tags=["gallery"])
    app.include_router(planning_router, prefix="/novels", tags=["planning"])
    app.include_router(chapter_router, prefix="/api/novels", tags=["chapters"])
    app.include_router(characters_router, prefix="/novels", tags=["characters"])
    app.include_router(world_router, prefix="/novels", tags=["world"])
    app.include_router(chekhov_router, prefix="/novels", tags=["chekhov"])
    app.include_router(reader_router, prefix="/novels", tags=["reader"])
    app.include_router(browse_router, prefix="/api/browse", tags=["browse"])
    app.include_router(notifications_router, prefix="/api/notifications", tags=["notifications"])
    app.include_router(stream_router, prefix="/api/stream", tags=["stream"])

    return app
