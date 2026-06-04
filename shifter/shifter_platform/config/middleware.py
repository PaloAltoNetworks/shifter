"""Custom middleware for Shifter platform."""

import uuid

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


class RequestIDMiddleware:
    """Add request ID to all requests for trace correlation.

    Preserves incoming X-Request-ID header if present, otherwise generates
    a new UUID. The request ID is available on the request object and
    included in the response header.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Get existing request ID or generate new one
        request_id = request.META.get("HTTP_X_REQUEST_ID")
        if not request_id:
            request_id = str(uuid.uuid4())[:8]

        # Store on request object for access by views and audit logging
        request.request_id = request_id

        response = self.get_response(request)

        # Include in response for client correlation
        response["X-Request-ID"] = request_id

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

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in _HEALTH_PATHS:
            request.META["HTTP_HOST"] = _HEALTH_ADMISSION_HOST
        return self.get_response(request)
