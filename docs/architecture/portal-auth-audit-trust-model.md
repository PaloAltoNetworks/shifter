# Portal Auth & Audit Trust Model

Status: implemented (issue #937)

Documents the trust boundaries hardened in #937 for the Shifter portal:
dev-auth reachability, audit source-IP attribution, and the self-service
`user_type` claim. These four concepts are kept deliberately separate:
dev-auth reachability, request attribution, identity-provider claims, and
platform elevation.

## Dev-auth reachability

`/dev-login/` and `/dev-logout/` are unauthenticated by design and gated in two
layers (`config/dev_auth.py`):

1. **Hard environment gate** (`_is_dev_environment`): admits only when
   `DEBUG=True` or `ENVIRONMENT == "development"`. Every other environment
   returns 403 before any user lookup, login, or group mutation. Deployed dev
   and prod export `ENVIRONMENT=production`, so this is fail-closed.
2. **Direct-peer admission** (`_request_peer_allowed`): when `DEBUG` is False,
   admission is bound to the actual socket peer (`REMOTE_ADDR`) — the loopback
   range is always admitted (local dev and SSM/admin tunnels present as
   loopback) plus any `DEV_LOGIN_ALLOWED_CIDRS`. The spoofable `Host` header and
   `X-Forwarded-For` are never consulted for this decision. Django host
   validation (`ALLOWED_HOSTS`) protects URL construction only; it is not a
   dev-auth allowlist.

## Audit source-IP attribution

`risk_register.services.get_client_ip()` is the single canonical resolver for
HTTP audit `source_ip`. It delegates to `select_trusted_client_ip()`, which
trusts the **rightmost** (proxy-appended) `X-Forwarded-For` hop — the value the
ALB appends is the real client as seen by the trusted proxy — and falls back to
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
path from a claim to a group:

| `user_type`       | Reachable Django group |
| ----------------- | ---------------------- |
| `standard`        | (none)                 |
| `ctf_participant` | `CTF Participant`      |
| `ctf_organizer`   | `CTF Organizer`        |

**Invariant:** a self-assigned `user_type` can reach only these CTF-scoped
groups. It can never grant `is_staff`, `is_superuser`, the `Threat Research`
group, or CMS authoring (`shared.auth.can_edit_cms_authoring`, which requires
staff or Threat Research). Platform elevation stays env-email driven via
`config.bootstrap_admin.apply_bootstrap_admin_flags()`
(`PLATFORM_BOOTSTRAP_STAFF_EMAILS` / `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS`). A
`CTF Organizer` may manage CTF event surfaces; that is CTF scope, not platform
operator elevation. The invariant is enforced by
`tests/config/test_user_type_sync.py::TestClaimDerivedGroupInvariant`.

Participant-only surface enforcement remains server-side and event-scoped
(coordinated with #944); UI hiding is not enforcement.

## Audit trail for role changes

Every change a `user_type` sync produces is recorded by
`risk_register.services.audit_role_sync()` as an `AuditLog` row with
`entity_type=USER` and `action=ROLE_SYNC`, capturing the actor, subject user id,
old/new `user_type`, old/new CTF groups, source provider, and request context
(source IP / user agent / request id where request-bound). The write is
**fail-closed**: it runs inside the same transaction as the group/profile
mutation, so if the audit row cannot be persisted the mutation is rolled back.
Rows are queryable through the existing audit API (`AuditLogViewSet`) and admin
(`AuditLogAdmin`, filterable by `action`). No tokens, cookies, full headers, or
provider payloads are written to audit state.
