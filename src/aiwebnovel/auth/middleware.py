"""Authentication, rate limiting, and CSRF middleware.

- AnonymousReaderMiddleware: Sets anonymous reader cookie if not present.
- RateLimitMiddleware: Redis sliding window rate limiter.
- CsrfMiddleware: Double-submit cookie CSRF protection.
"""

from __future__ import annotations

import re
import secrets
import uuid
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()

READER_COOKIE_NAME = "aiwn_reader_id"
READER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

# Regex for generation endpoints: /api/novels/{id}/generate or similar
_GENERATE_RE = re.compile(r"^(/api)?/novels/\d+/(generate|world/generate)")


class AnonymousReaderMiddleware(BaseHTTPMiddleware):
    """Sets an anonymous reader cookie if one is not already present.

    This gives every visitor a stable identity for:
    - Tracking reading progress and bookmarks
    - Reader influence (Oracle, Butterfly choices)
    - Rate limiting at the reader tier

    The cookie is a UUID stored for 1 year. Readers can optionally
    claim their anonymous profile by creating an account.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        reader_id = request.cookies.get(READER_COOKIE_NAME)

        if not reader_id:
            reader_id = str(uuid.uuid4())
            request.state.new_reader_id = reader_id
            logger.debug("anonymous_reader_created", reader_id=reader_id)
        else:
            request.state.new_reader_id = None

        response = await call_next(request)

        # Set cookie on response if we created a new reader
        if request.state.new_reader_id:
            settings = getattr(request.app.state, "settings", None)
            is_prod = settings and not settings.debug
            response.set_cookie(
                key=READER_COOKIE_NAME,
                value=request.state.new_reader_id,
                max_age=READER_COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=is_prod,
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Redis sliding window rate limiter.

    Uses INCR + EXPIRE for a fixed-window approximation per tier.
    Tiers are classified by request path; limits come from Settings.
    Gracefully passes traffic through when Redis is unavailable.
    """

    @staticmethod
    def _classify_tier(path: str, method: str = "GET") -> str:
        """Map a request path + method to a rate-limit tier."""
        # Auth mutations (login/register POST) — strictest limit
        if method == "POST" and (
            path.startswith("/api/auth/") or path.startswith("/auth/")
        ):
            return "auth"
        # BYOK key validation — strict (prevent key enumeration)
        if method == "POST" and path.startswith("/api/dashboard/keys"):
            return "key_validation"
        # Generation endpoints — very strict (POST only, not status polling)
        if method == "POST" and _GENERATE_RE.match(path):
            return "generation"
        # Static assets, images, and health — exempt (no rate limit)
        if path.startswith(("/static/", "/assets/", "/health", "/partials/")):
            return "exempt"
        # API JSON endpoints
        if path.startswith("/api/"):
            return "api"
        # Everything else is page browsing (HTML pages)
        return "browse"

    @staticmethod
    def _get_identifier(request: Request) -> str:
        """Return user_id from JWT cookie or fall back to client IP."""
        from aiwebnovel.auth.jwt import decode_access_token

        token = request.cookies.get("aiwn_token")
        if token:
            try:
                settings = getattr(request.app.state, "settings", None)
                if settings:
                    payload = decode_access_token(
                        token=token,
                        secret_key=settings.jwt_secret_key,
                        algorithm=settings.jwt_algorithm,
                    )
                    uid = payload.get("user_id")
                    if uid is not None:
                        return str(uid)
            # Intentional broad catch: JWT decode best-effort
            # for rate limit identity
            except Exception:
                pass
        return request.client.host if request.client else "unknown"

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return await call_next(request)

        settings = getattr(request.app.state, "settings", None)
        if settings is None:
            return await call_next(request)

        if settings.debug:
            logger.debug("rate_limiting_bypassed_debug_mode")
            return await call_next(request)

        tier = self._classify_tier(request.url.path, request.method)
        if tier == "exempt":
            return await call_next(request)
        identifier = self._get_identifier(request)
        key = f"ratelimit:{tier}:{identifier}"

        tier_limits = {
            "auth": settings.rate_limit_auth,
            "key_validation": settings.rate_limit_key_validation,
            "generation": settings.rate_limit_generation,
            "browse": settings.rate_limit_browse,
            "api": settings.rate_limit_api,
        }
        limit = tier_limits.get(tier, settings.rate_limit_api)

        try:
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, 60)
            if current > limit:
                ttl = await redis.ttl(key)
                retry_after = max(ttl, 1)
                logger.warning(
                    "rate_limit_exceeded",
                    tier=tier,
                    identifier=identifier,
                    current=current,
                    limit=limit,
                )
                return _rate_limit_response(request, retry_after)
        # Intentional broad catch: rate limiting graceful
        # fallback on Redis errors
        except Exception:
            logger.debug("rate_limit_redis_error", tier=tier, exc_info=True)

        return await call_next(request)


# ---------------------------------------------------------------------------
# CSRF Protection
# ---------------------------------------------------------------------------

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_CSRF_EXEMPT_PREFIXES = ("/static/", "/assets/", "/health")


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection.

    On every request, ensures a ``csrf_token`` cookie exists (readable by JS)
    and stores the value in ``request.state.csrf_token`` for template rendering.

    On mutating methods (POST/PUT/DELETE/PATCH), validates that the submitted
    token (via ``X-CSRF-Token`` header or ``csrf_token`` form field) matches
    the cookie value.  Requests with ``Authorization: Bearer`` are exempt
    (they don't rely on cookie auth).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        existing_token = request.cookies.get(CSRF_COOKIE_NAME)
        csrf_token = existing_token or secrets.token_hex(32)
        request.state.csrf_token = csrf_token

        # --- Validate on mutating methods ---
        if request.method not in _CSRF_SAFE_METHODS:
            path = request.url.path
            content_type = request.headers.get("content-type", "")

            # Only enforce CSRF for browser-submittable content types
            # (urlencoded / multipart).  JSON and other types require JS,
            # which is gated by CORS.  Bearer-auth and static paths are
            # also exempt.
            is_form = (
                "application/x-www-form-urlencoded" in content_type
                or "multipart/form-data" in content_type
            )
            exempt = (
                not is_form
                or any(path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES)
                or request.headers.get("authorization", "").lower().startswith(
                    "bearer "
                )
            )

            if not exempt:
                if not existing_token:
                    logger.warning("csrf_cookie_missing", path=path)
                    return _csrf_error_response(request)

                # Check header first (HTMX / JS), then form field
                submitted = request.headers.get(CSRF_HEADER_NAME)
                if not submitted:
                    body = await request.body()
                    form_data = parse_qs(body.decode())
                    tokens = form_data.get(CSRF_FORM_FIELD, [])
                    submitted = tokens[0] if tokens else None

                if not submitted or not secrets.compare_digest(
                    submitted, existing_token
                ):
                    logger.warning(
                        "csrf_validation_failed",
                        path=path,
                        method=request.method,
                    )
                    return _csrf_error_response(request)

        response = await call_next(request)

        # Set cookie if it wasn't already present
        if not existing_token:
            settings = getattr(request.app.state, "settings", None)
            is_prod = settings and not settings.debug
            response.set_cookie(
                CSRF_COOKIE_NAME,
                csrf_token,
                httponly=False,  # JS must read the value
                samesite="lax",
                secure=is_prod,
                path="/",
            )

        return response


def _rate_limit_response(request: Request, retry_after: int) -> Response:
    """Return 429 in the format the client expects (HTML vs JSON)."""
    headers = {
        "Retry-After": str(retry_after),
        "Cache-Control": "no-store",
    }
    if "text/html" in request.headers.get("accept", ""):
        templates = getattr(request.app.state, "templates", None)
        if templates:
            return templates.TemplateResponse(
                "pages/429.html",
                {
                    "request": request,
                    "current_author": None,
                    "retry_after": retry_after,
                },
                status_code=429,
                headers=headers,
            )
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"},
        headers=headers,
    )


def _csrf_error_response(request: Request) -> Response:
    """Return 403 in the format the client expects (HTML vs JSON)."""
    if "text/html" in request.headers.get("accept", ""):
        return Response(
            "CSRF validation failed", status_code=403, media_type="text/plain"
        )
    return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)
