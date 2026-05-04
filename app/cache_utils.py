import hashlib
from typing import Iterable

from fastapi import Request
from fastapi_cache import FastAPICache


def host_scoped_cache_key(
    func,
    namespace: str = "",
    request: Request = None,
    response=None,
    *args,
    **kwargs,
) -> str:
    """
    Stable host-scoped key for cached host endpoints.

    fastapi-cache2 passes `f"{global_prefix}:{decorator_namespace}"` as the
    `namespace` argument here, so the returned key already embeds the prefix.
    Format: `{prefix}:{decorator_namespace}:host:{host_id}:{md5}`

    The `host_id` segment lets invalidate_host_cache_namespaces do a targeted
    SCAN without touching other hosts' keys.
    """
    host = kwargs.get("kwargs", kwargs).get("current_host")
    host_id = getattr(host, "id", "anon")
    path = request.url.path if request is not None else f"/{func.__name__}"
    query = str(request.query_params) if request is not None else ""
    raw = f"{namespace}:{func.__module__}:{func.__name__}:{host_id}:{path}:{query}"
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:host:{host_id}:{digest}"


async def invalidate_host_cache_namespaces(host_id: int, namespaces: Iterable[str]) -> None:
    """
    Best-effort cache invalidation for host-scoped keys.
    Works for Redis backend and in-memory fallback backend.

    The SCAN pattern uses the global FastAPICache prefix explicitly so it matches
    the exact keys written by host_scoped_cache_key (which receives the combined
    `f"{prefix}:{namespace}"` string from the @cache decorator).
    """
    backend = FastAPICache.get_backend()
    if backend is None:
        return

    unique_namespaces = [ns for ns in set(namespaces) if ns]
    if not unique_namespaces:
        return

    # The decorator passes f"{prefix}:{namespace}" to the key builder, so the
    # stored key starts with that combined string.  Build patterns that match it
    # exactly rather than relying on a leading wildcard.
    cache_prefix = FastAPICache.get_prefix()  # e.g. "opa-cache:"

    redis_client = getattr(backend, "redis", None)
    if redis_client is not None:
        keys_to_delete = []
        for namespace in unique_namespaces:
            # Exact prefix: "opa-cache::host-booking-details:host:{id}:*"
            pattern = f"{cache_prefix}:{namespace}:host:{host_id}:*"
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=500)
                if keys:
                    keys_to_delete.extend(keys)
                if cursor == 0:
                    break
        if keys_to_delete:
            await redis_client.delete(*keys_to_delete)
        return

    store = getattr(backend, "_store", None)
    if isinstance(store, dict):
        prefixes = [f"{cache_prefix}:{namespace}:host:{host_id}:" for namespace in unique_namespaces]
        for key in list(store.keys()):
            key_str = key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
            if any(p in key_str for p in prefixes):
                store.pop(key, None)
