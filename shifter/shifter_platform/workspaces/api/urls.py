"""Workspace membership routes mounted at `/api/v1/workspaces/`."""

from django.urls import path

from workspaces.api.invitation_views import (
    WorkspaceInvitationListIssueView,
    WorkspaceInvitationResendView,
    WorkspaceInvitationRevokeView,
)
from workspaces.api.lifecycle_views import (
    WorkspaceArchiveView,
    WorkspaceCollectionView,
    WorkspaceDetailView,
    WorkspaceEgressPolicyView,
    WorkspaceQuotaView,
    WorkspaceRestoreView,
    WorkspaceTransferOwnershipView,
)
from workspaces.api.views import (
    MembershipLeaveView,
    MembershipListAddView,
    MembershipRemoveView,
    MembershipRoleView,
    OrganizationListView,
    OrganizationProfileView,
    PrincipalWorkspaceContextView,
    SelfMembershipView,
)

app_name = "workspaces"

urlpatterns = [
    # Static `context/` and `organizations/` prefixes are declared before the
    # `<uuid:workspace_uuid>` routes; neither is a valid UUID, so the ordering is
    # defensive, not load-bearing.
    path("", WorkspaceCollectionView.as_view(), name="workspaces"),
    path("context/", PrincipalWorkspaceContextView.as_view(), name="principal-context"),
    path("organizations/", OrganizationListView.as_view(), name="organization-list"),
    path(
        "organizations/<uuid:organization_uuid>/",
        OrganizationProfileView.as_view(),
        name="organization-detail",
    ),
    path("<uuid:workspace_uuid>/", WorkspaceDetailView.as_view(), name="workspace-detail"),
    path("<uuid:workspace_uuid>/archive/", WorkspaceArchiveView.as_view(), name="workspace-archive"),
    path("<uuid:workspace_uuid>/restore/", WorkspaceRestoreView.as_view(), name="workspace-restore"),
    path(
        "<uuid:workspace_uuid>/egress-policy/",
        WorkspaceEgressPolicyView.as_view(),
        name="workspace-egress-policy",
    ),
    path("<uuid:workspace_uuid>/quota/", WorkspaceQuotaView.as_view(), name="workspace-quota"),
    path("<uuid:workspace_uuid>/transfer/", WorkspaceTransferOwnershipView.as_view(), name="workspace-transfer"),
    path("<uuid:workspace_uuid>/membership/", SelfMembershipView.as_view(), name="membership-self"),
    path("<uuid:workspace_uuid>/memberships/", MembershipListAddView.as_view(), name="memberships"),
    path("<uuid:workspace_uuid>/memberships/leave/", MembershipLeaveView.as_view(), name="memberships-leave"),
    path(
        "<uuid:workspace_uuid>/invitations/",
        WorkspaceInvitationListIssueView.as_view(),
        name="invitations",
    ),
    path(
        "<uuid:workspace_uuid>/invitations/<uuid:invitation_uuid>/resend/",
        WorkspaceInvitationResendView.as_view(),
        name="invitations-resend",
    ),
    path(
        "<uuid:workspace_uuid>/invitations/<uuid:invitation_uuid>/revoke/",
        WorkspaceInvitationRevokeView.as_view(),
        name="invitations-revoke",
    ),
    path(
        "<uuid:workspace_uuid>/memberships/<int:user_id>/role/",
        MembershipRoleView.as_view(),
        name="memberships-role",
    ),
    path(
        "<uuid:workspace_uuid>/memberships/<int:user_id>/remove/",
        MembershipRemoveView.as_view(),
        name="memberships-remove",
    ),
]
