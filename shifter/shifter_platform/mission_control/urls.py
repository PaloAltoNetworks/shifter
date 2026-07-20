"""Mission Control URL configuration.

Rollout-flag aware (issue #1370, ADR-013 / ADR-029), mirroring
``risk_register.urls``. When the SPA shell is enabled, the GET page paths
(dashboard, agents, terminal, settings, help, walkthrough, NGFW pages,
credential pages) are served by the platform SPA host view (the Mission
Control routes rehomed under the unified client router); when off (the
default), the classic Django template views handle them. The decision is
made **per request** (not at import) so the flag can be flipped without a
restart and so tests can toggle it with ``override_settings``. The enable
check honours both ``PLATFORM_SPA_ENABLED`` (the platform-wide control) and
``MISSION_CONTROL_SPA_ENABLED`` (the Mission-Control-specific extension of
that flag pattern) — both must be on. The remaining legacy POST action URL
(``agents/<id>/delete/``) is always Django-handled. The legacy JSON API that
used to live under ``api/`` was retired (issue #1328): the SPA and all callers
now use the canonical ``/api/v1/mission-control/`` DRF routes exclusively (see
``mission_control.api.urls``). Page route *names* are identical in both modes so
``reverse("mission_control:...")`` callers keep working across the cutover.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import path, re_path

from shared.spa_host import platform_spa_host

from . import views


def _spa_enabled() -> bool:
    """Return whether the SPA shell should serve the Mission Control pages."""
    return bool(
        getattr(settings, "PLATFORM_SPA_ENABLED", False) and getattr(settings, "MISSION_CONTROL_SPA_ENABLED", False)
    )


def _page(django_view: Callable[..., HttpResponse] | None) -> Callable[..., HttpResponse]:
    """Return a view that serves the SPA shell when enabled, else the Django page.

    ``django_view=None`` marks a client-router-only path: it serves the shell
    when the SPA is enabled and 404s otherwise (so the catch-all is inert in the
    default Django mode).
    """

    def _dispatch(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Serve the SPA shell when enabled, else the Django page (or 404)."""
        if _spa_enabled():
            return platform_spa_host(request, *args, **kwargs)
        if django_view is None:
            raise Http404
        return django_view(request, *args, **kwargs)

    return _dispatch


app_name = "mission_control"

urlpatterns = [
    # Page paths: SPA shell when both flags are on, Django templates when off.
    path("", _page(views.dashboard), name="dashboard"),
    path("agents/", _page(views.agents), name="agents"),
    # Legacy POST action URL: always Django-handled.
    path("agents/<int:agent_id>/delete/", views.delete_agent, name="delete_agent"),
    path("terminal/", _page(views.terminal), name="terminal"),
    path("settings/", _page(views.settings), name="settings"),
    path("help/", _page(views.help_page), name="help"),
    path("walkthrough/", _page(views.walkthrough), name="walkthrough"),
    # NGFW page paths: SPA shell when both flags are on, Django templates when off.
    path("ngfw/", _page(views.ngfw_list), name="ngfw_list"),
    path("ngfw/setup/", _page(views.ngfw_wizard), name="ngfw_wizard"),
    path("ngfw/<uuid:app_id>/", _page(views.ngfw_detail), name="ngfw_detail"),
    path("ngfw/<uuid:app_id>/deprovision/", _page(views.ngfw_deprovision), name="ngfw_deprovision"),
    # Credential page paths: SPA shell when both flags are on, Django templates when off.
    path("credentials/", _page(views.credentials_list), name="credentials_list"),
    path("credentials/add/", _page(views.credential_add), name="credential_add"),
    path("credentials/<int:credential_id>/", _page(views.credential_detail), name="credential_detail"),
    # Client-router deep links / refresh: SPA shell when enabled, else 404.
    #
    # Excludes ``files/`` and the whole ``api/`` prefix. ``files/`` and
    # ``api/scripts/`` are the removed legacy experiments feature's surfaces
    # (issue #1195, migration cms.migrations.0034_remove_legacy_experiments);
    # the rest of ``api/`` is the retired legacy JSON API (issue #1328 — the SPA
    # and all callers use the canonical ``/api/v1/mission-control/`` DRF routes).
    # A catch-all that matched these would make the retired paths resolve again
    # (to the SPA shell, or a 404-at-request-time view), regressing
    # tests/cms/test_experiments_removed.py::test_legacy_script_surfaces_are_not_routed
    # and the #1328 retirement tests, which assert they are unroutable at the
    # URLconf level (``Resolver404``), not just 404-at-runtime. Do not remove this
    # exclusion to "simplify" the regex without confirming those tests first.
    re_path(r"^(?!files/$|api/).*$", _page(None)),
]
