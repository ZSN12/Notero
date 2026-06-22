"""Distributed login failure tracker backed by Redis (with in-memory fallback)."""

import json
import logging
import time
import threading
from app.core.redis_client import get_redis, redis_available

logger = logging.getLogger(__name__)

MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_DURATION = 15 * 60  # 15 minutes

# In-memory fallback for local dev without Redis
_memory_attempts: dict[str, dict] = {}
_memory_lock = threading.Lock()


def _redis_key(email: str) -> str:
    return f"login_lock:{email}"


def get_attempts(email: str) -> dict | None:
    """Fetch current attempt info for an email. Returns None if no record."""
    if redis_available():
        r = get_redis()
        if r is None:
            pass  # fallthrough to memory
        else:
            try:
                data = r.get(_redis_key(email))
                if data:
                    return json.loads(data)
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)
    with _memory_lock:
        return _memory_attempts.get(email)


def record_failure(email: str) -> tuple[int, bool]:
    """Record a failed login attempt.

    Returns:
        (remaining_lock_seconds, is_locked_now)
    """
    now = time.time()

    if redis_available():
        r = get_redis()
        if r is not None:
            try:
                key = _redis_key(email)
                data = r.get(key)
                count = 1
                locked_until = 0
                if data:
                    info = json.loads(data)
                    count = info.get("count", 0) + 1
                    locked_until = info.get("locked_until", 0)
                if count >= MAX_LOGIN_ATTEMPTS:
                    locked_until = now + LOGIN_LOCK_DURATION
                r.setex(key, LOGIN_LOCK_DURATION, json.dumps({"count": count, "locked_until": locked_until}))
                if locked_until > now:
                    return int(locked_until - now), True
                return 0, False
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)  # fallthrough to memory

    with _memory_lock:
        current = _memory_attempts.get(email, {"count": 0, "locked_until": 0})
        current["count"] = current.get("count", 0) + 1
        if current["count"] >= MAX_LOGIN_ATTEMPTS:
            current["locked_until"] = now + LOGIN_LOCK_DURATION
        _memory_attempts[email] = current
        if current["locked_until"] > now:
            return int(current["locked_until"] - now), True
        return 0, False


def clear_attempts(email: str) -> None:
    """Clear attempts after a successful login."""
    if redis_available():
        r = get_redis()
        if r is not None:
            try:
                r.delete(_redis_key(email))
                return
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)
    with _memory_lock:
        _memory_attempts.pop(email, None)


def reset_login_attempts_for_tests() -> None:
    """Clear all in-memory login attempts. Used by test fixtures only."""
    with _memory_lock:
        _memory_attempts.clear()
