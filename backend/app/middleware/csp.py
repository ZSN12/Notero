"""Content-Security-Policy middleware.

Provides a baseline CSP that can be tightened further as the frontend
assets and third-party dependencies are audited.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Baseline CSP for a Vite + React SPA.
# 'unsafe-inline' for scripts/styles is required until a full nonce/hash
# strategy is implemented. This is still a net win over no CSP.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class CSPMiddleware(BaseHTTPMiddleware):
    """Inject Content-Security-Policy header into every response."""

    def __init__(self, app, policy: str | None = None):
        super().__init__(app)
        self.policy = policy or DEFAULT_CSP

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = self.policy
        return response
