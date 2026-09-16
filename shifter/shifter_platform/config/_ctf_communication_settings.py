"""Deployment-owned settings for scoped CTF communications (ADR-051, #2048; engine #2098).

Typed, bounded, server-owned operational policy: retention windows, safe-content
link hosts, and the delivery-engine worker / backpressure / metrics knobs. Every
value fails loudly at startup on a malformed or out-of-range input rather than
silently weakening a policy, and the engine knobs are additionally validated for
their relationships (e.g. a transport timeout must fit inside its lease). None ever
carries a campaign, recipient, body, or secret.
"""

from __future__ import annotations

import os
import re

from django.core.exceptions import ImproperlyConfigured

__all__ = [
    "CTF_COMMUNICATION_ALLOWED_LINK_HOSTS",
    "CTF_COMMUNICATION_BACKOFF_BASE_SECONDS",
    "CTF_COMMUNICATION_BACKOFF_CAP_SECONDS",
    "CTF_COMMUNICATION_BACKOFF_JITTER_FRACTION",
    "CTF_COMMUNICATION_MAX_ATTEMPTS",
    "CTF_COMMUNICATION_MAX_AUDIENCE",
    "CTF_COMMUNICATION_MAX_ELAPSED_SECONDS",
    "CTF_COMMUNICATION_MAX_OUTSTANDING_GLOBAL",
    "CTF_COMMUNICATION_MAX_OUTSTANDING_PER_EVENT",
    "CTF_COMMUNICATION_MAX_OUTSTANDING_PER_WORKSPACE",
    "CTF_COMMUNICATION_METRICS_NAMESPACE",
    "CTF_COMMUNICATION_RATE_GLOBAL",
    "CTF_COMMUNICATION_RATE_PER_ACTOR",
    "CTF_COMMUNICATION_RATE_PER_WORKSPACE",
    "CTF_COMMUNICATION_RATE_WINDOW_SECONDS",
    "CTF_COMMUNICATION_RELEASE_GRACE_MINUTES",
    "CTF_COMMUNICATION_RETENTION_DAYS",
    "CTF_COMMUNICATION_TRANSPORT_TIMEOUT_SECONDS",
    "CTF_COMMUNICATION_WORKER_BATCH_SIZE",
    "CTF_COMMUNICATION_WORKER_LEASE_SECONDS",
    "CTF_COMMUNICATION_WORKER_PER_EVENT_CAP",
]

_DEFAULT_RETENTION_DAYS = 90
_MIN_RETENTION_DAYS = 1
_MAX_RETENTION_DAYS = 365

# Delivery-engine metrics namespace: a bounded provider-agnostic label prefix.
_METRICS_NAMESPACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(/[A-Za-z][A-Za-z0-9]*)*$")

# A bare, normalized hostname: labels of letters/digits/hyphens joined by dots.
# Deliberately excludes schemes, paths, ports, credentials, and whitespace so a
# link-host allowlist entry cannot smuggle a scheme or path into the policy.
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")


def _parse_retention_days(raw: str) -> int:
    """Parse and bound the retention window in days (fail-loud)."""
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError) as exc:
        raise ImproperlyConfigured("SHIFTER_CTF_COMMUNICATION_RETENTION_DAYS must be an integer") from exc
    if not _MIN_RETENTION_DAYS <= value <= _MAX_RETENTION_DAYS:
        raise ImproperlyConfigured(
            f"SHIFTER_CTF_COMMUNICATION_RETENTION_DAYS must be between {_MIN_RETENTION_DAYS} and {_MAX_RETENTION_DAYS}"
        )
    return value


def _parse_allowed_link_hosts(raw: str) -> frozenset[str]:
    """Parse a comma-separated, normalized host allowlist (fail-loud).

    An empty value means no external link hosts are allowed (relative links only).
    """
    hosts: set[str] = set()
    for entry in (raw or "").split(","):
        normalized = entry.strip().lower()
        if not normalized:
            continue
        if not _HOSTNAME_RE.match(normalized):
            raise ImproperlyConfigured(
                f"SHIFTER_CTF_COMMUNICATION_ALLOWED_LINK_HOSTS contains an invalid host: {entry.strip()!r}"
            )
        hosts.add(normalized)
    return frozenset(hosts)


def _parse_int(env_name: str, default: int, minimum: int, maximum: int) -> int:
    """Parse and bound an integer env var (fail-loud)."""
    raw = os.environ.get(env_name, str(default))
    try:
        value = int(str(raw).strip())
    except (ValueError, AttributeError) as exc:
        raise ImproperlyConfigured(f"{env_name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ImproperlyConfigured(f"{env_name} must be between {minimum} and {maximum}")
    return value


def _parse_float(env_name: str, default: float, minimum: float, maximum: float) -> float:
    """Parse and bound a float env var (fail-loud)."""
    raw = os.environ.get(env_name, str(default))
    try:
        value = float(str(raw).strip())
    except (ValueError, AttributeError) as exc:
        raise ImproperlyConfigured(f"{env_name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ImproperlyConfigured(f"{env_name} must be between {minimum} and {maximum}")
    return value


def _parse_metrics_namespace(raw: str) -> str:
    """Validate the metrics namespace as a bounded provider-agnostic label prefix."""
    value = (raw or "").strip()
    if not _METRICS_NAMESPACE_RE.match(value) or len(value) > 64:
        raise ImproperlyConfigured(
            "SHIFTER_CTF_COMMUNICATION_METRICS_NAMESPACE must be a short slash-separated identifier"
        )
    return value


CTF_COMMUNICATION_RETENTION_DAYS = _parse_retention_days(
    os.environ.get("SHIFTER_CTF_COMMUNICATION_RETENTION_DAYS", str(_DEFAULT_RETENTION_DAYS))
)
CTF_COMMUNICATION_ALLOWED_LINK_HOSTS = _parse_allowed_link_hosts(
    os.environ.get("SHIFTER_CTF_COMMUNICATION_ALLOWED_LINK_HOSTS", "")
)

# --- Delivery-engine worker policy (#2098) -------------------------------------
CTF_COMMUNICATION_WORKER_BATCH_SIZE = _parse_int("SHIFTER_CTF_COMMUNICATION_WORKER_BATCH_SIZE", 100, 1, 10000)
CTF_COMMUNICATION_WORKER_PER_EVENT_CAP = _parse_int("SHIFTER_CTF_COMMUNICATION_WORKER_PER_EVENT_CAP", 25, 1, 10000)
CTF_COMMUNICATION_WORKER_LEASE_SECONDS = _parse_int("SHIFTER_CTF_COMMUNICATION_WORKER_LEASE_SECONDS", 120, 5, 3600)
CTF_COMMUNICATION_TRANSPORT_TIMEOUT_SECONDS = _parse_int(
    "SHIFTER_CTF_COMMUNICATION_TRANSPORT_TIMEOUT_SECONDS", 10, 1, 300
)
CTF_COMMUNICATION_MAX_ATTEMPTS = _parse_int("SHIFTER_CTF_COMMUNICATION_MAX_ATTEMPTS", 6, 1, 100)
CTF_COMMUNICATION_MAX_ELAPSED_SECONDS = _parse_int("SHIFTER_CTF_COMMUNICATION_MAX_ELAPSED_SECONDS", 86400, 60, 2592000)
CTF_COMMUNICATION_BACKOFF_BASE_SECONDS = _parse_int("SHIFTER_CTF_COMMUNICATION_BACKOFF_BASE_SECONDS", 30, 1, 3600)
CTF_COMMUNICATION_BACKOFF_CAP_SECONDS = _parse_int("SHIFTER_CTF_COMMUNICATION_BACKOFF_CAP_SECONDS", 3600, 1, 86400)
CTF_COMMUNICATION_BACKOFF_JITTER_FRACTION = _parse_float(
    "SHIFTER_CTF_COMMUNICATION_BACKOFF_JITTER_FRACTION", 0.25, 0.0, 1.0
)

# --- Admission backpressure policy (#2098) -------------------------------------
CTF_COMMUNICATION_MAX_AUDIENCE = _parse_int("SHIFTER_CTF_COMMUNICATION_MAX_AUDIENCE", 5000, 1, 1000000)
CTF_COMMUNICATION_RATE_WINDOW_SECONDS = _parse_int("SHIFTER_CTF_COMMUNICATION_RATE_WINDOW_SECONDS", 60, 1, 3600)
CTF_COMMUNICATION_RATE_PER_ACTOR = _parse_int("SHIFTER_CTF_COMMUNICATION_RATE_PER_ACTOR", 30, 1, 100000)
CTF_COMMUNICATION_RATE_PER_WORKSPACE = _parse_int("SHIFTER_CTF_COMMUNICATION_RATE_PER_WORKSPACE", 120, 1, 1000000)
CTF_COMMUNICATION_RATE_GLOBAL = _parse_int("SHIFTER_CTF_COMMUNICATION_RATE_GLOBAL", 600, 1, 10000000)
CTF_COMMUNICATION_MAX_OUTSTANDING_PER_EVENT = _parse_int(
    "SHIFTER_CTF_COMMUNICATION_MAX_OUTSTANDING_PER_EVENT", 20000, 1, 10000000
)
CTF_COMMUNICATION_MAX_OUTSTANDING_PER_WORKSPACE = _parse_int(
    "SHIFTER_CTF_COMMUNICATION_MAX_OUTSTANDING_PER_WORKSPACE", 100000, 1, 100000000
)
CTF_COMMUNICATION_MAX_OUTSTANDING_GLOBAL = _parse_int(
    "SHIFTER_CTF_COMMUNICATION_MAX_OUTSTANDING_GLOBAL", 500000, 1, 1000000000
)

# --- Scheduler due-time / lateness policy (#2099) ------------------------------
# The bounded grace window (minutes) a scheduled communication may still be
# released after its authored due time (backlog, restart, clock skew). Picked up
# within the window -> released; past it -> the intent is EXPIRED (a durable
# no-work outcome), never delivered late as though it were on time. 0 means strict
# due-only. Absolute due time and this lateness bound are kept distinct from the
# delivery worker's retry deadlines.
CTF_COMMUNICATION_RELEASE_GRACE_MINUTES = _parse_int("SHIFTER_CTF_COMMUNICATION_RELEASE_GRACE_MINUTES", 20, 0, 10080)

# --- Metrics -------------------------------------------------------------------
CTF_COMMUNICATION_METRICS_NAMESPACE = _parse_metrics_namespace(
    os.environ.get("SHIFTER_CTF_COMMUNICATION_METRICS_NAMESPACE", "Shifter/CtfCommunication")
)


def _validate_engine_relationships() -> None:
    """Reject combinations that would misbehave even when each value is in range."""
    if CTF_COMMUNICATION_TRANSPORT_TIMEOUT_SECONDS >= CTF_COMMUNICATION_WORKER_LEASE_SECONDS:
        raise ImproperlyConfigured(
            "SHIFTER_CTF_COMMUNICATION_TRANSPORT_TIMEOUT_SECONDS must be strictly less than "
            "SHIFTER_CTF_COMMUNICATION_WORKER_LEASE_SECONDS so a transport call finishes inside its lease"
        )
    if CTF_COMMUNICATION_BACKOFF_BASE_SECONDS > CTF_COMMUNICATION_BACKOFF_CAP_SECONDS:
        raise ImproperlyConfigured(
            "SHIFTER_CTF_COMMUNICATION_BACKOFF_BASE_SECONDS must not exceed "
            "SHIFTER_CTF_COMMUNICATION_BACKOFF_CAP_SECONDS"
        )
    if CTF_COMMUNICATION_WORKER_PER_EVENT_CAP > CTF_COMMUNICATION_WORKER_BATCH_SIZE:
        raise ImproperlyConfigured(
            "SHIFTER_CTF_COMMUNICATION_WORKER_PER_EVENT_CAP must not exceed SHIFTER_CTF_COMMUNICATION_WORKER_BATCH_SIZE"
        )


_validate_engine_relationships()
