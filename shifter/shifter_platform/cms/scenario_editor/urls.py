"""URL configuration for Scenario Editor.

Rollout-flag aware (issue #1371, ADR-013 / ADR-029), mirroring
``mission_control.urls`` and ``risk_register.urls``. When the SPA shell is
enabled, the GET page paths (list, create, YAML create, detail, edit, YAML
editor) are served by the platform SPA host view (the Scenario Editor routes
rehomed under the unified client router); when off (the default), the classic
Django template views handle them. The decision is made **per request** (not at
import) so the flag can be flipped without a restart and so tests can toggle it
with ``override_settings``. The enable check honours both ``PLATFORM_SPA_ENABLED``
(the platform-wide control) and ``SCENARIO_EDITOR_SPA_ENABLED`` (the
Scenario-Editor-specific extension of that flag pattern) — both must be on. The
legacy POST action URLs (delete, clone, toggle-enabled, toggle-staff-only) and
the legacy validate-yaml / export endpoints are always Django-handled: the SPA
uses the canonical ``/api/v1/cms/`` DRF routes exclusively (see ``cms.api.urls``),
but old tabs, bookmarks, and rollback rely on these. Route *names* are identical
in both modes so ``reverse("scenario_editor:...")`` callers keep working across
the cutover.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import path, re_path

from cms.scenario_editor import views
from shared.spa_host import platform_spa_host

app_name = "scenario_editor"


def _spa_enabled() -> bool:
    """Return whether the SPA shell should serve the Scenario Editor pages."""
    return bool(
        getattr(settings, "PLATFORM_SPA_ENABLED", False) and getattr(settings, "SCENARIO_EDITOR_SPA_ENABLED", False)
    )


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _page(django_view: Callable[..., HttpResponse] | None) -> Callable[..., HttpResponse]:
    """Return a view that serves the SPA shell for a page path, else the Django page.

    The shell takeover is **method-aware**: unlike Risk Register / Mission
    Control (whose page paths are GET-only, with mutations on separate action
    URLs), several Scenario Editor page paths are handled by Django form views
    that own BOTH page rendering (GET) AND the form submission (POST) on the same
    URL (create, create/yaml, edit, editor). Serving the ``@require_safe`` SPA
    shell for those unsafe methods would 405 the legacy form POST and break the
    old-tab / rollback guarantee. So the shell is served only for safe methods
    when enabled; unsafe methods always fall through to the incumbent Django view
    (the SPA itself mutates exclusively via the canonical ``/api/v1/cms/`` routes).

    ``django_view=None`` marks a client-router-only path: it serves the shell for
    safe methods when the SPA is enabled and 404s otherwise (so the catch-all is
    inert in the default Django mode and never swallows an unsafe request).
    """

    def _dispatch(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Serve the SPA shell for safe methods when enabled, else the Django page (or 404)."""
        if _spa_enabled() and request.method in _SAFE_METHODS:
            return platform_spa_host(request, *args, **kwargs)
        if django_view is None:
            raise Http404
        return django_view(request, *args, **kwargs)

    return _dispatch


urlpatterns = [
    # Page paths: SPA shell when both flags are on, Django templates when off.
    path("", _page(views.scenario_list), name="list"),
    path("create/", _page(views.scenario_create_form), name="create"),
    path("create/yaml/", _page(views.scenario_yaml_create), name="create_yaml"),
    # Legacy YAML validation action: always Django-handled (SPA uses /api/v1/cms/).
    path("validate-yaml/", views.validate_yaml_view, name="api_validate_yaml"),
    path("<slug:scenario_id>/", _page(views.scenario_detail_view), name="detail"),
    path("<slug:scenario_id>/edit/", _page(views.scenario_edit_form), name="edit"),
    path("<slug:scenario_id>/editor/", _page(views.scenario_yaml_editor), name="yaml_editor"),
    # Legacy POST action + export URLs: always Django-handled (old tabs / rollback).
    path("<slug:scenario_id>/delete/", views.scenario_delete_view, name="delete"),
    path("<slug:scenario_id>/clone/", views.scenario_clone_view, name="clone"),
    path("<slug:scenario_id>/toggle-enabled/", views.scenario_toggle_enabled, name="toggle_enabled"),
    path("<slug:scenario_id>/toggle-staff-only/", views.scenario_toggle_staff_only, name="toggle_staff_only"),
    path("<slug:scenario_id>/export/", views.scenario_export_view, name="export"),
    # Client-router deep links / refresh: SPA shell when enabled, else 404.
    re_path(r"^.*$", _page(None)),
]
