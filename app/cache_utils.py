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
    Includes namespace + host_id so we can invalidate by namespace/host.
    """
    host = kwargs.get("current_host")
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
    """
    backend = FastAPICache.get_backend()
    if backend is None:
        return

    unique_namespaces = [ns for ns in set(namespaces) if ns]
    if not unique_namespaces:
        return

    redis_client = getattr(backend, "redis", None)
    if redis_client is not None:
        keys_to_delete = []
        for namespace in unique_namespaces:
            pattern = f"*{namespace}:host:{host_id}:*"
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
        prefixes = [f"{namespace}:host:{host_id}:" for namespace in unique_namespaces]
        for key in list(store.keys()):
            key_str = key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
            if any(prefix in key_str for prefix in prefixes):
                store.pop(key, None)
