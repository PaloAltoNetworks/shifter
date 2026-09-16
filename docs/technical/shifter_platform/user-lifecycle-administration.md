# User lifecycle administration (technical)

This note describes the implementation of user lifecycle administration
(PLAT-236, issue #1943): account state transitions, administrator-triggered
password reset, and bounded ownership transfer. It is constrained by PLAT-241
(cloud-agnostic, proven components) and the architecture preflight at
`docs/architecture/user-lifecycle-administration-preflight-1943.md`.

## Account state model

`User.is_active` remains the single authentication-enforcement bit. The only
added persisted fact is `UserProfile.suspended_at` (a nullable timestamp).
The administrator-facing state is *derived*, never stored as a second enum that
could disagree with `is_active`:

| Derived state | Durable facts |
| --- | --- |
| active | `is_active=True`, no suspension, not deleted |
| suspended | `is_active=False`, `suspended_at` set, not deleted |
| deactivated | `is_active=False`, no suspension, not deleted |
| deleted | profile `deleted_at` set (also forces `is_active=False`) |

`management.lifecycle` owns the state machine:

- `derive_lifecycle_state(user)` computes the state from durable facts.
- `available_actions(user, actor)` returns the server-derived, authority-aware
  action hints the detail projection exposes.
- `transition_account(user, *, action, actor, audit)` is the one command for the
  closed action set (`activate`, `deactivate`, `suspend`, `delete`). It locks the
  user and profile rows, derives the current state, validates a closed transition
  table, updates `is_active` and `suspended_at` together, revokes the target's
  live API tokens for a disabling action, and writes one strict, request
  attributed `shared.audit` event in the same transaction. Repeating the current
  state is an idempotent no-op that writes no audit and claims no transition.

Guards enforced under the lock: no self-disable, a non-superuser cannot mutate a
superuser, and a disabling action never removes the last active superuser.

## Authentication enforcement

Deactivated, suspended, and soft-deleted accounts all hold `is_active=False`, so
every authentication path converges on that one bit:

- `config.oidc.ShifterOIDCBackend` and `config.identity_platform.IdentityPlatformBackend`
  return no principal from `get_user` for an inactive account, and refuse an
  inactive account in `authenticate`, so an existing provider session cannot
  reload and a provider re-login cannot reactivate a blocked account through
  claims sync.
- `shared.api_tokens.authentication.ApiTokenAuthentication` rejects a token whose
  owner is missing, inactive, or soft-deleted, on top of the token revocation the
  transition already performs.
- The local and CTF backends and the DRF permission and actor-resolution seams
  already gate `is_active`.

`management.services.mark_user_deleted` now also clears `is_active` so soft
deletion blocks authentication; migration
`management/migrations/0012_disable_soft_deleted_accounts.py` converges any
pre-existing soft-deleted accounts.

## Password reset

`management.password_reset` is an account-origin-aware dispatcher whose first
implementation is Django's local password reset. `reset_eligibility(user)` admits
only an active, local, non-CTF account with a usable password and a valid email.
`request_password_reset` consumes the shared `shared.credential_delivery` budget,
builds the link domain from the validated public origin (`shared.site_url`,
extracted so no domain copies the validator), records a strict, secret-free
audit event, and schedules Django's `PasswordResetForm` email on transaction
commit. The confirm and complete landing pages are wired at
`config.password_reset_views` using Django's proven reset-confirm views; the
confirm view records a strict audit event for the completed password change.

## Ownership transfer

The composition-root view `config.api_administer.AdministerTransferOwnershipView`
requires a **superuser** session (not merely `auth.change_user`), resolves and
authorizes the source and replacement accounts, then delegates to
`cms.services.transfer_user_ownership`. Requiring a superuser closes the
escalation where a staff user holding `auth.change_user` and a membership in
another tenant's workspace could seize ranges; a superuser already holds
cross-tenant root authority, so the transfer is not an escalation. CMS is the
single layer permitted to import both `engine.services` and `workspaces.services`
(ADR-001), so the one bounded, per-kind orchestration lives there rather than at
the composition root.

The manifest is a closed set of resource kinds; there is no wildcard, generic
`owner_id` rewrite, or reflective scan:

- **ranges** delegate per range to `cms.services.reassign_range_owner`, which
  preserves the CMS and Engine ownership projections, the new owner's workspace
  membership requirement, active-range uniqueness, and the live-VPN refusal.
- **workspaces** delegate to `workspaces.services.admin_transfer_workspace_ownership`,
  the platform-administrator offboarding override accepted by ADR-046-R13. It
  transfers non-personal workspaces the source owns to a replacement who already
  holds a membership, promotes the replacement to owner before demoting the
  source (preserving the last-owner invariant), excludes personal workspaces, and
  writes a strict audit per workspace.

Workspaces are transferred before ranges so a replacement promoted to workspace
owner then satisfies the membership requirement for that workspace's ranges. The
view records a bounded, secret-free summary audit of the offboarding action.

## API surface

All routes extend `/api/v1/administer/users/`:

- `POST .../<pk>/lifecycle/` (`auth.change_user`): activate, deactivate, suspend.
- `POST .../<pk>/reset-password/` (`auth.change_user`): trigger a Django reset.
- `POST .../<pk>/transfer-ownership/` (superuser session): the offboarding
  transfer, served at the composition root.
- `POST .../<pk>/set-active/` and `POST .../<pk>/delete/` remain as v1
  compatibility adapters that delegate to the one transition service.

The detail projection adds server-derived `lifecycle_state` and
`available_actions`. The SPA (`frontend/src/features/administer/UserDetailPage.tsx`)
renders the actions and reports transfer results; it never reconstructs the
transition or reset-eligibility policy, and every endpoint reauthorizes.
