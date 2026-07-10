"""Engine-side helpers for fetching secrets from the active provider store.

These wrap ``shared.cloud.get_secrets_store()`` so callers do not need to know
which cloud backs the deployment. The helpers fail closed when a reference is
missing or unreadable rather than returning empty strings or silently falling
back to literals.
"""

import logging
import threading
import time
from collections.abc import Callable

from django.conf import settings

from shared.cloud import get_secrets_store
from shared.cloud.exceptions import CloudSecretsError

logger = logging.getLogger(__name__)


class SecretsError(Exception):
    """Error retrieving a secret from the active provider secret store."""


class _SecretCache:
    """Bounded, TTL-bounded, thread-safe cache of resolved secret values.

    Keyed by secret *reference* (ARN / resource path), never by value. Used to
    collapse a per-range connect storm to one provider fetch per reference for
    the TTL window (#929). The cache holds plaintext secret values in process
    memory only; references are the keys and values are never logged. TTL bounds
    staleness so credential rotation under the same reference converges and a
    destroyed range's entries simply expire — there is no durable storage.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        # ``clock`` is injectable so TTL/eviction can be tested deterministically
        # via the public constructor rather than patching the module clock.
        self._clock = clock
        self._lock = threading.Lock()
        # ref -> (expires_at_monotonic, value)
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, ref: str, ttl: int) -> str | None:
        if ttl <= 0:
            return None
        now = self._clock()
        with self._lock:
            entry = self._store.get(ref)
            if entry is not None and entry[0] <= now:
                # Past expiry: drop it and treat as a miss.
                del self._store[ref]
                entry = None
            return entry[1] if entry is not None else None

    def set(self, ref: str, value: str, ttl: int, max_entries: int) -> None:
        if ttl <= 0:
            return
        now = self._clock()
        with self._lock:
            if ref not in self._store and len(self._store) >= max_entries:
                # Evict the entry closest to expiry (effectively the oldest),
                # keeping the working set bounded.
                oldest_ref = min(self._store, key=lambda key: self._store[key][0])
                del self._store[oldest_ref]
            self._store[ref] = (now + ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_secret_cache = _SecretCache()


def clear_secret_cache() -> None:
    """Clear the in-process secret cache (used on shutdown and in tests)."""
    _secret_cache.clear()


def _cache_ttl_seconds() -> int:
    """Return the configured credential-cache TTL in seconds (<= 0 disables it)."""
    return int(getattr(settings, "SECRET_CACHE_TTL_SECONDS", 300))


def _cache_max_entries() -> int:
    """Return the configured maximum number of cached credential entries."""
    return max(1, int(getattr(settings, "SECRET_CACHE_MAX_ENTRIES", 256)))


def _get_cached_secret(secret_ref: str) -> str:
    """Return a secret value, consulting the bounded TTL cache first.

    Only successful fetches are cached; a failed provider fetch propagates the
    ``CloudSecretsError`` to the caller without poisoning the cache.
    """
    ttl = _cache_ttl_seconds()
    cached = _secret_cache.get(secret_ref, ttl)
    if cached is not None:
        return cached
    value = get_secrets_store().get_secret(secret_ref)
    _secret_cache.set(secret_ref, value, ttl, _cache_max_entries())
    return value


def get_ssh_key(secret_arn: str) -> str:
    """Retrieve an SSH private key from the active provider secret store.

    Args:
        secret_arn: The provider-native reference (AWS Secrets Manager ARN or
            GCP Secret Manager resource path) for the SSH private key.

    Returns:
        The SSH private key PEM as a string.

    Raises:
        SecretsError: If the reference is empty or the underlying fetch fails.
    """
    if not secret_arn:
        raise SecretsError("Secret ARN is required")

    try:
        return _get_cached_secret(secret_arn)
    except CloudSecretsError as e:
        logger.exception("Failed to retrieve SSH key secret")
        raise SecretsError(f"Failed to retrieve SSH key: {e}") from e


def get_rdp_password(secret_ref: str) -> str:
    """Retrieve a per-instance RDP password from the active provider secret store.

    The reference is a provider-native identifier — an AWS Secrets Manager
    secret ARN, a GCP Secret Manager resource path
    (``projects/<id>/secrets/<name>``), or any other value the active
    ``SecretsStore`` understands.

    Args:
        secret_ref: The provider-native reference for the RDP password.

    Returns:
        The password value.

    Raises:
        SecretsError: If the reference is empty or the underlying fetch fails.
    """
    if not secret_ref:
        raise SecretsError("Secret reference is required")

    try:
        return _get_cached_secret(secret_ref)
    except CloudSecretsError as e:
        logger.exception("Failed to retrieve RDP password secret")
        raise SecretsError(f"Failed to retrieve RDP password: {e}") from e
