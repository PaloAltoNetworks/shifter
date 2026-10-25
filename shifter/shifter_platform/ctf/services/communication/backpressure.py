"""Admission backpressure for scoped communications (ADR-051-R12, #2098).

Two complementary controls, because a rate counter alone cannot bound a durable
backlog:

* fixed-window abuse limits (per actor, per workspace, global) via the shared,
  atomic ``consume_fixed_window`` primitive; and
* a durable outstanding-work reservation (per event, per workspace, global) counted
  from the ledger and serialized against concurrent admissions with a per-workspace
  PostgreSQL advisory lock, plus a fan-out (audience-size) cap checked before any
  acceptance is reported.

Enforcement is fail-closed: an over-budget request raises a bounded
``CTFCommunicationError`` and emits a closed-label denial metric; it never silently
downgrades or partially admits. The typed, relationally-validated owner of the
numeric knobs is ``config._ctf_communication_settings``; the ``getattr`` defaults
here keep the module importable and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Count

from ctf.enums_communication import DeliveryStatus
from ctf.exceptions import CTFCommunicationError
from ctf.services.communication import metrics

# Namespace for per-workspace advisory locks so communication admission cannot
# collide with any other advisory-lock user.
# Arbitrary stable int namespacing issue #2098 admission advisory locks.
_ADVISORY_LOCK_NAMESPACE = 20498
# Single global key so all admissions serialize their durable outstanding-work checks.
_GLOBAL_ADMISSION_KEY = 0

_NON_TERMINAL = (
    DeliveryStatus.QUEUED.value,
    DeliveryStatus.CLAIMED.value,
    DeliveryStatus.RETRY_DUE.value,
)

_DEFAULTS = {
    "CTF_COMMUNICATION_MAX_AUDIENCE": 5000,
    "CTF_COMMUNICATION_RATE_WINDOW_SECONDS": 60,
    "CTF_COMMUNICATION_RATE_PER_ACTOR": 30,
    "CTF_COMMUNICATION_RATE_PER_WORKSPACE": 120,
    "CTF_COMMUNICATION_RATE_GLOBAL": 600,
    "CTF_COMMUNICATION_MAX_OUTSTANDING_PER_EVENT": 20000,
    "CTF_COMMUNICATION_MAX_OUTSTANDING_PER_WORKSPACE": 100000,
    "CTF_COMMUNICATION_MAX_OUTSTANDING_GLOBAL": 500000,
}


def _setting(name: str) -> int:
    """Return a bounded admission setting, defaulting when the settings owner is absent."""
    return int(getattr(settings, name, _DEFAULTS[name]))


@dataclass(frozen=True)
class AdmissionRequest:
    """The bounded facts admission control needs to accept or reject one intent."""

    actor_user_id: int | None
    workspace_id: int
    event_ids: frozenset[UUID]
    audience_size: int
    channel_count: int


def _deny(scope_class: str, code: str, message: str) -> None:
    """Emit a closed-label denial metric and raise a bounded, fail-closed error."""
    metrics.emit_admission_denied(scope_class=scope_class)
    raise CTFCommunicationError(message, code=code)


def _consume(scope_class: str, key: str, limit: int, window: int, code: str, message: str) -> None:
    """Fail closed when a fixed-window scope exceeds its per-window limit."""
    from shared.rate_limit import consume_fixed_window

    try:
        used = consume_fixed_window(cache, f"ctf:comm:admit:{key}", window)
    except Exception:
        raise CTFCommunicationError(
            "Communication admission unavailable", code="CTF_COMMUNICATION_ADMISSION_UNAVAILABLE"
        ) from None
    if used > limit:
        _deny(scope_class, code, message)


def _outstanding(scope_filter: dict[str, object]) -> int:
    """Count non-terminal (pending + in-flight) delivery commands in the given scope."""
    from ctf.models import DeliveryAttempt

    return (
        DeliveryAttempt.objects.filter(status__in=_NON_TERMINAL, **scope_filter).aggregate(n=Count("id")).get("n") or 0
    )


def _serialize_admission() -> None:
    """Serialize the durable outstanding-work checks globally on PostgreSQL.

    A single global advisory lock (constant key) serializes every admission's
    durable-reservation section, so the workspace, global, AND per-event counts are
    all observed and reserved consistently -- a per-workspace lock would let
    concurrent admissions in different workspaces both pass the shared global cap.
    Held only for the bounded count queries; released at transaction commit. A
    no-op on other backends (SQLite serializes writes already), so the unit lane
    exercises the count logic without the lock. Must run inside the caller's
    transaction.
    """
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_ADVISORY_LOCK_NAMESPACE, _GLOBAL_ADMISSION_KEY])


# Admission-denial codes that are transient (clearing the rate window or draining
# the backlog recovers the occurrence). Every other admission/authorization denial
# is permanent for this occurrence. Callers that run at due time use this to retry
# transient pressure within the grace window instead of discarding the occurrence.
RETRYABLE_ADMISSION_CODES = frozenset({"CTF_COMMUNICATION_RATE_LIMITED", "CTF_COMMUNICATION_BACKLOG_FULL"})


def enforce_admission(request: AdmissionRequest) -> None:
    """Enforce fan-out, rate, and durable outstanding-work budgets, fail-closed.

    MUST be called inside the release transaction (it relies on the caller's
    transaction for advisory-lock scope and count consistency).
    """
    projected = max(request.audience_size, 0) * max(request.channel_count, 1)

    # 1. Fan-out cost: reject an oversized intent before reporting acceptance.
    if request.audience_size > _setting("CTF_COMMUNICATION_MAX_AUDIENCE"):
        _deny("global", "CTF_COMMUNICATION_AUDIENCE_TOO_LARGE", "Audience exceeds the per-intent fan-out limit")

    enforce_operation_rate(request.actor_user_id, request.workspace_id)

    # 3. Durable outstanding-work reservation. Serialized globally so the workspace,
    # global, and per-event counts are all consistent hard bounds, and every check
    # adds this intent's projected work before comparing to its cap.
    _serialize_admission()
    if _outstanding({"intent__campaign__workspace_id": int(request.workspace_id)}) + projected > _setting(
        "CTF_COMMUNICATION_MAX_OUTSTANDING_PER_WORKSPACE"
    ):
        _deny(
            "workspace",
            "CTF_COMMUNICATION_BACKLOG_FULL",
            "Workspace has too much outstanding delivery work; retry later",
        )
    if _outstanding({}) + projected > _setting("CTF_COMMUNICATION_MAX_OUTSTANDING_GLOBAL"):
        _deny("global", "CTF_COMMUNICATION_BACKLOG_FULL", "The platform delivery backlog is full; retry later")
    # Per-event: add the projected fan-out for that event. audience_size is the
    # cross-event total, so use it as a conservative per-event upper bound (exact
    # for the common single-event campaign; never under-counts for multi-event).
    per_event_cap = _setting("CTF_COMMUNICATION_MAX_OUTSTANDING_PER_EVENT")
    for event_id in request.event_ids:
        if _outstanding({"snapshot__event_id": event_id}) + projected > per_event_cap:
            _deny(
                "event",
                "CTF_COMMUNICATION_BACKLOG_FULL",
                "This event has too much outstanding delivery work; retry later",
            )


def enforce_operation_rate(actor_user_id: int | None, workspace_id: int) -> None:
    """Bound draft/revision operations using the shared admission rate budgets."""
    # 2. Fixed-window abuse limits (atomic, distributed).
    window = _setting("CTF_COMMUNICATION_RATE_WINDOW_SECONDS")
    if actor_user_id is not None:
        _consume(
            "actor",
            f"actor:{int(actor_user_id)}",
            _setting("CTF_COMMUNICATION_RATE_PER_ACTOR"),
            window,
            "CTF_COMMUNICATION_RATE_LIMITED",
            "Too many communications from this actor; retry later",
        )
    _consume(
        "workspace",
        f"workspace:{int(workspace_id)}",
        _setting("CTF_COMMUNICATION_RATE_PER_WORKSPACE"),
        window,
        "CTF_COMMUNICATION_RATE_LIMITED",
        "Too many communications in this workspace; retry later",
    )
    _consume(
        "global",
        "global",
        _setting("CTF_COMMUNICATION_RATE_GLOBAL"),
        window,
        "CTF_COMMUNICATION_RATE_LIMITED",
        "The platform is shedding communication load; retry later",
    )
