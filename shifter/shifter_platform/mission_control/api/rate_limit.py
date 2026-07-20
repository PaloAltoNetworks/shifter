"""Launch-endpoint admission rate limiting (issue #322).

Backpressure for the two expensive Mission Control launch mutations
(``LaunchRangeView`` and ``NGFWCreateView``) to prevent cascade failures under
load. Each operation enforces two independent fixed-window budgets:

- **actor** budget — caps how often one owner can launch (abuse cap). The actor
  is resolved via :func:`mission_control_actor_user`, so a session user and an
  API token owned by the same user share one budget.
- **fleet** budget — caps accepted launch pressure across all users (the actual
  cascade guard). A per-actor limit alone cannot stop a many-user surge.

Admission runs as a DRF throttle (``initial()`` → after authentication and
permission gates, before the serializer/handler), so it charges every
authenticated POST reaching the endpoint — including malformed bodies — and a
rejected request never reaches CMS. Counters are consumed atomically against the
shared ``launch_rate_limit`` cache (Redis in production; see
``config/_cache_settings.py``) using ``add`` + ``incr`` — each is an atomic
server-side operation, so this is not the read-then-write pattern that
over-admits under a burst. Both counters are charged on every request
(conservative: a rejection on one budget still charges the other), which keeps
the two-budget interaction simple and deterministic.

Budget exhaustion raises DRF ``Throttled`` → HTTP 429 with ``Retry-After``,
rendered through the canonical ``shared.api.errors`` envelope (and the legacy
flat envelope on ``/mission-control/...`` routes). An admission-backend outage
fails closed for these two mutations with a bounded 503 + ``Retry-After``
(:class:`LaunchAdmissionUnavailable`) rather than silently admitting.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.cache.backends.base import BaseCache
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from mission_control.api.permissions import mission_control_actor_user
from shared.rate_limit import consume_fixed_window

logger = logging.getLogger(__name__)

LAUNCH_RATE_LIMIT_CACHE_ALIAS = "launch_rate_limit"


class LaunchAdmissionUnavailable(APIException):
    """503 raised when the admission backend is unavailable (fail closed).

    Carries ``wait`` so DRF's exception handler emits a bounded ``Retry-After``,
    exactly as it does for ``Throttled``.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Launch admission is temporarily unavailable. Please retry shortly."
    default_code = "launch_admission_unavailable"

    def __init__(self, wait: float | None = None, detail: object = None, code: str | None = None) -> None:
        self.wait = wait
        super().__init__(detail=detail, code=code)


class _LaunchRateThrottle(BaseThrottle):
    """Base throttle enforcing an actor + fleet budget for one launch operation.

    Subclasses set ``operation`` to a key in ``settings.LAUNCH_RATE_LIMITS``.
    """

    operation: str = ""

    def __init__(self) -> None:
        self._wait_seconds: float | None = None

    def allow_request(self, request: Request, view: APIView) -> bool:
        """Charge the actor + fleet budgets; return False when either is exhausted."""
        policy = self._active_policy(request)
        if policy is None:
            return True
        actor = mission_control_actor_user(request)
        if actor is None or actor.pk is None:
            # Authentication and permission gates run before throttling and
            # already reject an unauthenticated request; with no actor to key on
            # there is nothing to charge.
            return True
        exceeded = self._charge(policy, actor.pk)
        self._wait_seconds = float(max(exceeded)) if exceeded else None
        return not exceeded

    def wait(self) -> float | None:
        """Return the seconds a throttled caller should wait (drives Retry-After)."""
        return self._wait_seconds

    def _active_policy(self, request: Request) -> dict[str, Any] | None:
        """Return this operation's budget policy, or ``None`` when limiting is off."""
        enabled = getattr(settings, "LAUNCH_RATE_LIMIT_ENABLED", False)
        if not enabled or request.method != "POST":
            return None
        return settings.LAUNCH_RATE_LIMITS.get(self.operation)

    def _charge(self, policy: dict[str, Any], actor_pk: object) -> list[int]:
        """Charge both budgets and return the windows of any exceeded budget.

        Returns an empty list when within budget. Raises
        :class:`LaunchAdmissionUnavailable` (503) on an admission-backend outage
        so launch fails closed rather than silently admitting.
        """
        actor_max, actor_window = policy["actor"]["max"], policy["actor"]["window"]
        fleet_max, fleet_window = policy["fleet"]["max"], policy["fleet"]["window"]
        cache = self._cache()
        try:
            actor_count = consume_fixed_window(cache, self._actor_key(actor_pk), actor_window)
            fleet_count = consume_fixed_window(cache, self._fleet_key(), fleet_window)
        except Exception as exc:
            # Any admission-backend error must fail closed for these launch mutations.
            logger.warning(
                "launch admission backend unavailable: operation=%s actor=%s; failing closed",
                self.operation,
                actor_pk,
            )
            raise LaunchAdmissionUnavailable(wait=float(max(actor_window, fleet_window))) from exc

        exceeded: list[int] = []
        if actor_count > actor_max:
            exceeded.append(actor_window)
        if fleet_count > fleet_max:
            exceeded.append(fleet_window)
        if exceeded:
            logger.info(
                "launch admission throttled: operation=%s scope=%s actor=%s wait=%s",
                self.operation,
                "actor" if actor_count > actor_max else "fleet",
                actor_pk,
                max(exceeded),
            )
        return exceeded

    @staticmethod
    def _cache() -> BaseCache:
        from django.core.cache import caches

        return caches[LAUNCH_RATE_LIMIT_CACHE_ALIAS]

    def _actor_key(self, actor_pk: object) -> str:
        return f"launch-rl:{self.operation}:actor:{actor_pk}"

    def _fleet_key(self) -> str:
        return f"launch-rl:{self.operation}:fleet"


class RangeLaunchRateThrottle(_LaunchRateThrottle):
    """Admission throttle for the range launch endpoint (``LaunchRangeView``)."""

    operation = "range"


class NGFWLaunchRateThrottle(_LaunchRateThrottle):
    """Admission throttle for the NGFW create endpoint (``NGFWCreateView``)."""

    operation = "ngfw"
