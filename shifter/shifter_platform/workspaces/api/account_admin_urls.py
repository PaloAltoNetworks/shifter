"""Public dormant account administration routing surface."""

from django.urls import URLPattern, path

from workspaces.api import account_admin_views as accounts
from workspaces.api import account_authorization_views as authorization
from workspaces.api import policy_membership_views as members
from workspaces.api import policy_profile_views as profiles
from workspaces.api.authorization_views import AuthorizationCatalogView, PredefinedAuthorizationCatalogView


def _authorization_routes(prefix: str, target_type: str) -> list[URLPattern]:
    """One existing journal adapter for every concrete hierarchy scope."""
    defaults: dict[str, object] = {"target_type": target_type}
    if target_type == "installation":
        defaults["target_uuid"] = None
    routes = (
        ("groups/", authorization.ScopedAuthorizationGroupCollectionView),
        ("groups/<uuid:group_uuid>/memberships/", authorization.ScopedAuthorizationGroupMembershipView),
        ("policies/", authorization.ScopedAuthorizationPolicyCollectionView),
        ("policies/<uuid:policy_uuid>/assignments/", authorization.ScopedAuthorizationPolicyAssignmentView),
        ("policies/<uuid:policy_uuid>/actions/", authorization.ScopedAuthorizationPolicyActionView),
        ("direct-assignments/", authorization.ScopedAuthorizationDirectAssignmentView),
        ("predefined-assignments/", authorization.ScopedAuthorizationPredefinedAssignmentView),
        ("operations/<uuid:operation_uuid>/", authorization.ScopedAuthorizationOperationView),
    )
    return [path(prefix + suffix, view.as_view(), defaults) for suffix, view in routes]


urlpatterns = [
    path(
        "organizations/<uuid:target_uuid>/authorization/operations/<uuid:operation_uuid>/",
        authorization.ScopedAuthorizationOperationView.as_view(),
        {"target_type": "organization"},
    ),
    path("workspaces/<uuid:workspace_uuid>/membership/", members.PolicySelfWorkspaceMembershipView.as_view()),
    path("workspaces/<uuid:workspace_uuid>/memberships/leave/", members.PolicyLeaveWorkspaceView.as_view()),
    path("accounts/", accounts.AccountCollectionView.as_view()),
    path("accounts/current/", accounts.AccountCurrentView.as_view()),
    path("accounts/context/", profiles.AccountPrincipalContextView.as_view()),
    path("accounts/<uuid:account_uuid>/", profiles.PolicyAccountDetailView.as_view()),
    path("accounts/<uuid:account_uuid>/memberships/", accounts.AccountMemberCollectionView.as_view()),
    path("accounts/<uuid:account_uuid>/memberships/<uuid:principal_uuid>/", accounts.AccountMemberDetailView.as_view()),
    path("accounts/<uuid:account_uuid>/organizations/", accounts.AccountOrganizationCollectionView.as_view()),
    path(
        "accounts/<uuid:account_uuid>/organizations/<uuid:organization_uuid>/",
        profiles.PolicyOrganizationProfileView.as_view(),
    ),
    path(
        "accounts/<uuid:account_uuid>/organizations/<uuid:organization_uuid>/workspaces/",
        accounts.AccountWorkspaceCollectionView.as_view(),
    ),
    path(
        "accounts/<uuid:account_uuid>/organizations/<uuid:organization_uuid>/workspaces/<uuid:workspace_uuid>/",
        accounts.AccountWorkspaceDetailView.as_view(),
    ),
    path(
        "organizations/<uuid:target_uuid>/memberships/",
        members.PolicyScopeMemberCollectionView.as_view(),
        {"target_type": "organization"},
    ),
    path(
        "organizations/<uuid:target_uuid>/memberships/<uuid:principal_uuid>/",
        members.PolicyScopeMemberDetailView.as_view(),
        {"target_type": "organization"},
    ),
    path(
        "workspaces/<uuid:target_uuid>/memberships/",
        members.PolicyScopeMemberCollectionView.as_view(),
        {"target_type": "workspace"},
    ),
    path(
        "workspaces/<uuid:target_uuid>/memberships/<uuid:principal_uuid>/",
        members.PolicyScopeMemberDetailView.as_view(),
        {"target_type": "workspace"},
    ),
    path("workspaces/<uuid:workspace_uuid>/rename/", accounts.AccountWorkspaceRenameView.as_view()),
    path("workspaces/<uuid:workspace_uuid>/archive/", accounts.AccountWorkspaceArchiveView.as_view()),
    path("workspaces/<uuid:workspace_uuid>/restore/", accounts.AccountWorkspaceRestoreView.as_view()),
    path("workspaces/<uuid:workspace_uuid>/transfer/", members.PolicyWorkspaceOwnershipView.as_view()),
    path("workspaces/<uuid:workspace_uuid>/owners/", members.PolicyWorkspaceOwnerCollectionView.as_view()),
    path(
        "workspaces/<uuid:workspace_uuid>/owners/<uuid:principal_uuid>/",
        members.PolicyWorkspaceOwnerDetailView.as_view(),
    ),
    path("workspaces/<uuid:workspace_uuid>/quota/", profiles.PolicyWorkspaceQuotaView.as_view()),
    path("workspaces/<uuid:workspace_uuid>/quota-policy/", accounts.AccountWorkspaceQuotaPolicyView.as_view()),
    path("workspaces/<uuid:workspace_uuid>/egress-policy/", accounts.AccountWorkspaceEgressPolicyView.as_view()),
    path("workspaces/<uuid:workspace_uuid>/invitations/", members.PolicyInvitationCollectionView.as_view()),
    path(
        "workspaces/<uuid:workspace_uuid>/invitations/<uuid:invitation_uuid>/resend/",
        members.PolicyInvitationMutationView.as_view(),
        {"operation": "resend"},
    ),
    path(
        "workspaces/<uuid:workspace_uuid>/invitations/<uuid:invitation_uuid>/revoke/",
        members.PolicyInvitationMutationView.as_view(),
        {"operation": "revoke"},
    ),
    path("workspaces/authorization/catalog/", AuthorizationCatalogView.as_view()),
    path("workspaces/authorization/predefined-catalog/", PredefinedAuthorizationCatalogView.as_view()),
    *_authorization_routes("administer/authorization/", "installation"),
    *_authorization_routes("accounts/<uuid:target_uuid>/authorization/", "account"),
    *_authorization_routes(
        "accounts/<uuid:account_uuid>/organizations/<uuid:target_uuid>/authorization/", "organization"
    ),
    *_authorization_routes("workspaces/<uuid:target_uuid>/authorization/", "workspace"),
]
