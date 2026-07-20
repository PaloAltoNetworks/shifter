# Security Identity/Organizer Authorization Preflight (#1516)

Status: pre-implementation guidance

Date: 2026-07-11

Issue: GitHub #1516, "REV1 Security: separate self-service identity from
organizer authorization"

This issue is requirement-free. The GitHub issue title, body, acceptance
criteria, and `docs/architecture/rev1/security.md` are the shipping contract.
This note is intentionally not an implementation plan.

## Scope Boundary

Treat this as a correction to the #937 user-type mapping boundary, not as a new
RBAC, identity-provider, audit, or CTF workflow framework.

Keep these concepts separate:

1. Self-service identity/profile data: `custom:user_type`, `user_type`,
   `UserProfile.user_type`, active CTF event selection, and participant-facing
   routing state.
2. Participant authority: CTF participant registration and event-scoped
   participant services.
3. Organizer authority: `CTF Organizer` group membership and all CTF organizer
   views, DRF permissions, event creation, event ownership management,
   participant administration, and range provisioning/cleanup workflows.
4. Platform elevation: Django `is_staff`, `is_superuser`, `Threat Research`,
   CMS authoring, Risk Register privileged access, and Django admin access.
5. Provider evidence: verified, administrator-controlled provider group/role
   claims captured from the already-verified auth provider payload.

The invariant for this issue is stricter than #937: self-service claims may not
grant `CTF Organizer`, staff, superuser, `Threat Research`, or provisioning
authority. Organizer authority must be derived from administrator-controlled
provider evidence or explicit local administrator assignment, then audited.

## Architecture Decisions

- Remove `CTF Organizer` from any self-service `user_type`/profile-derived
  mapping. `ctf_organizer` may remain a legacy stored value only if needed for
  compatibility/migration, but it must not be sufficient to add or retain
  organizer authority.
- Keep participant synchronization in the existing `config.user_type_sync`
  seam, but narrow it so claim/profile sync cannot create privileged Django
  groups. Participant self-registration flows remain event-scoped and must keep
  using the CTF participant services.
- Derive privileged CTF authority from verified provider claims that are
  administrator-controlled. Reuse `config.cognito_groups` and
  `UserProfile.cognito_groups` as the existing provider-group capture seam
  unless implementation proves a different provider-neutral name is necessary.
- Map provider group names to local privileged groups through one explicit
  allowlisted mapping. The mapping may grant `CTF Organizer`; it must not be
  open-ended, must not create arbitrary Django groups, and must never grant
  staff/superuser flags.
- Keep staff/superuser assignment owned by
  `config.bootstrap_admin.apply_bootstrap_admin_flags()` and the
  `PLATFORM_BOOTSTRAP_STAFF_EMAILS` /
  `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` runtime contract.
- Continue to authorize CTF organizer endpoints through the existing
  `shared.auth` group constants, `ctf.bridges.get_user_role`,
  `ctf.views._access.ctf_organizer_required`, and `ctf.api._base`
  permissions. Do not duplicate organizer checks in provider code.
- Existing organizer memberships must be audited and migrated with a clear
  source classification: provider-authoritative, locally assigned, or removed.
  The migration must not silently grandfather self-service-derived organizer
  authority.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1516 |
| --- | --- | --- |
| Self-service user-type sync | `config.user_type_sync.sync_user_type`, `USER_TYPE_TO_GROUP`, `tests/config/test_user_type_sync.py` | Narrow this path so self-service claims cannot reach `CTF Organizer` or platform groups. |
| Provider group capture | `config.cognito_groups.sync_cognito_groups_from_claims`, `normalize_cognito_groups`, `UserProfile.cognito_groups`, `tests/risk_register/test_cognito_group_access.py` | Extend/reuse the verified provider-group snapshot instead of adding another raw-claim parser. |
| Provider verification | `config.oidc.ShifterOIDCBackend`, `config.identity_platform.IdentityPlatformBackend`, `config.views.identity_platform_session` | Provider-specific token/email/MFA checks run before any privileged group sync. |
| Bootstrap admin | `config.bootstrap_admin.apply_bootstrap_admin_flags` | Staff/superuser remains email-env driven, not provider-group or profile driven unless a future issue changes that explicitly. |
| Local role constants/predicates | `shared.auth` group constants, `get_user_group_names`, `is_ctf_organizer`, `is_ctf_participant`, `is_ctf_participant_only`, `can_edit_cms_authoring` | Keep local authorization predicates centralized; do not introduce competing role constants. |
| CTF role bridge | `ctf.bridges.get_user_role` | CTF views and APIs continue to read Django group state through the bridge. |
| Organizer HTTP decorators | `ctf.views._access.ctf_organizer_required`, `_check_event_ownership`, `ctf.services.authorization.assert_actor_owns_event` | Group admission is not event ownership; both remain required. |
| CTF DRF permissions | `ctf.api._base.CTF_ORGANIZER_PERMISSIONS`, `HasCTFOrganizer`, `HasCTFEndpointScope` | API-token scope admission does not replace organizer group and event ownership checks. |
| Audit persistence | `risk_register.services.audit_role_sync`, `audit_log(..., strict=True)`, `AuditLog.Action.ROLE_SYNC` | Reuse strict role-sync audit for group changes; do not add a parallel audit table. |
| Request attribution | `risk_register.services.get_client_ip`, `get_request_id`, `RequestAudit` | Audit rows use canonical source-IP and request-id extraction; no new XFF parsing. |
| Error envelopes | `shared.api.errors.api_error_response`, `shared.errors`, `ctf.views._access._json_error` | Return fixed/sanitized permission failures; do not serialize provider claims or migration details to clients. |
| Log hygiene | `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint`, module loggers | Logs may identify bounded source/mapping names; never log tokens, cookies, raw headers, or full provider payloads. |
| Import boundaries | `.importlinter`, `ctf.bridges`, `shared.auth`, `management.services` | Keep cross-layer reads through existing bridge/shared modules. |

## Cross-Cutting Layers

- Auth provider verification: OIDC and Identity Platform must verify tokens,
  issuer/audience, email eligibility, and MFA/session gates before privileged
  mapping runs. A raw decoded payload, dev-login POST field, or profile field is
  not authoritative evidence for organizer authority.
- Provider-claim shape validation: provider group claims must normalize through
  one parser, reject non-list/non-string garbage safely, and compare exact
  allowlisted group names. Unknown group names are ignored, not persisted as
  local Django groups.
- Self-service profile validation: `custom:user_type`,
  `UserProfile.user_type`, and `ctf_event_id` remain bounded to known values,
  but only participant/standard effects may come from this path. Negative tests
  must prove changing those fields cannot add or preserve `CTF Organizer`.
- Local group/RBAC surface: `CTF Organizer`, `CTF Participant`, and
  `Threat Research` remain explicit Django groups in `shared.auth`. Organizer
  authority is local group state only after authoritative provider/local admin
  reconciliation.
- CTF domain authorization: organizer group membership admits CTF organizer
  surfaces, but event-scoped operations still require `_check_event_ownership`
  and `ctf.services.authorization.assert_actor_owns_event`.
- API-token surface: `HasCTFEndpointScope` admits token scope only. The token
  owner must still satisfy `HasCTFOrganizer`, and the underlying event ownership
  checks still run.
- Audit persistence: every migration or sync that adds, removes, or confirms
  privileged local group membership needs durable audit evidence. Use
  `AuditLog` and the strict audit writer for mutation-coupled rows so audit
  failure rolls back role changes where role changes are online/request-bound.
- Secret-handling surface: ID tokens, Authorization headers, cookies, OIDC
  codes, Identity Platform API keys, bootstrap email env values, and raw
  provider payloads must not enter logs, audit state, client errors, test
  snapshots, shell argv, or generated docs.
- Env/config binding: provider-group mapping belongs in settings/config with
  fail-closed defaults. Empty or malformed privileged-group configuration must
  grant no organizer authority. Do not widen `ALLOWED_HOSTS`, dev-auth CIDRs,
  API token scopes, or Risk Register group settings for this issue.
- OS/runtime exposure: any audit or migration command must accept only bounded
  flags and must not require bearer tokens or provider payload JSON in process
  argv. Prefer database/provider state already available to the app over
  operator-pasted secrets.
- Error envelopes: denied organizer access remains a fixed 403. Auth-provider
  and mapping failures stay server-side with sanitized logs and audit
  correlation.

## Extensibility Seam

The future variation is another administrator-controlled provider role or a
second privileged CTF role. The seam belongs in one provider-authority mapping
near `config.cognito_groups`/auth-provider configuration:

- input: normalized verified provider group names;
- parameters: exact provider-group to local-Django-group mapping;
- output: allowed local privileged group membership changes plus strict audit;
- forbidden outputs: arbitrary Django groups, `is_staff`, `is_superuser`,
  `Threat Research`, and event ownership.

Adding a new provider group should update that one mapping plus tests, not OIDC,
Identity Platform, dev auth, CTF decorators, DRF permissions, and templates
independently.

## Whole-Repo Scope

In scope for the later implementation:

- `shifter/shifter_platform/config/user_type_sync.py`
- `shifter/shifter_platform/config/cognito_groups.py`
- `shifter/shifter_platform/config/oidc.py`
- `shifter/shifter_platform/config/identity_platform.py`
- `shifter/shifter_platform/config/dev_auth.py`
- `shifter/shifter_platform/config/settings.py`
- `shifter/shifter_platform/management/models.py` and migrations only as
  needed for compatibility/audit/migration state
- `shifter/shifter_platform/shared/auth.py`
- `shifter/shifter_platform/ctf/bridges.py`
- `shifter/shifter_platform/ctf/views/_access.py`
- `shifter/shifter_platform/ctf/api/_base.py`
- `shifter/shifter_platform/ctf/services/authorization.py`
- `shifter/shifter_platform/risk_register/services.py`
- Tests under `shifter/shifter_platform/tests/config`,
  `tests/ctf`, `tests/risk_register`, and provider/auth integration coverage
- Runtime docs only if a new provider-group mapping setting is added

Out of scope unless the implementation discovers a direct dependency:

- Rewriting CTF event ownership, participant registration, scoring, or range
  lifecycle services.
- Replacing Django groups with a new RBAC model.
- Replacing OIDC, Identity Platform, dev-login, session auth, or API-token
  authentication.
- Changing Risk Register authorization, CMS authoring authorization, or
  `Threat Research` semantics.
- Changing Terraform, Helm, Kubernetes, ALB, WAF, or GitHub Actions behavior.

## Gotchas And Anti-Patterns

- Do not move organizer from `custom:user_type` to another self-service claim
  with a different name. The control is administrator ownership, not spelling.
- Do not treat `UserProfile.user_type == "ctf_organizer"` as a compatibility
  shortcut for authorization after this fix.
- Do not let `standard` or absent provider groups preserve a previous
  self-service-derived organizer group without audit and migration
  classification.
- Do not create Django groups directly from claim strings. Only local constants
  selected by the allowlisted mapping are valid outputs.
- Do not make provider group capture itself an authorization decision for every
  request. Capture is evidence; local group reconciliation plus existing CTF
  predicates remain the app authorization surface.
- Do not weaken event ownership checks because organizer group derivation is
  stronger. Organizer group membership is still not ownership of every event.
- Do not conflate CTF organizer with staff, superuser, CMS authoring, Risk
  Register privileged access, or provisioning service identity.
- Do not duplicate claim parsing in OIDC, Identity Platform, dev auth, CTF
  decorators, and DRF permissions. Centralize the mapping.
- Do not expose withheld exploit details in public docs, test names, migration
  comments, logs, PR metadata, or issue comments.

## Non-Goals

- No implementation in this preflight note.
- No new formal Ground Control requirement.
- No new ADR unless the implementation changes repo-wide auth, provider, audit,
  or RBAC policy beyond the boundaries above.
- No redesign of participant self-registration or event membership.
- No new authorization framework, exception hierarchy, schema registry, audit
  database, event bus, or role-management UI.
