"""Prepared S4 URLConf. S8 alone mounts the coordinated production route swap."""

from django.urls import include, path

from config import api_administer_leases as leases
from config.api_account_administration import PolicyAdministerGrantOrganizerView, PolicyAdministerTransferOwnershipView

api_patterns = [
    path("", include("workspaces.api.account_admin_urls")),
    path("", include("management.api.account_admin_urls")),
    path("cms/", include("cms.api.account_admin_urls")),
    path("administer/users/<int:pk>/transfer-ownership/", PolicyAdministerTransferOwnershipView.as_view()),
    path("administer/users/<int:pk>/grant-organizer/", PolicyAdministerGrantOrganizerView.as_view()),
    path("administer/mission-control/lease-policy/", leases.PolicyMissionControlLeasePolicySettingsView.as_view()),
    path("administer/mission-control/lease-policy/tenant/", leases.PolicyMissionControlTenantLeasePolicyView.as_view()),
    path(
        "administer/mission-control/lease-policy/tenant/reset/",
        leases.PolicyMissionControlTenantLeasePolicyResetView.as_view(),
    ),
    path(
        "administer/mission-control/lease-policy/groups/<int:group_id>/",
        leases.PolicyMissionControlGroupLeasePolicyView.as_view(),
    ),
    path(
        "administer/mission-control/lease-policy/groups/<int:group_id>/reset/",
        leases.PolicyMissionControlGroupLeasePolicyResetView.as_view(),
    ),
]
urlpatterns = [path("api/v1/", include(api_patterns))]
