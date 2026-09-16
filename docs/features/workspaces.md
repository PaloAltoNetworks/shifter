# Workspace Membership

Workspaces group people around a shared tenancy scope while each range keeps its
individual owner. Membership does not let one member open, change, or destroy
another member's range.

## Roles

Each workspace membership has one of three roles:

| Role | Membership permissions |
|------|------------------------|
| Owner | View the roster; add, remove, and change members; grant or revoke owner |
| Admin | View the roster; add, remove, and change admins or members |
| Member | View their own membership and leave the workspace |

A workspace must always keep at least one owner. Only an owner can grant or
revoke the owner role. Personal workspaces are compatibility spaces for
individual users: their owner cannot leave or be removed or demoted, and
collaborators cannot be added.

## Manage membership with the API

Workspace membership is available under `/api/v1/workspaces/{workspace_uuid}/`.
The API accepts the workspace's public UUID, never its internal database ID.

- `GET membership/` returns your own membership.
- `GET memberships/` returns the roster to an owner or admin.
- `POST memberships/` adds an existing active Shifter account by email.
- `POST memberships/{user_id}/role/` changes a member's role.
- `POST memberships/{user_id}/remove/` removes another member.
- `POST memberships/leave/` removes your own membership.

Session requests use the normal Shifter login and CSRF protection. API tokens
need `workspaces:membership:read` for reads and
`workspaces:membership:write` for changes. Token scopes do not replace role
checks: the token's active owner must also hold the required workspace role.

Adding a member does not send an invitation or create an account. The target
must already have an active Shifter account. Exact duplicate additions are
safe to retry; adding the same account with a different role returns a
conflict, and the role-change endpoint must be used instead.

Membership and role changes are transactional and recorded in the audit log.
Removing membership immediately revokes access to that workspace's bound range
surfaces, including lifecycle, lease, VPN, terminal, SSH, and RDP operations.
This applies to subsequent platform requests, downloads, and new sessions. It
does not terminate an already established terminal or Guacamole session or
invalidate a VPN profile that was already downloaded; range expiry and
system-owned cleanup continue even after membership removal.

## Invite a new member

The staff administration console provides invitation management at
`/administer/organization/workspaces/{workspace_uuid}/invitations`. A workspace
owner or admin can issue, list, resend, and revoke invitations when their current
role permits the matching operation. Owner invitations remain owner-only.

Invitation endpoints live under
`/api/v1/workspaces/{workspace_uuid}/invitations/` and accept browser sessions
only; platform API tokens cannot administer them. The issued credential is sent
by email and is never returned by the API. Acceptance requires a fresh,
provider-verified login using the invited email. Resending rotates the signed
credential, revocation invalidates it, and acceptance creates exactly one
membership without silently changing an existing role.

## Launch a range in a workspace

A range launch accepts an optional `workspace_uuid` naming the workspace the new
range belongs to. Omitting it launches into your personal workspace, so nothing
changes for a single-user install. When you supply it, you must be a member of
that workspace with a role that permits launching; an unknown or non-member
workspace is refused rather than quietly launched somewhere else. The launched
range still belongs to you individually—putting it in a shared workspace does
not let other members open, change, or destroy it. Only the workspace's public
UUID is accepted, never an internal identifier.
