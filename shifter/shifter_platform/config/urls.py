"""Root URL configuration for the Shifter platform Django project."""

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.urls import include, path, re_path
from django.views.decorators.http import require_safe

from config import api_urls
from config.csp_report import csp_report
from config.dev_auth import dev_login, dev_logout
from config.health import CoarseHealthCheckView
from config.password_reset_views import (
    PlatformPasswordResetCompleteView,
    PlatformPasswordResetConfirmView,
)
from config.views import (
    dashboard_router,
    identity_platform_session,
    legacy_oidc_authenticate,
    logout_view,
    platform_login,
    privacy_notice,
)
from shared.spa_host import platform_spa_host


@require_safe
def _root_page(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
    """Serve the platform SPA shell at ``/``."""
    return platform_spa_host(request, *args, **kwargs)


@require_safe
def _raes_image_registry_page(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
    """Serve the SPA shell for the RAES image registry pages."""
    return platform_spa_host(request, *args, **kwargs)


@require_safe
def _administer_page(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
    """Serve the SPA shell for the Administer workspace pages."""
    return platform_spa_host(request, *args, **kwargs)


urlpatterns = [
    path("", _root_page, name="home"),
    path("privacy/", privacy_notice, name="privacy_notice"),
    path("", include("workspaces.public_urls")),
    # Same-origin CSP violation report collector (ADR-036-R3). POST-only,
    # anonymous, CSRF-exempt transport plumbing; not a public business API.
    path("security/csp-report/", csp_report, name="csp_report"),
    path("login/", platform_login, name="platform_login"),
    path("auth/identity/session/", identity_platform_session, name="identity_platform_session"),
    path("dashboard/", dashboard_router, name="dashboard_router"),
    path("logout/", logout_view, name="logout"),
    # Administrator-triggered password reset completion (PLAT-236, #1943). Only
    # the token-gated confirm/complete landing pages are public; there is no
    # public "enter your email" request page (reset is administrator-triggered
    # via the Administer API), so no account-enumeration surface is added.
    path(
        "account/password/reset/<uidb64>/<token>/",
        PlatformPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "account/password/reset/done/",
        PlatformPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("mission-control/", include("mission_control.urls")),
    path("scenario-editor/", include("cms.scenario_editor.urls")),
    # RAES image registry SPA pages (#1566). The base path plus a catch-all under
    # the prefix serve the shell so client-router deep links and refresh resolve.
    path("raes-image-registry/", _raes_image_registry_page, name="raes_image_registry"),
    re_path(r"^raes-image-registry/.*$", _raes_image_registry_page),
    # Administer workspace SPA pages (#1373). The base path plus a catch-all under
    # the prefix serve the shell so client-router deep links and refresh resolve.
    # Django admin at /admin/ remains a separate server-owned surface.
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
