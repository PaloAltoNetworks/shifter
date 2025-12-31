from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from config.views import home

urlpatterns = [
    path("", home, name="home"),
    path("mission-control/", include("mission_control.urls")),
    path("risk-register/", include("risk_register.urls")),
    path("docs/", include("documentation.urls")),
    path("api/v1/", include("risk_register.api.urls")),
    path("admin/", admin.site.urls),
    path("health/", include("health_check.urls")),
    path("oidc/", include("mozilla_django_oidc.urls")),
]

# Development-only auth bypass - routes don't exist in production
if settings.DEBUG:
    from config.dev_auth import dev_login, dev_logout

    urlpatterns += [
        path("dev-login/", dev_login, name="dev_login"),
        path("dev-logout/", dev_logout, name="dev_logout"),
    ]
