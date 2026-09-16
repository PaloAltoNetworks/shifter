# Organization/workspace admin console

The organization/workspace admin console is the staff-facing area for
administering organizations and workspaces. It lives under **Administer →
Organization** in the platform navigation and is the shell that the
per-capability administration surfaces (membership, invitations, users, range
scoping, policy, quota, and audit) attach to as they ship.

## Access

- The console is visible only to staff accounts and only when the
  `administer_spa` rollout flag is on. When the flag is off, the console and its
  navigation entry are hidden and the routes are not served.
- Access to the console (a staff session) is separate from authority inside a
  workspace. Being staff lets you open the console; it does not grant any
  workspace operation. Each workspace action is authorized by your role in that
  workspace, and the server re-checks it on every request.
- **Django admin** remains available as a full-page escape hatch from the
  Administer sidebar in every rollout state, for the deep or rarely used
  administration the console does not duplicate.

## Working in the console

- The console lists the organizations and workspaces you belong to. Your role in
  each workspace is shown next to it.
- A **workspace switcher** selects the workspace you are administering. The
  selected workspace is part of the page address, so you can bookmark or share a
  link to a specific workspace. Opening a link to a workspace you do not belong
  to shows a "workspace not found" message rather than silently switching you to
  a different workspace.
- Within a selected workspace, the section navigation reflects what your role
  permits: sections your role cannot use are shown but disabled. This is a
  display aid only; the underlying endpoints enforce access regardless of what
  the navigation shows.

## Organization settings

**Administer → Organization → Organization settings** lets an organization
administrator view and edit their organization's profile: its display name,
description, support email, and support URL. If you administer more than one
organization the surface first lists them so you can choose which to edit;
otherwise it opens the one you administer directly.

- **Who can edit.** Editing an organization is restricted to that
  organization's administrators. Being able to open the admin console (a staff
  session) does not by itself let you edit an organization—organization
  administration is a separate authority. A platform superuser can administer
  any organization; every such change is recorded in the audit log.
- **What is saved.** Only the fields you change are written. Leaving a field
  empty clears it. Invalid input (for example a malformed support email) is
  rejected with a message next to the field, and nothing is saved until it is
  corrected.
- Organization logos and other branding assets are not part of this surface;
  they will arrive with their own release once their storage and safety handling
  is defined.

## Workspaces

**Administer → Organization → Workspaces** lists the workspaces in an
organization you administer and lets you create and manage them. If you
administer more than one organization you choose the organization first;
otherwise it opens the one you administer.

- **Create.** Give the workspace a name that is unique within the organization.
  You become its owner. Personal workspaces are created automatically for each
  user and are not created or managed here.
- **List and search.** The list shows active workspaces by default; a toggle
  includes archived ones. Search filters by name.
- **Rename.** A workspace owner or admin can rename a workspace. Names stay
  unique within the organization.
- **Archive and restore.** Archiving hides a workspace from the default list
  without deleting anything—ranges bound to the workspace are left untouched.
  Restoring brings it back. Archiving is fully reversible.
- **Transfer ownership.** A workspace owner can hand ownership to another
  existing member of the workspace: the new owner is promoted and the previous
  owner becomes an admin, so the workspace always keeps an owner.
- **Who can do what.** Creating and listing workspaces requires organization
  administrator authority for that organization. Renaming, archiving, restoring,
  and transferring are authorized by your role in that specific workspace (owner
  or admin; transfer is owner-only). The server re-checks every action; the
  console never decides access on its own. Personal workspaces cannot be
  created, renamed, archived, or transferred here.

## Membership and roles

**Administer → Organization → Workspaces → (a workspace) → Membership** manages
who belongs to a workspace and the role each member holds. Roles come from a
fixed, closed set: **owner**, **admin**, and **member**.

- **Roster.** Owners and admins see the full membership roster: each member's
  name, role, and when they joined.
- **Add a member.** Owners and admins can add an existing account to the
  workspace by email and assign it a role. This adds an account that already
  exists; it does not send an invitation or create a new account.
- **Change a role.** Owners and admins can change a member's role from the
  roster.
- **Remove a member.** Owners and admins can remove another member after a
  confirmation. Removing a member does not delete their account.
- **Leave.** Any member can leave a workspace they belong to. A member who
  cannot see the roster still sees a simple self-service view that shows their
  own role and lets them leave.
- **The last owner is protected.** A workspace always keeps at least one owner.
  The last remaining owner cannot be removed, demoted, or leave; the console
  shows this clearly and disables those actions. To move on, add or promote
  another owner, or transfer ownership from the workspace overview, first.
- **Who can do what.** The actions you see are driven by what your role in that
  specific workspace permits, as reported by the server. Seeing an action is not
  the same as being allowed to complete it: the server re-checks every action
  and is the final authority. Managing owners is restricted to owners, so an
  admin may be shown an action on an owner that the server then declines.

## Invite and onboard members

**Administer → Organization → Workspaces → (a workspace) → Invitations** lets a
staff user who is also a workspace owner or admin invite a person who does not
yet have a Shifter account.

- Enter the recipient's email and choose the closed workspace role. Only a
  workspace owner can issue an owner invitation.
- The recipient gets a time-limited link. They must authenticate through the
  configured identity provider with that verified email address; Shifter then
  creates the membership atomically. An invitation never creates a placeholder
  account and never changes an existing member's role.
- Pending invitations can be resent, which invalidates every earlier link, or
  revoked immediately. Expired links can be resent to issue a fresh expiry.
- The invitation list shows the recipient, role, derived status, and expiry. It
  never displays or returns the signed invitation credential.
- Invitation administration requires a staff browser session and current
  workspace authority. Platform API tokens are deliberately rejected.

If a link is invalid, expired, revoked, already consumed, or used by a different
verified identity, the recipient sees a bounded failure message and should ask a
workspace administrator to send a new invitation.

## Network egress policy

Each workspace has a network egress policy that controls outbound internet
access for the ranges launched in it. An owner or admin sets it on the workspace
detail surface. Two choices are available:

- **Inherit deployment baseline** (the default): ranges keep the deployment's
  existing network posture, so behavior is unchanged from before this setting
  existed.
- **Zero egress (no outbound NAT path)**: newly provisioned ranges have no
  outbound path to the internet. On AWS the participant subnets receive no
  default route, NAT, or internet-gateway path. On GCP the range's subnets are
  attached to no Cloud NAT and the guests have no external address, so a
  guest cannot reach the internet even though internal range traffic and the
  management fabric still work.

The policy applies only to ranges provisioned after the change; it never alters
a range that is already running. Changing it is audited (the old and new value
are recorded) and authorized by the workspace role, the same as rename and
archive. Personal workspaces can set the policy too, so a single-user install
can opt its own ranges into zero egress.

## Resource quotas and usage

Each workspace can carry per-resource limits so shared infrastructure such as a
university or lab cannot be exhausted by a single workspace. Two resources are
limited:

- **Concurrent ranges**: how many ranges the workspace may have running at once.
- **Member seats**: how many members the workspace may hold.

The **Quota** surface shows an owner or admin the current usage against each
limit, and a history of when a limit was applied. A resource with no configured
limit shows as unlimited, which preserves the prior behavior for every workspace
that has not had a limit set.

Each limit is either a soft cap or a hard cap:

- A **hard cap** blocks the over-limit action. Launching a range past the
  concurrent-range limit is refused, and adding a member past the seat limit is
  refused.
- A **soft cap** allows the action but records that the limit was exceeded, so an
  administrator can see the overage on the Quota surface and in the deployment
  audit history.

Every quota decision is recorded, and each applied limit (a soft-cap warning or a
hard-cap block) also appears in the administrator audit history. Lowering a limit
below the current usage never evicts members or destroys running ranges; it only
governs subsequent actions. Enforcement runs in the portal before any cloud
resource is created, so it behaves identically on AWS and GCP.

Setting a limit is a platform-administration task rather than a workspace-role
action, so the Quota surface is read-only. A platform administrator sets limits
through the Django administration interface.

## What is not here yet

This release delivers the console shell, navigation, workspace context,
switcher, the organization settings surface, the workspace lifecycle surface,
the membership, roles, invitation, and resource-quota surfaces above. The
remaining administration surfaces (user lifecycle, range scoping, and policy)
arrive in later releases; their sections are present as placeholders until then.
