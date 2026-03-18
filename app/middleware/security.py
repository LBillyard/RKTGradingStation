"""Security middleware for auth enforcement and error sanitization."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Paths that do NOT require authentication
AUTH_EXEMPT_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/status",
    "/api/health",
    "/api/docs",
    "/api/docs/oauth2-redirect",
    "/api/openapi.json",
    "/api/agent/version",
    "/api/agent/download",
    "/api/slab/verify",
})

# Path prefixes that never need auth (static assets, SPA shell)
NO_AUTH_PREFIXES = ("/static/", "/data/", "/api/docs")


class SecurityMiddleware(BaseHTTPMiddleware):
    """Enforce authentication on /api/* routes and sanitize 500 errors."""

    def __init__(self, app, debug: bool = False):
        super().__init__(app)
        self.debug = debug

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # --- Auth enforcement for API routes ---
        if path.startswith("/api/") and not self._is_exempt(path):
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    {"detail": "Authentication required"},
                    status_code=401,
                )
            token = auth_header[7:]
            from app.api.routes_auth import _verify_token
            payload = _verify_token(token)
            if payload is None:
                return JSONResponse(
                    {"detail": "Invalid or expired token"},
                    status_code=401,
                )

        # --- Call the actual route ---
        response = await call_next(request)

        # --- Error sanitization in production ---
        if not self.debug and response.status_code >= 500:
            logger.error(
                "500 error on %s %s (status %d)",
                request.method, path, response.status_code,
            )
            return JSONResponse(
                {"detail": "Internal server error"},
                status_code=500,
            )

        return response

    @staticmethod
    def _is_exempt(path: str) -> bool:
        if path in AUTH_EXEMPT_PATHS:
            return True
        for prefix in NO_AUTH_PREFIXES:
            if path.startswith(prefix):
                return True
        return False
