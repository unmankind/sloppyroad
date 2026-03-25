"""DEPRECATED: This module has been split into the ``aiwebnovel.api.pages`` package.

The monolithic routes_pages.py has been refactored into domain-specific modules:

    pages/__init__.py   — Combined router (drop-in replacement)
    pages/helpers.py    — Shared context builders and utilities
    pages/home.py       — Homepage
    pages/auth.py       — Login, register, logout, author settings
    pages/dashboard.py  — Dashboard, usage
    pages/browse.py     — Browse/search novels
    pages/novel.py      — Novel detail, create, delete, settings, share, the-end
    pages/world.py      — World seeds, generation, forging, overview, power system
    pages/chapter.py    — Chapter reading, generation, analysis
    pages/characters.py — Character gallery and detail
    pages/gallery.py    — Image gallery, arc plans
    pages/partials.py   — HTMX partials (notifications, rating, chapter list)

To migrate existing imports::

    # Before:
    from aiwebnovel.api.routes_pages import router as pages_router

    # After:
    from aiwebnovel.api.pages import router as pages_router
"""

# Re-export router for backwards compatibility
from aiwebnovel.api.pages import router  # noqa: F401

__all__ = ["router"]
