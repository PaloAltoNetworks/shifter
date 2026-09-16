# User lifecycle administration

User lifecycle administration lets an administrator manage the state of a user
account across its life on a shared deployment: activate, deactivate, suspend and
reinstate an account, trigger a password reset, and reassign a departing user's
owned resources to a replacement. It extends the existing **Administer → Users**
surface and its detail page.

## Access

- The actions are visible only to staff accounts and only when the
  `administer_spa` rollout flag is on.
- Lifecycle transitions and password reset require the Django `auth.change_user`
  permission; soft delete requires `auth.delete_user`. A staff session alone is
  not sufficient, and the server rechecks the permission on every request.
- Transfer ownership is a root-level offboarding action and requires a superuser
  session, not merely `auth.change_user`.
- The buttons a page shows are advisory. The server derives the actions that
  apply to each account and reauthorizes every request, so a hidden or disabled
  control is never the only thing standing between a caller and an action.

## Account states

An account is always in exactly one lifecycle state, shown on the user detail
page:

- **Active**: the account can sign in.
- **Suspended**: a temporary security hold. The account cannot sign in, but its
  assignments and owned resources are retained. Reinstate the account to lift the
  suspension.
- **Deactivated**: a reversible offboarding block. The account cannot sign in.
  It is distinct from deletion and from suspension, and it is reversible by
  activating the account.
- **Deleted**: the account has been soft-deleted. It cannot sign in and does not
  appear in the default user list. This is not a permanent erasure and does not
  anonymize the account or unbind its identity.

Suspending, deactivating, or deleting an account signs the user out, blocks
subsequent sign-in, and revokes the account's live API tokens. Reactivating an
account restores sign-in only; it does not restore revoked tokens.

The platform protects against locking itself out: you cannot suspend,
deactivate, or delete your own account, a non-superuser cannot change the state
of a superuser account, and the last active superuser cannot be disabled.

## Password reset

The **Reset password** action emails the user a link to set a new password using
the platform's standard reset flow. It is available only for local accounts with
a usable password and a valid email address:

- A provider-bound account (one that signs in through the identity provider)
  resets its credential at that provider, not here.
- A temporary event account keeps its own event-scoped credential flow.

The action returns only whether the request was accepted. The reset link is
delivered by email only and is never shown in the interface.

## Transfer ownership

The **Transfer ownership** action reassigns a departing user's owned resources to
a replacement account during offboarding. You choose the replacement account and
which kinds of resource to transfer:

- **Ranges**: the departing user's ranges move to the replacement, keeping their
  workspace scope. A range whose participant VPN credential is still live is
  reported as blocked rather than transferred; destroy that range's generation
  and provision a replacement instead.
- **Workspaces**: workspaces the departing user owns move to the replacement,
  provided the replacement already holds a membership in the workspace. A
  workspace the replacement is not a member of is reported as blocked and is
  never silently rehomed. Personal workspaces are never transferred.

The result summarizes how many resources were transferred and how many were
blocked. Transfer moves ownership only. It does not remove memberships, change
roles, move stored credentials or agents, or rewrite the historical record of
who did what.

## What these actions do not do

- They do not permanently erase or anonymize an account.
- They do not delete or disable the account at the identity provider.
- They do not recall a VPN profile a user already downloaded or tear down a
  remote session (SSH, RDP, or a desktop gateway) that was already established;
  those are governed by their own credential and session lifecycles.
