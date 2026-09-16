"""Public service facade for the workspaces tenancy domain (ADR-046-R1/R8).

This module is the *only* surface other layers may import. They must not import
``workspaces.models`` and must not hold a cross-layer ForeignKey to a workspace;
they carry a validated scalar ``workspace_id`` instead (ADR-001-R2).

Membership mutation is exposed only through the transactional functions below;
callers never write tenancy models directly.
"""

from workspaces.roles import WorkspaceOperation

from ._admin_transfer import WorkspaceOwnershipTransferResult, admin_transfer_workspace_ownership
from ._authorization import (
    WorkspaceAuthorization,
    WorkspaceAuthorizationError,
    authorize_bound_workspace,
    authorize_launch_workspace_locked,
    authorize_workspace,
    authorized_workspace_ids,
)
from ._context import (
    ActorWorkspaceContext,
    OrganizationRef,
    list_actor_workspace_contexts,
)
from ._egress import set_workspace_egress_policy, workspace_egress_policy
from ._invitations import (
    WORKSPACE_INVITATION_SIGNING_SALT,
    WORKSPACE_INVITATION_TOKEN_MAX_AGE_SECONDS,
    WorkspaceInvitationClaim,
    WorkspaceInvitationError,
    WorkspaceInvitationProjection,
    accept_workspace_invitation,
    issue_workspace_invitation,
    list_workspace_invitations,
    resend_workspace_invitation,
    revoke_workspace_invitation,
    stage_workspace_invitation_token,
)
from ._lifecycle import (
    WorkspaceAuditContext,
    WorkspaceLifecycleError,
    WorkspaceProjection,
    archive_workspace,
    create_workspace,
    get_workspace,
    list_workspaces,
    rename_workspace,
    restore_workspace,
    transfer_workspace_ownership,
)
from ._memberships import (
    MembershipAuditContext,
    WorkspaceMembershipError,
    WorkspaceMembershipProjection,
    add_workspace_member,
    change_workspace_member_role,
    get_self_membership,
    leave_workspace,
    list_workspace_memberships,
    remove_workspace_member,
)
from ._model_access import (
    ModelAccessOrganizationScope,
    ModelAccessWorkspaceScope,
    resolve_model_access_organization,
    resolve_model_access_workspace,
)
from ._organization import (
    OrganizationAuditContext,
    OrganizationAuthorizationError,
    OrganizationProfile,
    OrganizationValidationError,
    get_organization_profile,
    list_administrable_organizations,
    resolve_administrable_organization,
    update_organization_profile,
)
from ._personal import resolve_personal_workspace
from ._quota import (
    QuotaVerdict,
    WorkspaceQuotaAuditContext,
    WorkspaceQuotaError,
    WorkspaceQuotaRejected,
    admit_workspace_member_seat,
    record_workspace_quota_rejection,
    release_workspace_concurrent_range,
    reserve_workspace_concurrent_range,
)
from ._quota_admin import (
    WorkspaceQuotaDecisionView,
    WorkspaceQuotaProjection,
    WorkspaceResourceUsage,
    set_workspace_quota_policy,
    workspace_quota_usage,
)
from ._range_scope_admin import RangeRebindAuthorization, authorize_range_rebind

# ``WorkspaceOperation`` is re-exported here on purpose: callers name the
# operation they want authorized, and the facade is the only module they may
# import (ADR-001-R1). The role vocabulary is NOT re-exported -- no other layer
# has business reading or comparing a role code.
__all__ = [
    "WORKSPACE_INVITATION_SIGNING_SALT",
    "WORKSPACE_INVITATION_TOKEN_MAX_AGE_SECONDS",
    "ActorWorkspaceContext",
    "MembershipAuditContext",
    "ModelAccessOrganizationScope",
    "ModelAccessWorkspaceScope",
    "OrganizationAuditContext",
    "OrganizationAuthorizationError",
    "OrganizationProfile",
    "OrganizationRef",
    "OrganizationValidationError",
    "QuotaVerdict",
    "RangeRebindAuthorization",
    "WorkspaceAuditContext",
    "WorkspaceAuthorization",
    "WorkspaceAuthorizationError",
    "WorkspaceInvitationClaim",
    "WorkspaceInvitationError",
    "WorkspaceInvitationProjection",
    "WorkspaceLifecycleError",
    "WorkspaceMembershipError",
    "WorkspaceMembershipProjection",
    "WorkspaceOperation",
    "WorkspaceOwnershipTransferResult",
    "WorkspaceProjection",
    "WorkspaceQuotaAuditContext",
    "WorkspaceQuotaDecisionView",
    "WorkspaceQuotaError",
    "WorkspaceQuotaProjection",
    "WorkspaceQuotaRejected",
    "WorkspaceResourceUsage",
    "accept_workspace_invitation",
    "add_workspace_member",
    "admin_transfer_workspace_ownership",
    "admit_workspace_member_seat",
    "archive_workspace",
    "authorize_bound_workspace",
    "authorize_launch_workspace_locked",
    "authorize_range_rebind",
    "authorize_workspace",
    "authorized_workspace_ids",
    "change_workspace_member_role",
    "create_workspace",
    "get_organization_profile",
    "get_self_membership",
    "get_workspace",
    "issue_workspace_invitation",
    "leave_workspace",
    "list_actor_workspace_contexts",
    "list_administrable_organizations",
    "list_workspace_invitations",
    "list_workspace_memberships",
    "list_workspaces",
    "record_workspace_quota_rejection",
    "release_workspace_concurrent_range",
    "remove_workspace_member",
    "rename_workspace",
    "resend_workspace_invitation",
    "reserve_workspace_concurrent_range",
    "resolve_administrable_organization",
    "resolve_model_access_organization",
    "resolve_model_access_workspace",
    "resolve_personal_workspace",
    "restore_workspace",
    "revoke_workspace_invitation",
    "set_workspace_egress_policy",
    "set_workspace_quota_policy",
    "stage_workspace_invitation_token",
    "transfer_workspace_ownership",
    "update_organization_profile",
    "workspace_egress_policy",
    "workspace_quota_usage",
]
