"""Shared Redis client for rate limiting, login locks, and caching."""

import os
import logging

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_redis_client = None


def get_redis():
    """Lazy-init singleton Redis client. Returns None if Redis is unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    try:
        import redis as redis_lib
        _redis_client = redis_lib.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
        logger.info("Redis connected (%s)", REDIS_URL)
    except Exception as e:
        logger.warning("Redis unavailable (%s): %s", REDIS_URL, e)
        _redis_client = None
    return _redis_client


def redis_available() -> bool:
    return get_redis() is not None
