"""Canonical v1 API URL configuration for the Shifter platform."""

from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.api_administer import AdministerGrantOrganizerView
from config.api_bootstrap import BootstrapView
from config.api_dashboard import DashboardSummaryView

app_name = "api"

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(api_version="v1"), name="openapi-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="v1:openapi-schema"), name="api-docs"),
    path("bootstrap/", BootstrapView.as_view(), name="bootstrap"),
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("cms/", include("cms.api.urls", namespace="cms")),
    path("ctf/", include("ctf.api.urls")),
    path("mission-control/", include("mission_control.api.urls")),
    # Administer workspace (#1373). Single-domain user operations live in
    # management.api; the cross-domain local-organizer grant is served by the
    # composition root and registered ahead of the include so its specific route
    # matches first.
    path(
        "administer/users/<int:pk>/grant-organizer/",
        AdministerGrantOrganizerView.as_view(),
        name="administer-grant-organizer",
    ),
    path("administer/", include("management.api.urls")),
    path("", include("risk_register.api.urls")),
]
