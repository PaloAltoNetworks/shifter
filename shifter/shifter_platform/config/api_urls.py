"""Canonical v1 API URL configuration for the Shifter platform."""

from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.api_administer import AdministerGrantOrganizerView, AdministerTransferOwnershipView
from config.api_administer_leases import (
    MissionControlGroupLeasePolicyResetView,
    MissionControlGroupLeasePolicyView,
    MissionControlLeasePolicySettingsView,
    MissionControlTenantLeasePolicyResetView,
    MissionControlTenantLeasePolicyView,
)
from config.api_bootstrap import BootstrapView
from config.api_dashboard import DashboardSummaryView

app_name = "api"

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(api_version="v1"), name="openapi-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="v1:openapi-schema"), name="api-docs"),
    path("bootstrap/", BootstrapView.as_view(), name="bootstrap"),
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path(
        "administer/mission-control/lease-policy/",
        MissionControlLeasePolicySettingsView.as_view(),
        name="administer-mission-control-lease-policy",
    ),
    path(
        "administer/mission-control/lease-policy/tenant/",
        MissionControlTenantLeasePolicyView.as_view(),
        name="administer-mission-control-tenant-lease-policy",
    ),
    path(
        "administer/mission-control/lease-policy/tenant/reset/",
        MissionControlTenantLeasePolicyResetView.as_view(),
        name="administer-mission-control-tenant-lease-policy-reset",
    ),
    path(
        "administer/mission-control/lease-policy/groups/<int:group_id>/",
        MissionControlGroupLeasePolicyView.as_view(),
        name="administer-mission-control-group-lease-policy",
    ),
    path(
        "administer/mission-control/lease-policy/groups/<int:group_id>/reset/",
        MissionControlGroupLeasePolicyResetView.as_view(),
        name="administer-mission-control-group-lease-policy-reset",
    ),
    path("workspaces/", include("workspaces.api.urls")),
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
    # Cross-domain offboarding ownership transfer (ranges + workspaces, PLAT-236).
    # Composition-root command registered ahead of the include, like grant-organizer.
    path(
        "administer/users/<int:pk>/transfer-ownership/",
        AdministerTransferOwnershipView.as_view(),
        name="administer-transfer-ownership",
    ),
    path("administer/", include("management.api.urls")),
    path("", include("shared.api.urls")),
]
