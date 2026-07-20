"""Failure-safe counter behavior used by private credential delivery."""

from shared.rate_limit import consume_fixed_window


class _FailingRedisPool:
    def get_client(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")


class _FallbackCache:
    version = 1
    _cache = _FailingRedisPool()

    def __init__(self):
        self.value = 0

    def make_key(self, key, version=None):
        return f"v{version}:{key}"

    def add(self, key, value, timeout):
        self.value = value
        return True

    def incr(self, key):
        self.value += 1
        return self.value


class _MissingCounterCache(_FallbackCache):
    _cache = object()

    def incr(self, key):
        raise ValueError("missing counter")

    def set(self, key, value, timeout):
        self.value = value


def test_counter_falls_back_when_native_redis_client_is_unavailable():
    cache = _FallbackCache()

    assert consume_fixed_window(cache, "credential-delivery:1", 60) == 1


def test_counter_initializes_when_backend_reports_a_missing_key():
    cache = _MissingCounterCache()

    assert consume_fixed_window(cache, "credential-delivery:1", 60) == 1
    assert cache.value == 1
