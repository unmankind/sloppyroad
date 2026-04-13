"""Shared helpers for page route modules.

Common context builders, formatters, and cover URL resolution used
across multiple page route modules.
"""

from __future__ import annotations

import html as _html
import re

import structlog
from fastapi import Request
from fastapi.responses import RedirectResponse
from markupsafe import Markup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import get_optional_user
from aiwebnovel.db.models import (
    ArtAsset,
    ArtGenerationQueue,
    AuthorProfile,
    LLMUsageLog,
    Notification,
    Novel,
    NovelStats,
    User,
)

logger = structlog.get_logger(__name__)


def _templates(request: Request):
    """Get Jinja2Templates from app state."""
    return request.app.state.templates


def _format_chapter_text(raw_text: str) -> Markup:
    """Convert raw chapter text (with \\n\\n paragraph breaks) to HTML paragraphs.

    Also converts markdown emphasis to HTML:
    - **bold** → <strong>bold</strong>
    - *italic* → <em>italic</em>
    - --- (horizontal rule) → <hr>
    """
    # Strip leading markdown headers (e.g. "# Chapter 1\n\n") — the template
    # already renders the chapter title in the page header.
    text = re.sub(r"\A(#{1,6}\s+[^\n]*\n*)+", "", raw_text).lstrip("\n")
    escaped = _html.escape(text)

    # Convert markdown emphasis to HTML (after escaping so tags are safe).
    # Bold first (**word**), then italic (*word*) to avoid conflicts.
    escaped = re.sub(
        r"\*\*([^*]+?)\*\*", r"<strong>\1</strong>", escaped,
    )
    escaped = re.sub(
        r"\*([^*]+?)\*", r"<em>\1</em>", escaped,
    )
    # Horizontal rules: standalone --- or *** lines
    escaped = re.sub(
        r"(?m)^(?:---|\*\*\*|___)$", "<hr>", escaped,
    )

    paragraphs = escaped.split("\n\n")
    html_parts = []
    for p in paragraphs:
        p = p.strip()
        if p:
            if p == "<hr>":
                html_parts.append(p)
            else:
                p = p.replace("\n", "<br>")
                html_parts.append(f"<p>{p}</p>")
    return Markup("\n".join(html_parts))


def _redirect_to_login(request: Request, url: str = "/auth/login") -> RedirectResponse:
    """Redirect to login, clearing stale auth cookie if flagged by _base_context."""
    response = RedirectResponse(url, status_code=303)
    if getattr(request.state, "clear_auth_cookie", False):
        response.delete_cookie("aiwn_token")
    return response


async def _base_context(request: Request, db: AsyncSession) -> dict:
    """Build base template context shared by all pages.

    Populates: request, current_author (or None for anonymous).
    """
    ctx: dict = {"request": request, "current_author": None}

    user = await get_optional_user(request)
    if user and user.get("role") == "author":
        user_id = user["user_id"]
        # Verify the User row still exists in the DB (guards against stale JWTs
        # after a DB wipe).
        db_user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if db_user is None:
            # Stale JWT — user no longer exists. Flag for cookie clearing.
            logger.warning("stale_jwt_in_base_context", user_id=user_id)
            request.state.clear_auth_cookie = True
            return ctx

        stmt = select(AuthorProfile).where(
            AuthorProfile.user_id == user_id
        )
        result = await db.execute(stmt)
        profile = result.scalar_one_or_none()
        ctx["current_author"] = {
            "email": user.get("sub"),
            "user_id": user_id,
            "pen_name": profile.display_name if profile else user.get("sub"),
            "has_profile": profile is not None,
            "plan_type": profile.plan_type if profile else "free",
        }
        ctx["plan_type"] = profile.plan_type if profile else "free"
        # Unread notification count for the navbar bell badge
        unread_stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        ctx["unread_count"] = (await db.execute(unread_stmt)).scalar_one()

    # CSRF token (set by CsrfMiddleware) for template forms and JS
    ctx["csrf_token"] = getattr(request.state, "csrf_token", "")

    return ctx


async def _get_novel_cover_url(
    db: AsyncSession, novel_id: int,
) -> tuple[str | None, bool]:
    """Return the URL for a novel's cover image, with fallback chain.

    Returns (cover_url, cover_generating).

    Fallback:
    1. Cover art asset → use it
    2. No cover but pending/generating ArtGenerationQueue entry → (None, True)
    3. Protagonist portrait → use it
    4. World map → use it
    5. None (template uses gradient)
    """
    # Check for cover asset first
    stmt = (
        select(ArtAsset.file_path)
        .where(
            ArtAsset.novel_id == novel_id,
            ArtAsset.asset_type == "cover",
            ArtAsset.is_current.is_(True),
            ArtAsset.file_path.isnot(None),
        )
        .order_by(ArtAsset.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        return f"/assets/images/{row}", False

    # No cover asset — check if one is pending/generating
    pending_stmt = (
        select(ArtGenerationQueue.id)
        .where(
            ArtGenerationQueue.novel_id == novel_id,
            ArtGenerationQueue.asset_type == "cover",
            ArtGenerationQueue.status.in_(("pending", "generating")),
        )
        .limit(1)
    )
    pending = (await db.execute(pending_stmt)).scalar_one_or_none()
    if pending is not None:
        return None, True

    # Fall through to portrait / map
    for asset_type in ("portrait", "world_map"):
        stmt = (
            select(ArtAsset.file_path)
            .where(
                ArtAsset.novel_id == novel_id,
                ArtAsset.asset_type == asset_type,
                ArtAsset.is_current.is_(True),
                ArtAsset.file_path.isnot(None),
            )
            .order_by(ArtAsset.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            return f"/assets/images/{row}", False
    return None, False


async def _batch_get_cover_urls(
    db: AsyncSession, novel_ids: list[int],
) -> dict[int, tuple[str | None, bool]]:
    """Batch-fetch cover URLs for multiple novels in a single query.

    Returns {novel_id: (cover_url, cover_generating)}.
    Fallback chain per novel: cover → pending cover → portrait → world_map → None.
    """
    if not novel_ids:
        return {}

    # Fetch all current art assets for these novels (covers, portraits, maps)
    asset_stmt = (
        select(ArtAsset.novel_id, ArtAsset.asset_type, ArtAsset.file_path)
        .where(
            ArtAsset.novel_id.in_(novel_ids),
            ArtAsset.asset_type.in_(("cover", "portrait", "world_map")),
            ArtAsset.is_current.is_(True),
            ArtAsset.file_path.isnot(None),
        )
        .order_by(ArtAsset.created_at.desc())
    )
    asset_rows = (await db.execute(asset_stmt)).all()

    # Build per-novel maps: {novel_id: {asset_type: file_path}} (first wins)
    asset_map: dict[int, dict[str, str]] = {}
    for novel_id, asset_type, file_path in asset_rows:
        asset_map.setdefault(novel_id, {})
        if asset_type not in asset_map[novel_id]:
            asset_map[novel_id][asset_type] = file_path

    # Check for pending/generating cover jobs for novels that lack a cover asset
    novels_without_cover = [
        nid for nid in novel_ids
        if "cover" not in asset_map.get(nid, {})
    ]
    pending_set: set[int] = set()
    if novels_without_cover:
        pending_stmt = (
            select(ArtGenerationQueue.novel_id)
            .where(
                ArtGenerationQueue.novel_id.in_(novels_without_cover),
                ArtGenerationQueue.asset_type == "cover",
                ArtGenerationQueue.status.in_(("pending", "generating")),
            )
            .distinct()
        )
        pending_set = {
            row[0] for row in (await db.execute(pending_stmt)).all()
        }

    # Build result with fallback chain
    result: dict[int, tuple[str | None, bool]] = {}
    for nid in novel_ids:
        assets = asset_map.get(nid, {})
        if "cover" in assets:
            result[nid] = (f"/assets/images/{assets['cover']}", False)
        elif nid in pending_set:
            result[nid] = (None, True)
        elif "portrait" in assets:
            result[nid] = (f"/assets/images/{assets['portrait']}", False)
        elif "world_map" in assets:
            result[nid] = (f"/assets/images/{assets['world_map']}", False)
        else:
            result[nid] = (None, False)
    return result


async def _inject_cover_urls(db: AsyncSession, novels: list[dict]) -> None:
    """Batch-inject cover_url and cover_generating into a list of novel view dicts."""
    novel_ids = [nv["id"] for nv in novels]
    cover_map = await _batch_get_cover_urls(db, novel_ids)
    for nv in novels:
        cover_url, cover_generating = cover_map.get(nv["id"], (None, False))
        nv["cover_url"] = cover_url
        nv["cover_generating"] = cover_generating


def _novel_view(
    novel: Novel,
    stats: NovelStats | None = None,
    *,
    chapter_count_override: int | None = None,
    author_name: str | None = None,
    cover_url: str | None = None,
) -> dict:
    """Build a template-friendly dict from a Novel ORM instance.

    Templates expect fields like description, chapter_count, word_count,
    avg_rating, etc. that aren't on the Novel model directly.
    """
    chapter_count = chapter_count_override if chapter_count_override is not None else (
        stats.total_chapters if stats else 0
    )

    # Derive display status from actual state instead of relying on
    # the potentially-stale novel.status DB field.
    raw_status = novel.status or ""
    if raw_status in ("complete", "writing_complete"):
        effective_status = raw_status
    elif chapter_count > 0:
        effective_status = "writing"
    elif raw_status == "skeleton_complete":
        effective_status = "skeleton_complete"
    else:
        effective_status = raw_status

    # Format tags — use GenreConfig display name for the genre badge
    from aiwebnovel.story.genre_config import get_genre_config

    genre_cfg = get_genre_config(novel.genre) if novel.genre else None
    tags = [genre_cfg.display_name] if genre_cfg else []

    return {
        "id": novel.id,
        "title": novel.title,
        "genre": novel.genre,
        "status": effective_status,
        "description": novel.description or novel.completion_summary or "",
        "tagline": "",
        "tags": tags,
        "share_token": novel.share_token,
        "is_public": novel.is_public,
        "created_at": novel.created_at,
        "updated_at": novel.updated_at,
        "chapter_count": chapter_count,
        "word_count": stats.total_words if stats else 0,
        "reader_count": stats.total_readers if stats else 0,
        "avg_rating": stats.avg_rating if stats else None,
        "rating_count": stats.rating_count if stats else 0,
        "author_name": author_name or "",
        "cover_url": cover_url or "",
        "cover_generating": False,
    }


async def _author_sidebar_context(
    ctx: dict, db: AsyncSession, user_id: int,
) -> None:
    """Populate ctx with sidebar data: novels list + author stats.

    Extracts the repeated sidebar pattern (novel count, total words,
    total chapters) into a reusable helper.
    """
    novels_stmt = (
        select(Novel, NovelStats)
        .outerjoin(NovelStats, NovelStats.novel_id == Novel.id)
        .where(Novel.author_id == user_id)
        .order_by(Novel.updated_at.desc())
    )
    novels_result = await db.execute(novels_stmt)
    ctx["novels"] = [_novel_view(row[0], row[1]) for row in novels_result.all()]
    ctx["author_stats"] = {
        "novel_count": len(ctx["novels"]),
        "chapter_count": sum(n["chapter_count"] for n in ctx["novels"]),
        "word_count": sum(n["word_count"] for n in ctx["novels"]),
        "budget_remaining": 0,
    }


async def _author_settings_context(
    request: Request, db: AsyncSession
) -> dict:
    """Build context for author settings page (reuses author_base layout)."""
    ctx = await _base_context(request, db)

    if not ctx["current_author"]:
        return ctx

    user_id = ctx["current_author"]["user_id"]

    # User record (for email)
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    ctx["user"] = user

    # Author profile
    profile = (
        await db.execute(
            select(AuthorProfile).where(AuthorProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    ctx["profile"] = profile

    # Novels list (for sidebar)
    stmt = (
        select(Novel, NovelStats)
        .outerjoin(NovelStats, NovelStats.novel_id == Novel.id)
        .where(Novel.author_id == user_id)
        .order_by(Novel.updated_at.desc())
    )
    result = await db.execute(stmt)
    ctx["novels"] = [_novel_view(row[0], row[1]) for row in result.all()]

    # Author stats for author_base.html
    spent_stmt = select(
        func.coalesce(func.sum(LLMUsageLog.cost_cents), 0.0),
    ).where(LLMUsageLog.user_id == user_id)
    total_spent_cents = float(
        (await db.execute(spent_stmt)).scalar_one()
    )
    budget_cents = profile.api_budget_cents if profile else 0
    budget_remaining = (budget_cents - total_spent_cents) / 100.0

    ctx["author_stats"] = {
        "novel_count": len(ctx["novels"]),
        "chapter_count": sum(n["chapter_count"] for n in ctx["novels"]),
        "word_count": sum(n["word_count"] for n in ctx["novels"]),
        "budget_remaining": budget_remaining,
    }

    # API keys for BYOK settings section
    from aiwebnovel.db.models import AuthorAPIKey

    api_keys_rows = (
        await db.execute(
            select(AuthorAPIKey).where(AuthorAPIKey.user_id == user_id)
        )
    ).scalars().all()
    ctx["api_keys"] = [
        {"provider": k.provider, "key_suffix": k.key_suffix, "is_valid": k.is_valid}
        for k in api_keys_rows
    ]

    ctx["active_page"] = "settings"
    ctx["selected_novel"] = None

    return ctx
