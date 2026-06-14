"""Request logging middleware with structured output and request-id tracing."""

import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("notero.access")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request-id to every request and log structured access records."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            latency = time.perf_counter() - start
            logger.error(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "latency_ms": round(latency * 1000, 2),
                    "error": str(exc),
                },
            )
            raise

        latency = time.perf_counter() - start
        response.headers["X-Request-ID"] = request_id

        status_code = response.status_code
        log_level = logging.WARNING if status_code >= 400 else logging.INFO
        logger.log(
            log_level,
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "latency_ms": round(latency * 1000, 2),
                "client_ip": request.client.host if request.client else None,
            },
        )
        return response
