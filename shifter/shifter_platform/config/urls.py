"""Root URL configuration for the Shifter platform Django project."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from config.dev_auth import dev_login, dev_logout
from config.health import CoarseHealthCheckView
from config.views import (
    dashboard_router,
    home,
    identity_platform_session,
    legacy_oidc_authenticate,
    logout_view,
    platform_login,
)

urlpatterns = [
    path("", home, name="home"),
    path("login/", platform_login, name="platform_login"),
    path("auth/identity/session/", identity_platform_session, name="identity_platform_session"),
    path("dashboard/", dashboard_router, name="dashboard_router"),
    path("logout/", logout_view, name="logout"),
    path("mission-control/", include("mission_control.urls")),
    path("risk-register/", include("risk_register.urls")),
    path("mission-control/experiments/", include("cms.experiments.urls")),
    path("scenario-editor/", include("cms.scenario_editor.urls")),
    path("docs/", include("documentation.urls")),
    path("api/v1/", include("risk_register.api.urls")),
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
