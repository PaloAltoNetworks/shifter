"""Closed workspace role and operation vocabularies (ADR-046-R2/R8)."""

from django.db import models


class WorkspaceRole(models.TextChoices):
    """Roles a user may hold in a workspace."""

    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MEMBER = "member", "Member"


class OrganizationRole(models.TextChoices):
    """Roles a user may hold at the organization level (ADR-048).

    Distinct from :class:`WorkspaceRole`: organization authority is a separately
    accepted, persisted seam and is never derived from a workspace role, Django
    staff/groups, model permissions, identity-provider claims, API-token scopes,
    or cloud roles. The vocabulary is closed and starts with a single
    ``admin`` role; it is fail-closed, so a role code outside it carries no
    authority.
    """

    ADMIN = "admin", "Admin"


class WorkspaceOperation(models.TextChoices):
    """Operations the workspace authorization seam can be asked about."""

    LAUNCH_RANGE = "launch_range", "Launch a range in the workspace"
    REASSIGN_RANGE = "reassign_range", "Reassign a range within the workspace"
    READ_RANGE = "read_range", "Read an owned range in the workspace"
    MANAGE_RANGE = "manage_range", "Manage an owned range in the workspace"
    ACCESS_RANGE = "access_range", "Access an owned range in the workspace"
    READ_SELF_MEMBERSHIP = "read_self_membership", "Read own workspace membership"
    READ_MEMBERS = "read_members", "Read the workspace membership roster"
    ADD_MEMBER = "add_member", "Add a workspace member"
    CHANGE_MEMBER_ROLE = "change_member_role", "Change a workspace member role"
    REMOVE_MEMBER = "remove_member", "Remove a workspace member"
    LEAVE_WORKSPACE = "leave_workspace", "Leave the workspace"
    READ_INVITATIONS = "read_invitations", "Read workspace invitations"
    ISSUE_INVITATION = "issue_invitation", "Issue a workspace invitation"
    RESEND_INVITATION = "resend_invitation", "Resend a workspace invitation"
    REVOKE_INVITATION = "revoke_invitation", "Revoke a workspace invitation"
    READ_WORKSPACE = "read_workspace", "Read a workspace's administrative detail"
    RENAME_WORKSPACE = "rename_workspace", "Rename the workspace"
    ARCHIVE_WORKSPACE = "archive_workspace", "Archive the workspace"
    RESTORE_WORKSPACE = "restore_workspace", "Restore an archived workspace"
    SET_EGRESS_POLICY = "set_egress_policy", "Set the workspace network egress policy"
    TRANSFER_OWNERSHIP = "transfer_ownership", "Transfer workspace ownership"
    LIST_RANGE_SCOPE_BINDINGS = "list_range_scope_bindings", "List ranges scoped to the workspace"
    REBIND_RANGE_WORKSPACE = "rebind_range_workspace", "Reassign a range's workspace scope"
    USE_CTF_COMMUNICATIONS = "use_ctf_communications", "Use CTF communications scoped to the workspace"
    PUBLISH_MODEL_ACCESS = "publish_model_access", "Publish model access for the workspace"


#: Role-to-operation policy. Callers must not re-derive permissions from a role
#: code themselves. Resource operations remain additive to the existing
#: per-range owner/source/lifecycle/access gates.
_RESOURCE_OPERATIONS = frozenset(
    {
        WorkspaceOperation.LAUNCH_RANGE.value,
        WorkspaceOperation.REASSIGN_RANGE.value,
        WorkspaceOperation.READ_RANGE.value,
        WorkspaceOperation.MANAGE_RANGE.value,
        WorkspaceOperation.ACCESS_RANGE.value,
        WorkspaceOperation.READ_SELF_MEMBERSHIP.value,
        WorkspaceOperation.LEAVE_WORKSPACE.value,
    }
)
_MEMBERSHIP_MANAGEMENT_OPERATIONS = frozenset(
    {
        WorkspaceOperation.READ_MEMBERS.value,
        WorkspaceOperation.ADD_MEMBER.value,
        WorkspaceOperation.CHANGE_MEMBER_ROLE.value,
        WorkspaceOperation.REMOVE_MEMBER.value,
    }
)
_INVITATION_OPERATIONS = frozenset(
    {
        WorkspaceOperation.READ_INVITATIONS.value,
        WorkspaceOperation.ISSUE_INVITATION.value,
        WorkspaceOperation.RESEND_INVITATION.value,
        WorkspaceOperation.REVOKE_INVITATION.value,
    }
)
# Workspace lifecycle administration (#1940). Owner and admin may read the
# administrative detail, rename, archive, restore, and set the network egress
# policy (#1945, PLAT-238) of a workspace; transferring ownership is owner-only,
# mirroring the owner-authority rule the membership service already enforces for
# managing owners.
_WORKSPACE_ADMIN_OPERATIONS = frozenset(
    {
        WorkspaceOperation.READ_WORKSPACE.value,
        WorkspaceOperation.RENAME_WORKSPACE.value,
        WorkspaceOperation.ARCHIVE_WORKSPACE.value,
        WorkspaceOperation.RESTORE_WORKSPACE.value,
        WorkspaceOperation.SET_EGRESS_POLICY.value,
        WorkspaceOperation.PUBLISH_MODEL_ACCESS.value,
    }
)
_OWNER_ONLY_OPERATIONS = frozenset({WorkspaceOperation.TRANSFER_OWNERSHIP.value})
# Range-to-workspace scope administration (#1944, PLAT-237). Owner and admin may
# list the ranges scoped to a workspace and reassign a range's workspace scope.
# These are deliberately distinct from the per-range REASSIGN_RANGE (ownership
# handover) and READ_RANGE (own-range access) operations: scope administration is
# cross-owner administrative authority, not additive per-range access, so it is
# never granted to a plain member (ADR-046-R14).
_RANGE_SCOPE_ADMIN_OPERATIONS = frozenset(
    {
        WorkspaceOperation.LIST_RANGE_SCOPE_BINDINGS.value,
        WorkspaceOperation.REBIND_RANGE_WORKSPACE.value,
    }
)
# Tenancy-membership proofs (ADR-051, #2048). These prove only that the actor is
# a member of the workspace; they carry no resource, membership, or product
# authority of their own. USE_CTF_COMMUNICATIONS lets CTF confine a communication
# campaign to a workspace the actor belongs to; per-event and recipient authority
# is decided separately in CTF, never granted by this proof.
_TENANCY_MEMBERSHIP_OPERATIONS = frozenset({WorkspaceOperation.USE_CTF_COMMUNICATIONS.value})

ROLE_OPERATIONS: dict[str, frozenset[str]] = {
    WorkspaceRole.OWNER.value: (
        _RESOURCE_OPERATIONS
        | _MEMBERSHIP_MANAGEMENT_OPERATIONS
        | _INVITATION_OPERATIONS
        | _WORKSPACE_ADMIN_OPERATIONS
        | _RANGE_SCOPE_ADMIN_OPERATIONS
        | _OWNER_ONLY_OPERATIONS
        | _TENANCY_MEMBERSHIP_OPERATIONS
    ),
    WorkspaceRole.ADMIN.value: (
        _RESOURCE_OPERATIONS
        | _MEMBERSHIP_MANAGEMENT_OPERATIONS
        | _INVITATION_OPERATIONS
        | _WORKSPACE_ADMIN_OPERATIONS
        | _RANGE_SCOPE_ADMIN_OPERATIONS
        | _TENANCY_MEMBERSHIP_OPERATIONS
    ),
    WorkspaceRole.MEMBER.value: _RESOURCE_OPERATIONS | _TENANCY_MEMBERSHIP_OPERATIONS,
}

# Operations that additionally require the workspace to be active (not archived).
# The generic role-to-operation policy above proves membership; an archived
# workspace still lets a member read its history but must not accept new
# authoring/release work. This set is enforced once inside the authorization
# service (workspaces.services), never by a consumer reading ``archived_at``.
_ACTIVE_WORKSPACE_OPERATIONS = frozenset(
    {
        WorkspaceOperation.PUBLISH_MODEL_ACCESS.value,
        WorkspaceOperation.USE_CTF_COMMUNICATIONS.value,
    }
)


def role_permits(role: str, operation: str) -> bool:
    """Return True when ``role`` is allowed to perform ``operation``.

    Unknown roles and unknown operations are denied: the policy is fail-closed,
    so a role code that predates a vocabulary change never silently gains
    authority.
    """
    return operation in ROLE_OPERATIONS.get(role, frozenset())


def operation_requires_active_workspace(operation: str) -> bool:
    """Return True when ``operation`` must be denied on an archived workspace."""
    return operation in _ACTIVE_WORKSPACE_OPERATIONS
