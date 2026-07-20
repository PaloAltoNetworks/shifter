# Security Auth/Audit Hardening Preflight (#937)

Status: pre-implementation guidance

Date: 2026-06-20

Issue: GitHub #937, "security: dev-login Host-header bypass and audit/claim
trust hardening"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as hardening existing auth and audit seams, not as a new RBAC,
identity, logging, or proxy-trust framework.

Keep these concepts separate:

1. Development-auth reachability: whether `/dev-login/` and `/dev-logout/` are
   callable at all.
2. Request attribution: which network value is stored as audit `source_ip`.
3. Identity-provider claims: provider-supplied or self-service user profile
   values that may synchronize CTF-scoped role state.
4. Platform elevation: Django `is_staff`, `is_superuser`, Threat Research, CMS
   authoring, and organizer/admin surfaces.

`custom:user_type` may remain self-mutable. The safety control is durable,
reviewable auditability plus the invariant that claim-derived roles are CTF
roles only; they must not become platform elevation.

## Architectural Decisions

- Preserve the hard dev-auth gate: `DEBUG=True` or `ENVIRONMENT=development`
  may admit dev auth; every other environment must 403 before user creation,
  session creation, or group mutation.
- Bind deployed-dev dev-auth allowlisting to the direct peer address
  (`REMOTE_ADDR`) and loopback/admin CIDRs. Do not use `Host`,
  `request.get_host()`, `X-Forwarded-For`, `ALLOWED_HOSTS`, or CSRF/Origin
  semantics as the secondary dev-login security decision.
- Make `risk_register.services.get_client_ip()` the canonical HTTP audit source
  resolver. The resolver should model the deployed load-balancer contract:
  when an ALB/proxy appends to `X-Forwarded-For`, use the trusted rightmost
  appended value rather than the attacker-controlled leftmost value; otherwise
  fall back to `REMOTE_ADDR`.
- WebSocket session audit must not keep a separate XFF parsing policy. It should
  use the same hop-selection semantics as the HTTP audit resolver, adapted to
  ASGI scope headers, so terminal audit rows do not drift from HTTP rows.
- User-type claim synchronization should be centralized in the profile/auth
  service layer used by Cognito OIDC, GCP Identity Platform, and dev login. That
  operation owns CTF group add/remove, profile `user_type` sync, active CTF event
  sync where applicable, and the audit entry. Keep CTF-specific view/service
  authorization out of this helper.
- Claim-derived `standard` maps to no CTF group membership.
- Claim-derived `ctf_participant` maps to Django group `CTF Participant`.
- Claim-derived `ctf_organizer` maps to Django group `CTF Organizer`.
- Staff/superuser assignment remains owned by
  `config.bootstrap_admin.apply_bootstrap_admin_flags()` and the
  `PLATFORM_BOOTSTRAP_STAFF_EMAILS` /
  `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` runtime contract. Do not let
  `custom:user_type`, `user_type`, CTF groups, or dev-login POST data set
  `is_staff`, `is_superuser`, or `Threat Research`.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #937 |
| --- | --- | --- |
| Dev auth gate | `config.dev_auth._is_dev_environment`, `dev_login`, `dev_logout`, `tests/config/test_dev_auth.py` | Keep fail-closed production behavior and add regression coverage for forged `Host`/XFF with non-local `REMOTE_ADDR`. |
| Runtime env parsing | `config.settings` `_env_list`, `ENVIRONMENT`, `DEV_LOGIN_ALLOWED_CIDRS`, `DJANGO_ALLOWED_HOSTS` | New or changed knobs must bind through settings, fail closed on malformed values, and not broaden `ALLOWED_HOSTS`. |
| HTTP audit context | `risk_register.services.AuditEvent`, `audit_log`, `audit_log_from_request`, `audit_auth_event`, `get_client_ip` | Extend these helpers instead of adding per-view audit dicts or another audit model. |
| Audit query surface | `risk_register.models.AuditLog`, `risk_register.api.views.AuditLogViewSet`, `risk_register.admin.AuditLogAdmin` | User-type and group-change rows must be queryable through existing audit filters. |
| Auth providers | `config.oidc.ShifterOIDCBackend`, `config.identity_platform.IdentityPlatformBackend`, `config.views.identity_platform_session` | Keep provider-specific verification in provider modules; share the post-verification user-type sync. |
| Admin bootstrap | `config.bootstrap_admin.apply_bootstrap_admin_flags` | Keep staff/superuser email-env driven, not claim driven. |
| CTF role constants and predicates | `shared.auth` group constants, `get_user_group_names`, `is_ctf_organizer`, `is_ctf_participant`, `is_ctf_participant_only`, `can_edit_cms_authoring` | Reuse these predicates when proving the claim-derived groups do not grant platform/CMS elevation. |
| CTF role bridge | `ctf.bridges.get_user_role` | Keep CTF views reading role state through the bridge rather than duplicating profile/group interpretation. |
| Participant enforcement | `ctf.services.participant.is_active_participant`, event-scoped participant helpers in `ctf.views` | Coordinate with #944 by keeping participant-only surface enforcement server-side and event scoped. |
| CMS authoring gate | `shared.auth.validate_cms_authoring_user`, `threat_research_required` | Do not treat CTF Organizer as CMS authoring permission. |
| Import boundaries | `.importlinter`, `ctf.bridges`, `shared.auth`, `management.services` | Do not make `management` import CTF, do not make CTF import Mission Control or Engine, and do not hide a cross-layer dependency in a new helper. |
| Error envelopes | `shared.errors.classify_user_message`, existing fixed auth error codes | Do not return raw provider/auth exceptions or internal audit failure details to clients. |
| Log hygiene | `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint`, module loggers | Audit values can be stored durably, but logs must stay sanitized and must not print tokens, headers wholesale, or env dumps. |
| Architecture enforcement | `.importlinter`, `scripts/adr_guard/adr_guard.py`, docs under `docs/architecture/` and `docs/adr/` | Do not add undocumented app-boundary exceptions or weaken guardrails. |

## Cross-Cutting Layers

- Auth surface: `/dev-login/` and `/dev-logout/` are unauthenticated by design,
  so their gate must run before user lookup, user creation, login, logout, or
  group mutation. The gate is environment plus direct-peer local/admin network
  admission; host validation is only Django host validation, not a dev-auth
  allowlist.
- Identity-provider surface: Cognito OIDC and GCP Identity Platform still own
  token verification, email/MFA/provider checks, and first-login user creation.
  Post-verification user-type sync must not weaken provider checks or introduce
  a provider-independent bypass.
- Claim/user-profile validation: accepted values stay constrained to the
  existing `UserProfile.USER_TYPE_CHOICES` / CTF user-type set. Unknown claim
  values are ignored or rejected without changing groups, and must not create
  arbitrary Django groups.
- Group/RBAC surface: only `CTF Organizer` and `CTF Participant` are reachable
  from `user_type`. `Threat Research`, `is_staff`, and `is_superuser` are not
  reachable. CMS authoring uses `can_edit_cms_authoring`; CTF organizer views use
  `ctf_organizer_required`; participant views use `is_active_participant`.
- Audit persistence: use `risk_register.models.AuditLog` with
  `EntityType.USER` and existing action vocabulary unless a narrowly justified
  enum extension is added with a migration and docs. Rows must include actor,
  subject user id, old/new `user_type`, old/new CTF groups, source provider/path,
  source IP where request-bound, user agent where request-bound, and request id
  where available.
- Audit failure behavior: `risk_register.services.audit_log()` is best effort
  and returns `None` on persistence failure. Because this issue's safety control
  requires every user-type change to be recorded, the implementation must not
  apply a role/profile mutation and then silently accept `None`. If this path
  needs fail-closed behavior, add the narrow strictness inside the existing
  `risk_register.services` audit surface instead of creating a second audit
  model or bypassing audit helpers in provider code.
- Request attribution: HTTP request-bound audit flows use
  `risk_register.services.get_client_ip()`. Raw client-provided leftmost XFF,
  `Host`, and `X-Real-IP` are not trusted. Direct local/test requests fall back
  to `REMOTE_ADDR`.
- Secret-handling surface: ID tokens, session cookies, invite tokens, CSRF
  tokens, Authorization headers, API keys, OIDC client secrets, Identity Platform
  API keys, bootstrap email env values, and full request headers must not be
  logged, copied into audit state, emitted to error envelopes, placed in argv, or
  written to docs/test fixtures.
- Env-binding shape: dev-auth CIDR configuration belongs in settings and
  provider runtime env surfaces. Defaults should admit local loopback/admin-tunnel
  usage but not public ingress. Malformed CIDRs should fail closed for the check
  and log a sanitized warning.
- OS/runtime exposure: fixes should not move secrets or bearer tokens into
  command arguments, generated ConfigMaps, GitHub summaries, Terraform output,
  Kubernetes manifests, process-global debug state, or shell-visible env dumps.
- Error-envelope surface: dev-auth denials may return fixed 403 messages.
  Identity Platform/OIDC failures should keep existing fixed error codes and
  classified messages. Audit persistence details and provider upstream errors
  stay server-side.
- Observability: use existing module loggers with sanitized values. Durable audit
  rows carry review evidence; logs carry enough correlation to find the row
  without duplicating sensitive data.

## Extensibility Seams

- The client-IP seam belongs in `risk_register.services`: parameterize the
  trusted-hop policy there if another deployment adds a different trusted proxy
  chain. Do not scatter hop-selection constants across auth providers, CTF views,
  DRF auth, and WebSocket consumers.
- The user-type sync seam belongs in one profile/auth service helper callable by
  OIDC, Identity Platform, and dev auth. The obvious future variation is another
  identity provider or another CTF-only role; that should update a single mapping
  from user type to allowed CTF group, not three provider files.
- The group mapping should stay data-driven enough that adding a future
  participant-only CTF group is a mapping/test update, while still explicitly
  forbidding platform groups (`Threat Research`) and Django admin flags.
- If a new audit action is needed for role synchronization, add it once to
  `AuditLog.Action` with migration, serializer/admin visibility, and audit docs.
  Do not encode new action taxonomies only in free-form context strings.

## Whole-Repo Scope

In scope for the implementation:

- `shifter/shifter_platform/config/dev_auth.py`
- `shifter/shifter_platform/config/oidc.py`
- `shifter/shifter_platform/config/identity_platform.py`
- `shifter/shifter_platform/config/views.py` if Identity Platform request/error
  handling needs source context plumbing
- `shifter/shifter_platform/risk_register/services.py`
- `shifter/shifter_platform/risk_register/models.py`, migrations, serializers,
  admin, and audit docs only if the AuditLog enum/schema changes
- `shifter/shifter_platform/mission_control/consumers.py`
- `shifter/shifter_platform/ctf/views.py` only for replacing duplicate client-IP
  parsing; do not change CTF authorization semantics here
- `shifter/shifter_platform/management/services.py` or a shared auth/profile
  helper if that becomes the chosen home for user-type sync
- Tests under `tests/config`, `tests/risk_register`, `tests/mission_control`,
  `tests/ctf`, and `tests/management` matching the touched seams
- Runtime env docs if `DEV_LOGIN_ALLOWED_*` semantics change

Usually out of scope:

- Locking or removing the self-mutable `custom:user_type` attribute.
- Redesigning OIDC, Identity Platform, magic links, Django auth backends, or
  session middleware.
- Redesigning CTF organizer/participant feature access beyond proving and
  preserving the server-side boundaries already in place.
- Introducing a new audit database, activity log, event bus, SIEM exporter, RBAC
  framework, exception hierarchy, or schema registry.
- Changing Terraform, Helm, Kubernetes ingress, ALB listener behavior, WAF,
  Cloudflare, or `ALLOWED_HOSTS` except for docs/tests that prove existing runtime
  contracts.

## Gotchas And Anti-Patterns

- Do not replace the dev-login Host-header bypass with an XFF bypass. Dev-login
  admission is not audit attribution and should use `REMOTE_ADDR`.
- Do not use `request.get_host()` as an authorization or allowlist primitive.
  Django host validation protects URL construction and host routing, not
  unauthenticated login reachability.
- Do not make `DEV_LOGIN_ALLOWED_HOSTS`, `ALLOWED_HOSTS`, CSRF trusted origins, or
  Origin checks equivalent to network locality.
- Do not trust the leftmost `X-Forwarded-For` value for audit attribution behind
  a proxy that appends its own hop.
- Do not keep one-off XFF parsers in OIDC, Identity Platform, CTF submissions,
  DRF API-key auth, and terminal WebSockets once the canonical resolver exists.
- Do not audit only the profile field and omit the resulting group membership
  mutation. The acceptance criterion requires both.
- Do not audit only login success. A `custom:user_type` change on an existing
  user must produce a reviewable old-to-new row even when the login otherwise
  looks routine.
- Do not create arbitrary groups from claims or POST data. The allowed groups are
  fixed CTF groups.
- Do not conflate `CTF Organizer` with CMS authoring, Threat Research,
  `is_staff`, Django admin, or superuser. A CTF organizer can manage CTF event
  surfaces; that is not platform operator elevation.
- Do not weaken participant-only server-side checks while coordinating with #944.
  UI hiding is not enforcement.
- Do not put tokens, cookies, full headers, or upstream provider bodies into
  audit `previous_state` / `new_state`, logs, test snapshots, or error responses.

## Non-Goals

- No implementation in this preflight note.
- No new formal Ground Control requirement.
- No new ADR unless the implementation changes repo-wide auth, audit, proxy, or
  RBAC policy beyond the boundaries above.
- No attempt to fix unrelated audit gaps, historic `ActivityLog` rows, old audit
  archives, or broader role-management UX.
- No rollback of the accepted maintainer decision that `custom:user_type` remains
  self-mutable.
