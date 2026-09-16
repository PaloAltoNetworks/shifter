# Portal Auth & Audit Trust Model

Status: implemented (issues #937, #1516)

Documents the trust boundaries hardened in #937 for the Shifter portal:
dev-auth reachability, audit source-IP attribution, and the self-service
`user_type` claim. These four concepts are kept deliberately separate:
dev-auth reachability, request attribution, identity-provider claims, and
platform elevation. Issue #1516 tightened the identity-provider boundary
further: organizer authority is no longer derivable from self-service identity
data (see "Self-service `user_type`" and "Organizer authority" below).

## Dev-auth reachability

`/dev-login/` and `/dev-logout/` are unauthenticated by design and gated in two
layers (`config/dev_auth.py`):

1. **Hard environment gate** (`_is_dev_environment`): admits only when
   `DEBUG=True` or `ENVIRONMENT == "development"`. Every other environment
   returns 403 before any user lookup, login, or group mutation. Deployed dev
   and prod export `ENVIRONMENT=production`, so this is fail-closed.
2. **Direct-peer admission** (`_request_peer_allowed`): when `DEBUG` is False,
   admission is bound to the actual socket peer (`REMOTE_ADDR`): the loopback
   range is always admitted (local dev and SSM/admin tunnels present as
   loopback) plus any `DEV_LOGIN_ALLOWED_CIDRS`. The spoofable `Host` header and
   `X-Forwarded-For` are never consulted for this decision. Django host
   validation (`ALLOWED_HOSTS`) protects URL construction only; it is not a
   dev-auth allowlist.

## Audit source-IP attribution

`shared.audit.get_client_ip()` is the single canonical resolver for
HTTP audit `source_ip`. It delegates to `select_trusted_client_ip()`, which
trusts the **rightmost** (proxy-appended) `X-Forwarded-For` hop (the value the
ALB appends is the real client as seen by the trusted proxy), and falls back to
`REMOTE_ADDR` when the chain is absent, shorter than the trusted hop count, or
the selected token is not a valid IP. The client-controlled leftmost value is
never trusted. The number of trusted proxy hops is configured by
`AUDIT_TRUSTED_PROXY_HOPS` (default 1, modelling the single ALB). The WebSocket
terminal consumer (`mission_control/consumers.py`) reuses the same hop policy on
the ASGI scope so terminal audit rows do not drift from HTTP rows.

## Self-service `user_type` and the CTF-only invariant

`custom:user_type` is self-mutable by design (accepted maintainer decision,
2026-06-10). The safety control is a durable, reviewable audit trail plus a
structural invariant, not attribute locking.

`config.user_type_sync.sync_user_type()` is the single helper that turns a
claimed `user_type` into CTF group membership, shared by Cognito OIDC, GCP
Identity Platform, and dev-login. The mapping (`USER_TYPE_TO_GROUP`) is the only
path from a self-service claim to a group, and since #1516 it reaches only the
participant group:

| `user_type`       | Reachable Django group |
| ----------------- | ---------------------- |
| `standard`        | (none)                 |
| `ctf_participant` | `CTF Participant`      |
| `ctf_organizer`   | (none; unrecognized on this path since #1516) |

**Invariant (tightened by #1516):** a self-assigned `user_type` can reach only
the `CTF Participant` group. It can never grant `CTF Organizer`, `is_staff`,
`is_superuser`, the `Threat Research` group, or CMS authoring
(`shared.auth.can_edit_cms_authoring`, which requires staff or Threat Research).
A `ctf_organizer` claim is treated as unrecognized here and grants nothing; the
self-service sync also never *removes* an admin-granted `CTF Organizer` group (a
`standard` claim clears participant membership only). Platform elevation stays
env-email driven via `config.bootstrap_admin.apply_bootstrap_admin_flags()`
(`PLATFORM_BOOTSTRAP_STAFF_EMAILS` / `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS`). The
invariant is enforced by
`tests/config/test_user_type_sync.py::TestClaimDerivedGroupInvariant` and
`::TestSelfServiceCannotAcquireOrganizer`.

Participant-only surface enforcement remains server-side and event-scoped
(coordinated with #944); UI hiding is not enforcement.

## Organizer authority (administrator-controlled)

`CTF Organizer` gates the CTF admin surface (`/ctf/admin/*`, participant/bracket/
notification management via `ctf.views._access.ctf_organizer_required` and
`ctf.api._base`) and participant range provisioning through `ctf.services`, so it
is privileged authority, not merely participant scope. Since #1516 it is granted
only from administrator-controlled sources, never from self-service identity data.
`config.organizer_authority` is the single seam:

- **Verified provider group evidence.** The admin-managed `cognito:groups` claim
  (captured from the already-verified OIDC / Identity Platform payload by
  `config.cognito_groups`) is mapped to `CTF Organizer` through one exact,
  settings-driven allowlist, `CTF_ORGANIZER_PROVIDER_GROUPS`. It is audited and
  **fail-closed**: an empty/unset allowlist disables the provider path entirely,
  and only `CTF Organizer` is ever reachable (never staff/superuser or arbitrary
  groups). Unknown provider groups are ignored.
- **Explicit local assignment.** A superuser adds a user to `CTF Organizer` in
  the Django admin; dev-login grants it through the same audited helper on the
  dev-only, peer-restricted path.

The provider group is authoritative for provider-derived authority, so login
reconciliation both grants **and revokes**: a verified login with an allowlisted
provider group grants organizer, and a later verified login *without* it revokes
the membership when (and only when) it was provider-derived. Provenance is
tracked on `UserProfile.organizer_grant_source` (`provider` / `local`): explicit
local assignments and unknown-provenance memberships are never auto-revoked, and
a missing/empty allowlist neither grants nor revokes (config absence cannot strip
authority). Grant and revoke are each written as fail-closed `ROLE_SYNC` audit
rows.

**Migration / re-grant runbook.** Because pre-#1516 organizer memberships were
reachable from self-service claims, migration
`management/migrations/0008_revoke_self_service_organizers` revokes `CTF
Organizer` from every existing member (each removal audited) when it applies.
After deploying #1516, re-grant legitimate organizers either by adding them to an
allowlisted `CTF_ORGANIZER_PROVIDER_GROUPS` provider group (they regain organizer
on next login) or by adding the `CTF Organizer` group directly in the Django
admin. This is enforced by `tests/config/test_organizer_authority.py` and
`tests/management/test_revoke_organizers_migration.py`.

## Audit trail for role changes

Every change a `user_type` sync produces is recorded by
`shared.audit.audit_role_sync()` as an `AuditLog` row with
`entity_type=USER` and `action=ROLE_SYNC`, capturing the actor, subject user id,
old/new `user_type`, old/new CTF groups, source provider, and request context
(source IP / user agent / request id where request-bound). The write is
**fail-closed**: it runs inside the same transaction as the group/profile
mutation, so if the audit row cannot be persisted the mutation is rolled back.
Rows are queryable through the existing audit API (`AuditLogViewSet`) and admin
(`AuditLogAdmin`, filterable by `action`). No tokens, cookies, full headers, or
provider payloads are written to audit state.
