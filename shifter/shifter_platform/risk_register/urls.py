"""URL routing for the Risk Register UI.

Rollout-flag aware (issue #1302, ADR-029). When ``RISK_REGISTER_SPA_ENABLED``
is on, the GET page paths are served by the React SPA host view; when off (the
default), the classic Django template views handle them. The decision is made
**per request** (not at import) so the flag can be flipped without a restart and
so tests can toggle it with ``override_settings``. The legacy POST action URLs
are always Django-handled — the SPA uses /api/v1/ exclusively, but old tabs,
bookmarks, and rollback rely on them. Route *names* are identical in both modes
so ``reverse("risk_register:...")`` callers keep working across the cutover.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import path, re_path

from risk_register import views
from risk_register.spa_views import risk_register_spa_host


def _spa_enabled() -> bool:
    """Return whether the Risk Register SPA rollout flag is enabled."""
    return bool(getattr(settings, "RISK_REGISTER_SPA_ENABLED", False))


def _page(django_view: Callable[..., HttpResponse] | None) -> Callable[..., HttpResponse]:
    """Return a view that serves the SPA shell when enabled, else the Django page.

    ``django_view=None`` marks a client-router-only path: it serves the shell
    when the SPA is enabled and 404s otherwise (so the catch-all is inert in the
    default Django mode).
    """

    def _dispatch(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Serve the SPA shell when enabled, else the Django page (or 404)."""
        if _spa_enabled():
            return risk_register_spa_host(request, *args, **kwargs)
        if django_view is None:
            raise Http404
        return django_view(request, *args, **kwargs)

    return _dispatch


app_name = "risk_register"

urlpatterns = [
    # Page paths: SPA shell when the flag is on, Django templates when off.
    path("", _page(views.risk_list), name="risk_list"),
    path("risks/create/", _page(views.risk_create), name="risk_create"),
    path("risks/<int:pk>/", _page(views.risk_detail), name="risk_detail"),
    path("risks/<int:pk>/edit/", _page(views.risk_edit), name="risk_edit"),
    # Legacy POST action URLs: always Django-handled (old tabs / rollback).
    path("risks/<int:pk>/delete/", views.risk_delete, name="risk_delete"),
    path("risks/<int:pk>/restore/", views.risk_restore, name="risk_restore"),
    path("risks/<int:pk>/close/", views.risk_close, name="risk_close"),
    path("risks/<int:pk>/reopen/", views.risk_reopen, name="risk_reopen"),
    path("risks/<int:risk_pk>/comments/add/", views.comment_add, name="comment_add"),
    path(
        "risks/<int:risk_pk>/comments/<int:pk>/delete/",
        views.comment_delete,
        name="comment_delete",
    ),
    # Client-router deep links / refresh: SPA shell when enabled, else 404.
    re_path(r"^.*$", _page(None)),
]
