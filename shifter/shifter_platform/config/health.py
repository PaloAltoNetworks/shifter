"""Portal ``/health`` readiness view.

Public-safe wrapper around ``django-health-check``'s ``CheckMixin``. The
upstream ``HealthCheckView`` (v4) hard-codes a default ``checks`` list that
includes ``health_check.Mail`` and the v4 db-heartbeat / storage backends —
not the legacy ``health_check.db.DatabaseBackend``, ``CacheBackend``, and
``DefaultFileStorageHealthCheck`` that the portal's ``INSTALLED_APPS``
register. Per
``docs/architecture/portal-health-readiness-preflight-477.md`` the installed
``health_check.db`` / ``health_check.cache`` / ``health_check.storage`` apps
are the canonical probe set, so this view consults the
``plugin_dir._registry`` populated by those apps rather than the v4 default
list.

It also replaces the upstream renderers (HTML template + JSON
``pretty_status()``) with a coarse JSON body that exposes only the probe
label and a fixed ``working`` / ``unavailable`` token. The upstream
renderers surface each probe's raw error text (PostgreSQL
``OperationalError`` strings carrying private RDS hostnames, S3
``ClientError`` bodies carrying bucket names, Redis ``ConnectionError``
strings carrying internal endpoints, full stack traces). The #477 preflight
Anti-Patterns section forbids that on the public surface. The HTTP status
code (200 / 500) still differentiates pass and fail; detailed diagnostics
remain available in structured logs via
``health_check.backends.HealthCheck.add_error`` which routes through the
standard logger and ``config.logging.ECSFormatter``.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import View
from health_check.mixins import CheckMixin


class CoarseHealthCheckView(CheckMixin, View):
    """Run the ``INSTALLED_APPS``-registered django-health-check probes and
    return a coarse JSON body.

    Body shape: ``{"<plugin label>": "working" | "unavailable", ...}``.
    Status: 200 when every plugin's ``errors`` is empty, 500 otherwise.
    """

    _OK_LABEL = "working"
    _FAIL_LABEL = "unavailable"

    @method_decorator(never_cache)
    def get(self, request, *args, **kwargs):
        has_error = bool(self.check())
        status_code = 500 if has_error else 200
        body = {label: (self._FAIL_LABEL if p.errors else self._OK_LABEL) for label, p in self.plugins.items()}
        return JsonResponse(body, status=status_code)
