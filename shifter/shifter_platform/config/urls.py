"""Root URL configuration for the Shifter platform Django project."""

from django.conf import settings
from django.contrib import admin
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import include, path, re_path
from django.views.decorators.http import require_safe

from config import api_urls
from config.csp_report import csp_report
from config.dev_auth import dev_login, dev_logout
from config.health import CoarseHealthCheckView
from config.views import (
    dashboard_router,
    home,
    identity_platform_session,
    legacy_oidc_authenticate,
    logout_view,
    platform_login,
    privacy_notice,
)
from shared.spa_host import platform_spa_enabled, platform_spa_host


@require_safe
def _root_page(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
    """Serve the platform SPA shell at ``/`` when the rollout flag is on.

    When ``PLATFORM_SPA_ENABLED`` is off (the default) the legacy public
    ``home`` landing renders unchanged, so rollback is a flag flip. Only the
    exact root path is SPA-owned here (no global catch-all), so ``/privacy/``,
    ``/login/``, and the other Django routes stay Django-handled. GET/HEAD only
    (both the shell host and the legacy landing are safe reads).
    """
    if platform_spa_enabled():
        return platform_spa_host(request, *args, **kwargs)
    return home(request, *args, **kwargs)


def _aces_image_registry_spa_enabled() -> bool:
    """Return whether the SPA shell should serve the ACES image registry pages.

    Greenfield SPA-only surface (#1566): there is no legacy Django page here, so
    the pages exist only inside the flag-gated SPA. Gated on the platform SPA
    shell AND ``SHIFTER_ACES_NATIVE_PROVISIONING`` (the issue's hard gate), so the
    surface is inert unless both are on. No separate cutover flag: nothing is
    being replaced.
    """
    return bool(platform_spa_enabled() and getattr(settings, "ACES_NATIVE_PROVISIONING_ENABLED", False))


@require_safe
def _aces_image_registry_page(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
    """Serve the SPA shell for the ACES image registry pages, else 404.

    GET/HEAD only. When the surface is disabled the path 404s (there is no legacy
    page to fall back to), so the route is inert in the default configuration and
    never swallows a request.
    """
    if _aces_image_registry_spa_enabled():
        return platform_spa_host(request, *args, **kwargs)
    raise Http404


def _administer_spa_enabled() -> bool:
    """Return whether the SPA shell should serve the Administer workspace pages.

    Administer (#1373) is a greenfield SPA surface: there is no legacy Django page
    at ``/administer/``, so the pages exist only inside the flag-gated SPA. Gated
    on the platform SPA shell AND ``ADMINISTER_SPA_ENABLED`` so the surface is
    inert unless both are on. Django admin at ``/admin/`` is independent and stays
    mapped to ``admin.site.urls`` in every rollout state.
    """
    return bool(platform_spa_enabled() and getattr(settings, "ADMINISTER_SPA_ENABLED", False))


@require_safe
def _administer_page(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
    """Serve the SPA shell for the Administer workspace pages, else 404.

    GET/HEAD only. When the surface is disabled the path 404s (there is no legacy
    ``/administer/`` page — Django admin lives at ``/admin/``), so the route is
    inert in the default configuration and never swallows a request.
    """
    if _administer_spa_enabled():
        return platform_spa_host(request, *args, **kwargs)
    raise Http404


urlpatterns = [
    path("", _root_page, name="home"),
    path("privacy/", privacy_notice, name="privacy_notice"),
    # Same-origin CSP violation report collector (ADR-036-R3). POST-only,
    # anonymous, CSRF-exempt transport plumbing; not a public business API.
    path("security/csp-report/", csp_report, name="csp_report"),
    path("login/", platform_login, name="platform_login"),
    path("auth/identity/session/", identity_platform_session, name="identity_platform_session"),
    path("dashboard/", dashboard_router, name="dashboard_router"),
    path("logout/", logout_view, name="logout"),
    path("mission-control/", include("mission_control.urls")),
    path("risk-register/", include("risk_register.urls")),
    path("scenario-editor/", include("cms.scenario_editor.urls")),
    # ACES image registry SPA pages (#1566): greenfield, SPA-only, gated on the
    # platform SPA shell + SHIFTER_ACES_NATIVE_PROVISIONING. The base path plus a
    # catch-all under the prefix serve the shell so client-router deep links and
    # refresh resolve; both 404 when the surface is disabled.
    path("aces-image-registry/", _aces_image_registry_page, name="aces_image_registry"),
    re_path(r"^aces-image-registry/.*$", _aces_image_registry_page),
    # Administer workspace SPA pages (#1373): greenfield, SPA-only, gated on the
    # platform SPA shell + ADMINISTER_SPA_ENABLED. The base path plus a catch-all
    # under the prefix serve the shell so client-router deep links and refresh
    # resolve; both 404 when the surface is disabled. Django admin at /admin/ is
    # untouched.
    path("administer/", _administer_page, name="administer"),
    re_path(r"^administer/.*$", _administer_page),
    path("api/v1/", include((api_urls.urlpatterns, api_urls.app_name), namespace="v1")),
    path("ctf/", include("ctf.urls")),
    path("admin/", admin.site.urls),
    # /health and /health/ both resolve to the same dependency-aware probe
    # view. The no-trailing-slash variant is for the AWS ALB target group
    # (``platform/terraform/environments/{dev,prod}/portal/terraform.tfvars``
    # ``health_check_path = "/health"``) which does not follow 3xx redirects;
    # the trailing-slash variant is the canonical URL used by the GCP
    # readiness/liveness probes, the Docker HEALTHCHECK, and the
    # ``shifter/installation`` backend bundle contract. See issue #477 and
    # ``docs/architecture/portal-health-readiness-preflight-477.md``.
    path("health/", CoarseHealthCheckView.as_view(), name="portal_health"),
    path("health", CoarseHealthCheckView.as_view(), name="portal_health_no_slash"),
]

urlpatterns.append(path("oidc/authenticate/", legacy_oidc_authenticate, name="legacy_oidc_authenticate"))

if settings.AUTH_PROVIDER == "oidc":
    urlpatterns.append(path("oidc/", include("mozilla_django_oidc.urls")))

# Keep the routes stable across environments and enforce production blocking in the views.
urlpatterns += [
    path("dev-login/", dev_login, name="dev_login"),
    path("dev-logout/", dev_logout, name="dev_logout"),
]
