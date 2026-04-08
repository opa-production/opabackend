"""
Redis cache initialisation for FastAPI Cache 2.
Call ``init_cache()`` once during application startup.
"""

import logging
import os

logger = logging.getLogger(__name__)


async def init_cache() -> None:
    """Initialise FastAPI Cache with a Redis backend.

    Gracefully falls back (cache disabled) if Redis is unavailable.
    """
    from fastapi_cache import FastAPICache
    from fastapi_cache.backends.redis import RedisBackend

    try:
        import redis.asyncio as redis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url, decode_responses=True)
        FastAPICache.init(
            RedisBackend(redis_client),
            prefix="opa-cache:",
            expire=300,
        )
        logger.info("[CACHE] Redis cache initialised successfully")
    except Exception as exc:
        logger.warning("[CACHE] Redis not available, caching disabled: %s", exc)
        FastAPICache.init(backend=None, prefix="opa-cache:", expire=300)
