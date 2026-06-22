"""Rate limiting middleware using sliding window algorithm backed by Redis.

Redis is preferred so limits are shared across workers/instances. If Redis is
unavailable, the middleware falls back to an in-process memory window.
"""
import hashlib
import logging
import re
import time
import uuid
from collections import defaultdict
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

# Rate limit rules: each rule is (matcher, max_requests, window_seconds)
# matcher can be:
#   - str: matched with path.startswith(matcher)
#   - re.Pattern: matched with pattern.search(path)
# Rules are checked in order; first match wins.
RATE_LIMITS: list[tuple[str | re.Pattern, int, int]] = [
    ("/api/process/audio-stream", 200, 60),   # 200 requests per minute
    ("/api/process/audio-finish", 5, 60),     # 5 requests per minute
    ("/api/process/audio-batch", 5, 60),      # 5 requests per minute
    ("/api/process/ppt-upload", 5, 60),       # 5 requests per minute
    ("/api/mindmap", 60, 60),                 # 60 mind map requests per minute
    (re.compile(r"^/api/quiz/session/[^/]+/bank"), 10, 60),  # bank rebuild/status - triggers AI, strictest
    ("/api/quiz/session", 30, 60),            # 30 quiz session requests per minute (list/generate/detail/submit)
    ("/api/vector/session", 30, 60),          # 30 vector status/rebuild requests per minute
    ("/api/vector/notebook", 10, 60),         # 10 notebook vector rebuilds per minute
    ("/api/vector/search", 60, 60),           # 60 vector searches per minute
    ("/api/notebooks", 30, 60),               # 30 requests per minute
    (re.compile(r"^/api/sessions/[^/]+/processing-status"), 120, 60),  # processing status polling - generous limit
    ("/api/sessions", 30, 60),                # 30 requests per minute
    ("/api/notes", 30, 60),                   # 30 requests per minute
    ("/api/auth/register", 5, 3600),          # 5 registrations per hour
    ("/api/auth/reset-password", 5, 3600),    # 5 password reset attempts per hour
]


def _matches(path: str, matcher: str | re.Pattern) -> bool:
    """Check if a path matches a rule matcher."""
    if isinstance(matcher, re.Pattern):
        return bool(matcher.search(path))
    return path.startswith(matcher)


def _matcher_key(matcher: str | re.Pattern) -> str:
    """Get a stable string key for a matcher (used in rate limit counters)."""
    if isinstance(matcher, re.Pattern):
        return matcher.pattern
    return matcher


def _redis_key(user_key: str, matcher_key: str) -> str:
    """Redis key for a user/matcher sliding window."""
    return f"ratelimit:{user_key}:{matcher_key}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter per user (by IP for anonymous, by token for authenticated)."""

    def __init__(self, app):
        super().__init__(app)
        # In-process fallback when Redis is unavailable.
        self._memory_requests: dict[tuple[str, str], list[float]] = defaultdict(list)

    def _get_user_key(self, request: Request) -> str:
        """Identify user by Authorization header (stable token digest) or IP address."""
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            # Use SHA-256 of the token so the key is stable across processes.
            # Never put the raw token into Redis keys or logs.
            token = auth[7:].strip()
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            return f"user:{digest}"
        # Prefer X-Forwarded-For / X-Real-IP for reverse-proxy setups
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            ip = xff.split(",")[0].strip()
            if ip:
                return f"ip:{ip}"
        xri = request.headers.get("x-real-ip", "")
        if xri:
            return f"ip:{xri}"
        return f"ip:{request.client.host}" if request.client else "ip:unknown"

    def _check_rate_limit_memory(
        self,
        user_key: str,
        matcher: str | re.Pattern,
        max_req: int,
        window: int,
        now: float,
    ) -> tuple[bool, dict]:
        """In-process sliding window fallback."""
        mkey = _matcher_key(matcher)
        key = (user_key, mkey)
        timestamps = self._memory_requests[key]
        cutoff = now - window
        self._memory_requests[key] = [t for t in timestamps if t > cutoff]
        timestamps = self._memory_requests[key]

        remaining = max_req - len(timestamps)
        reset_time = int(window - (now - timestamps[0])) if timestamps else 0

        if remaining <= 0:
            return False, {
                "X-RateLimit-Limit": str(max_req),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_time),
            }

        timestamps.append(now)
        return True, {
            "X-RateLimit-Limit": str(max_req),
            "X-RateLimit-Remaining": str(remaining - 1),
            "X-RateLimit-Reset": str(reset_time),
        }

    def _check_rate_limit_redis(
        self,
        redis_client,
        user_key: str,
        matcher: str | re.Pattern,
        max_req: int,
        window: int,
        now: float,
    ) -> tuple[bool, dict] | None:
        """Redis sliding window using sorted set. Returns None on Redis error."""
        key = _redis_key(user_key, _matcher_key(matcher))
        window_ms = window * 1000
        # Use millisecond timestamps so multiple requests in the same second still
        # get distinct scores and we can accurately compute the reset time.
        now_ms = int(now * 1000)
        cutoff_ms = now_ms - window_ms
        member = f"{now_ms}:{uuid.uuid4().hex}"

        try:
            pipe = redis_client.pipeline()
            pipe.zremrangebyscore(key, 0, cutoff_ms)
            pipe.zadd(key, {member: now_ms})
            pipe.zcard(key)
            pipe.expire(key, window)
            pipe.zrange(key, 0, 0, withscores=True)
            _, _, count, _, oldest = pipe.execute()
        except Exception as exc:
            logger.warning("rate_limit_redis_failed error=%s", exc)
            return None

        remaining = max_req - count
        reset_time = 0
        if oldest:
            oldest_score = float(oldest[0][1])
            reset_time = max(0, int((oldest_score + window_ms - now_ms) / 1000))

        if remaining < 0:
            # Roll back the just-added member so the window stays accurate.
            try:
                redis_client.zrem(key, member)
            except Exception:
                pass
            return False, {
                "X-RateLimit-Limit": str(max_req),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_time),
            }

        return True, {
            "X-RateLimit-Limit": str(max_req),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_time),
        }

    def _check_rate_limit(self, user_key: str, path: str) -> tuple[bool, dict]:
        """Check if request is within rate limits. Returns (allowed, headers)."""
        now = time.time()

        for matcher, max_req, window in RATE_LIMITS:
            if not _matches(path, matcher):
                continue

            redis_client = None
            try:
                redis_client = get_redis()
            except Exception as exc:
                logger.warning("rate_limit_redis_connect_failed error=%s", exc)

            if redis_client is not None:
                result = self._check_rate_limit_redis(
                    redis_client, user_key, matcher, max_req, window, now
                )
                if result is not None:
                    return result
                # Redis command failed: fall through to memory fallback.
                logger.debug("rate_limit_falling_back_to_memory user_key=%s", user_key)

            return self._check_rate_limit_memory(
                user_key, matcher, max_req, window, now
            )

        return True, {}

    async def dispatch(self, request: Request, call_next):
        user_key = self._get_user_key(request)
        allowed, headers = self._check_rate_limit(user_key, request.url.path)

        if not allowed:
            return Response(
                content='{"detail": "Too many requests. Please try again later."}',
                status_code=429,
                media_type="application/json",
                headers=headers,
            )

        response = await call_next(request)
        for k, v in headers.items():
            response.headers[k] = v
        return response
