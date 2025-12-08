from django.contrib import admin
from django.urls import include, path

from config.views import home

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("health/", include("health_check.urls")),
    path("oidc/", include("mozilla_django_oidc.urls")),
]
