"""Atomic fixed-window counters shared by admission policies."""

from __future__ import annotations

from typing import Any

from django.core.cache.backends.base import BaseCache

_LUA_INCR_EXPIRE = (
    "local c = redis.call('INCR', KEYS[1])\n"
    "if c == 1 or redis.call('TTL', KEYS[1]) == -1 then\n"
    "  redis.call('EXPIRE', KEYS[1], ARGV[1])\n"
    "end\n"
    "return c"
)


def _redis_client(cache: BaseCache, made_key: str) -> Any | None:
    """Return the native Redis client when the cache backend exposes one."""
    get_client = getattr(getattr(cache, "_cache", None), "get_client", None)
    if get_client is None:
        return None
    try:
        return get_client(made_key, write=True)
    except Exception:
        return None


def consume_fixed_window(cache: BaseCache, key: str, window: int) -> int:
    """Atomically increment a fixed-window counter and retain its TTL."""
    made_key = cache.make_key(key, version=cache.version)
    client = _redis_client(cache, made_key)
    if client is not None:
        return int(client.eval(_LUA_INCR_EXPIRE, 1, made_key, window))
    try:
        cache.add(key, 0, window)
        return int(cache.incr(key))
    except ValueError:
        cache.set(key, 1, window)
        return 1
