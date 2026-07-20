"""Custom middleware for Shifter platform."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, cast

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings

from config.capacity_metrics import inflight_requests

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from django.http import HttpRequest, HttpResponse

# Paths that bypass ``ALLOWED_HOSTS`` enforcement so AWS ALB / GCP ingress
# health probes (which arrive with the load balancer's internal IP as the
# ``Host`` header) admit to the real ``CoarseHealthCheckView``. See issue
# #477 and ``docs/architecture/portal-health-readiness-preflight-477.md``.
_HEALTH_PATHS = frozenset({"/health", "/health/"})

# Host substituted for the request's ``HTTP_HOST`` on health-probe paths.
# ``localhost`` is always in ``DJANGO_ALLOWED_HOSTS`` (see ``config.settings``
# default ``"localhost,127.0.0.1"``), so downstream host validation admits
# the probe without weakening ``ALLOWED_HOSTS`` for non-health paths.
_HEALTH_ADMISSION_HOST = "localhost"

_CTF_ACCOUNT_ALWAYS_ALLOWED = frozenset(
    {
        "/ctf/change-password/",
        "/logout/",
    }
)

# Mission Control range-access endpoints a live participant legitimately needs to
# reach their OWN range box: the Guacamole RDP/SSH URL bootstrap plus its
# status/open polling (issue #1740). These self-authorize per user — the
# underlying resolvers (engine.services.get_rdp_connection_info /
# get_ssh_connection_info via Range.resolve_active_for_instance) only return a
# box in the requester's own active, ready range, and the bootstrap
# status/open lookups are owner-scoped — so admitting the path is safe. This is
# ADMISSION ONLY: the endpoints still enforce authentication, CSRF, actor/scope,
# request-shape, ready-range ownership, declared participant channel, and
# owner-scoped bootstrap delivery. The prefix is deliberately narrow: NGFW,
# range lifecycle/history, credentials, uploads, agents, and scenarios stay
# blocked. Any NEW route added under this prefix becomes reachable by temporary
# accounts and therefore requires its own security review.
_PARTICIPANT_MISSION_CONTROL_PREFIXES = ("/api/v1/mission-control/guacamole/",)


class RequestIDMiddleware:
    """Add request ID to all requests for trace correlation.

    Preserves incoming X-Request-ID header if present, otherwise generates
    a new UUID. The request ID is available on the request object and
    included in the response header.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Get existing request ID or generate new one
        request_id = request.META.get("HTTP_X_REQUEST_ID")
        if not request_id:
            request_id = str(uuid.uuid4())[:8]

        # Store on request object for access by views and audit logging. The
        # ignore is needed because HttpRequest has no typed slot for this
        # middleware-added dynamic attribute (read back by views / audit logger).
        request.request_id = request_id  # type: ignore[attr-defined]

        response = self.get_response(request)

        # Include in response for client correlation
        response["X-Request-ID"] = request_id

        return response


class CTFAccountBoundaryMiddleware:
    """Deny marked temporary accounts outside participant-owned surfaces."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from django.http import HttpResponse
        from django.shortcuts import redirect

        from management.services import is_ctf_password_change_required, is_temporary_ctf_account

        user = request.user
        if not is_temporary_ctf_account(user):
            response = self.get_response(request)
        else:
            path = request.path
            from ctf.services.participant.accounts import live_participant_for_user

            participant_surface = (
                (path.startswith("/ctf/") and not path.startswith("/ctf/admin/"))
                or path.startswith("/api/v1/ctf/")
                or path.startswith(_PARTICIPANT_MISSION_CONTROL_PREFIXES)
            )
            forbidden = (path != "/logout/" and live_participant_for_user(user) is None) or (
                path not in _CTF_ACCOUNT_ALWAYS_ALLOWED and not participant_surface
            )
            if forbidden:
                response = HttpResponse("Forbidden", status=403, content_type="text/plain")
            elif is_ctf_password_change_required(user) and path not in _CTF_ACCOUNT_ALWAYS_ALLOWED:
                response = redirect("ctf:ctf_change_password")
            else:
                response = self.get_response(request)
        return response


class HealthCheckMiddleware:
    """Admit AWS ALB / GCP ingress health probes past ``ALLOWED_HOSTS``.

    Load-balancer health probes arrive with the LB's internal IP as the
    ``Host`` header. Those IPs intentionally are not in
    ``DJANGO_ALLOWED_HOSTS`` (see
    ``scripts/gcp/render_runtime_env.py:101-107``), so without this
    middleware Django raises ``DisallowedHost`` on every probe.

    The middleware is admission-only: for ``/health`` and ``/health/``, it
    overwrites ``HTTP_HOST`` with ``localhost`` (already in
    ``ALLOWED_HOSTS``) and continues down the chain. The real
    ``config.health.CoarseHealthCheckView`` then runs the registered
    ``django-health-check`` probes (DB, cache, storage) and reports the
    actual readiness state. The middleware never creates the response,
    status code, or body.

    Per the issue #477 preflight at
    ``docs/architecture/portal-health-readiness-preflight-477.md``, this
    bypass stays path-scoped and admission-only. Non-health paths are
    unaffected.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path in _HEALTH_PATHS:
            request.META["HTTP_HOST"] = _HEALTH_ADMISSION_HOST
        return self.get_response(request)


class RequestInFlightMiddleware:
    """Track in-flight HTTP request concurrency per worker process (#940).

    Brackets every HTTP request with an increment/decrement on the process-local
    ``inflight_requests`` gauge that ``config.capacity_metrics`` publishes to the
    ``Shifter/PortalCapacity`` namespace. The gauge is the app-side
    ``WorkerBusyRatio`` numerator: a worker whose in-flight count sits above its
    soft-concurrency target is queueing request-path work that average EC2 CPU
    does not reflect.

    The middleware is async-aware so it measures true event-loop concurrency
    rather than threadpool-adapted concurrency: under the Uvicorn worker the
    portal serves requests on the loop, and a sync-only middleware would force
    every request through Django's limited sync threadpool and distort the very
    signal being measured. The counter is decremented in a ``finally`` so an
    exception in a downstream view or middleware can never leak the gauge upward.
    It records HTTP only; terminal/websocket saturation is accounted separately
    via ``mission_control.terminal_sessions``.
    """

    async_capable = True
    sync_capable = True

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self._is_async = iscoroutinefunction(get_response)
        if self._is_async:
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> HttpResponse | Awaitable[HttpResponse]:
        if self._is_async:
            return self._acall(request)
        inflight_requests.increment()
        try:
            return self.get_response(request)
        finally:
            inflight_requests.decrement()

    async def _acall(self, request: HttpRequest) -> HttpResponse:
        inflight_requests.increment()
        try:
            # In the async path Django passes a coroutine get_response; the class
            # attribute is typed with the sync signature, so cast the awaitable.
            return await cast("Awaitable[HttpResponse]", self.get_response(request))
        finally:
            inflight_requests.decrement()


class BrowserPolicyHeadersMiddleware:
    """Set the browser-policy headers Django's own middleware does not own.

    Adds ``Permissions-Policy`` and ``Reporting-Endpoints`` (the W3C reporting
    group backing the CSP ``report-to`` directive) globally, beside the native
    ``ContentSecurityPolicyMiddleware`` and ``SecurityMiddleware``. Values come
    from :mod:`config._browser_security` (ADR-036). ``setdefault`` is used so a
    deliberately stricter per-view header (e.g. the CTF invite ``no-referrer``)
    is never clobbered.

    Async-aware so it measures no request through Django's sync threadpool under
    the ASGI worker (matching :class:`RequestInFlightMiddleware`).
    """

    async_capable = True
    sync_capable = True

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self._is_async = iscoroutinefunction(get_response)
        if self._is_async:
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> HttpResponse | Awaitable[HttpResponse]:
        if self._is_async:
            return self._acall(request)
        return self._apply(self.get_response(request))

    async def _acall(self, request: HttpRequest) -> HttpResponse:
        response = await cast("Awaitable[HttpResponse]", self.get_response(request))
        return self._apply(response)

    @staticmethod
    def _apply(response: HttpResponse) -> HttpResponse:
        response.setdefault("Permissions-Policy", settings.PERMISSIONS_POLICY)
        response.setdefault("Reporting-Endpoints", settings.REPORTING_ENDPOINTS_HEADER)
        return response
