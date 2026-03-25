"""Page routes package — drop-in replacement for routes_pages.py.

Combines all domain-specific page route modules into a single ``router``
that registers the exact same routes as the original monolithic file.

Usage in main.py::

    from aiwebnovel.api.pages import router as pages_router
    app.include_router(pages_router, tags=["pages"])
"""

from fastapi import APIRouter

from .auth import router as auth_router
from .browse import router as browse_router
from .chapter import router as chapter_router
from .characters import router as characters_router
from .dashboard import router as dashboard_router
from .gallery import router as gallery_router
from .home import router as home_router
from .novel import router as novel_router
from .partials import router as partials_router
from .world import router as world_router

router = APIRouter()

router.include_router(home_router)
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(browse_router)
router.include_router(novel_router)
router.include_router(world_router)
router.include_router(chapter_router)
router.include_router(characters_router)
router.include_router(gallery_router)
router.include_router(partials_router)
