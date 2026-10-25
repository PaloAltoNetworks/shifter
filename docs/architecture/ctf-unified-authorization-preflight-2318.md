# CTF unified authorization preflight (#2318)

Status: architecture guidance for S5; application authority activates at the
coordinated ADR-066 S8 cutover.

Contract: issue #2318, under #2308 and ADR-066. This is a requirement-free
preflight, not an implementation plan. The existing CTF-006/010/012/608
contracts need reconciliation when implementation begins. Custom source work
remains subject to #2308's authorization gate.

## Decision boundary

- CTF uses the one `shared.authorization.ACTION_CATALOG`, `AuthorizationRequest`,
  `CredentialCeiling`, and provider port. `management.services` resolves active
  human/service principals; `workspaces.services` resolves customer ancestry and
  owns policy mutations; CTF owns event state, participation, scoring, ranges,
  and communications. `config` composes the credential and OpenFGA adapters.
  No CTF policy evaluator, identity provider, or role-to-action fallback exists
  after S8. Before S8, source preparation cannot make a second live authority.
- Every protected operation has one registered action, target, and server-resolved
  scope. The baseline 114 API operations, browser/legacy views, Django admin,
  imports/exports, commands, scheduled work, communication workers, callbacks,
  webhooks, and participant channels need explicit coverage or an explicit
  public/authenticated-only exemption. Route names and HTTP verbs do not infer
  authorization. A service method rechecks the same action for callers that
  bypass a view. The catalog's administrative set remains exactly the coverage
  of the predefined ApplicationAdministrator policy.
- The current catalog has `event.read`, `event.participate`, `event.manage`,
  participant/challenge/communication management, and authorization delegation.
  The incumbent `EventCapability` distinguishes configuration, teams, ranges,
  scoring, awards, submissions, content, lifecycle, and deletion as well. Where
  those distinctions remain grantable, register the missing actions in the
  *shared* catalog; do not collapse them into `event.manage` or copy the old
  capability enum into another policy vocabulary. Each operation has one exact
  action even when a broader policy grants that action by inheritance.
- Event creation authorizes against the selected **existing parent scope**;
  a nonexistent event cannot be its own authorization target. The catalog must
  register creation for each supported account/organization/workspace placement
  and distinguish it from event management. Full human and service application
  administrators can perform every valid administration action, including
  creation, staff changes, and ownership transfer. The event's creator, owner,
  staff, Django superuser flag, or token scope cannot silently veto that grant
  or supply one independently. Delegation and ownership mutations require an
  explicitly registered administrative action and the shared delegation ceiling.
  A browser form may require a human session, but it cannot be the sole entry
  to a valid administration operation: a service credential needs a matching
  API/service path with the same authorization and domain rules.
- A personal event has direct individual-account scope. A business event retains
  validated Account -> Organization -> optional Workspace ancestry. No personal
  organization/workspace is fabricated. `CTFEvent.created_by` is currently a
  non-null human FK; it cannot represent a service creator or be the S8 owner
  authority. Keep creator/audit attribution and durable owner-principal identity
  distinct. `CTFEventStaff.user` and its role map likewise cannot be a hidden
  human-only policy gate. SQL owns event ownership and state facts; OpenFGA owns
  permission relationships. Changes crossing them use the existing durable
  authorization mutation/reconciliation boundary, with no permission mirror.
- `CTFParticipant.principal_uuid` is the participation identity for humans and
  services. `CTFTeam`, brackets, cohorts, captainship, and participant status
  remain competition facts, never `AuthorizationGroup` memberships. An admin
  does not become a participant. A service participates only through an explicit
  event association and the same eligible/viewing, release, submission, hint,
  team, scoring, and range predicates as a human, with its credential ceiling
  and live `event.participate` grant. Temporary CTF humans keep their exact
  single-event credential target, password-change and origin gates, and HTTP /
  WebSocket confinement; they gain no account or installation authority.

## Existing seams and concrete traps

| Concern | Canonical incumbent and constraint |
| --- | --- |
| Identity, scope, policy | `shared.identity_scope`, `shared.credentials`, `shared.authorization`; `management.services` and `shared.principal_port`; `workspaces.services.resolve_resource_scope` and authorization facade; `config.openfga_authorization`. Resolve live identity and SQL ancestry before a high-consistency policy check. Deny evaluator errors; never rescue them with CTF roles. |
| Event placement/discovery | `ctf.services.event._workspace`, `_queries`, `ctf.services.credential_scope`, `ctf.services.authorization_inventory`, `shared.authorization.inventory`, and `config.openfga_authorization._scope_parents`. Today creation falls back to a personal workspace, descendant inventory accepts only workspace IDs, and the provider requires a workspace parent for events. All three must admit validated account-level events and the supported business ancestry, including delegation proofs and bounded, policy-filtered discovery. The current blank `scope_kind` is mapping-only legacy state, not an S8 authority shape. OpenFGA `list_objects` is advisory, not authoritative inventory. |
| Existing CTF gates | `ctf.services.authorization`, `ctf.services.event.staff`, `ctf.api._base`, `ctf.api.organizer._base`, `ctf.views._access`, `ctf.bridges`, and `ctf.services.event._queries` currently compose owner/staff/organizer/superuser/token checks. Their owner-only `capability=None` paths, global organizer prefilter, `actor_id` service signatures, and `EventListView.post` are concrete service-admin blockers. Keep domain lifecycle checks, but replace permission decisions at the S8 boundary rather than OR-ing two evaluators. |
| Participation and range | `ctf.services.principal_participation`, `ctf.services.participant`, `team`, `submission`, `hint`, `scoring`, `range`, `ctf.api.projections`, and CMS/Engine service bridges. `admit_service_participant` currently creates a row while `participant_for_credential` also requires `event.participate`; a row and a policy grant are separate necessary facts, so admission and revocation must reconcile both without an unusable or overprivileged result. Existing `participant.user` and `event.created_by` assumptions in participant range/content paths must not fabricate a User for a service or substitute an event admin for participant/cloud authority. Scope and event association are checked before any range or data access. |
| Async/communication | `CTFScheduledTask`, `ctf.services.event.scheduling`, `range.tasks`, `communication.admission/release/scheduling/delivery`, `ctf.signals`, `cms.handlers.ctf_bridge`, and `ctf.services.webhook`. Existing claim tokens, row locks, retry/idempotency rules, immutable campaign targets, and strict audit remain. A human/service-initiated queued effect stores bounded principal/credential attribution, then re-resolves active principal, current credential ceiling, policy, scope, and domain state at execution/replay. Revocation denies or cancels before effect; missing actor is never system authority. Intrinsic scheduler/callback work uses only its established trusted source proof and remains event-scoped. No raw bearer, password, flag, webhook secret, or policy tuple enters task metadata or process arguments. |
| HTTP and frontend | `config._drf_settings`, bearer-first authentication, Django session/CSRF, `shared.api.principals.authenticated_credential`, `ClosedSerializer`, `shared.api.strict_json`, CTF serializers/forms, `shared.api.errors`, `ctf.exceptions`, OpenAPI, `frontend/src/api/client.ts` and generated `schema.d.ts`. Validate shape at the edge and business invariants in CTF services. Legacy HTML, DRF wrappers and direct DRF views must converge on the same action decision; cached UI capabilities are hints only. Preserve the request-ID error envelope and bounded, opaque denials. |
| Audit, persistence, runtime | `shared.audit` attribution/vocabulary/integrity, `ctf.services.audit`, `shared.log_sanitize`, Django transactions/constraints/`select_for_update`, and the PostgreSQL lane. Strict-audit authority and participation mutations in their owning transaction; preserve provider operation outcomes and worker fences. Use stable IDs and bounded reason codes, not email, token, roster, flag, secret, relationship, provider body, or exception text. |

## Cross-cutting security and runtime gates

1. **Admission:** exact verified provider binding, active principal and Django
   session or supported service credential; fail-closed bearer parsing; CSRF on
   unsafe sessions; server-derived exact `CredentialCeiling`. `config.middleware`
   and `config.websocket_auth` still confine temporary CTF accounts. The HTTP
   middleware admits the broad `/api/v1/ctf/` prefix, so every organizer
   service must also reject temporary authority. No token
   scopes, provider claims, Django groups, or superuser flags become policy.
2. **Shape and ancestry:** DRF's closed JSON/serializers, legacy forms/parsers,
   `PrincipalRef`, `TargetRef`, `ResourceScope`, action/target validation, and
   `workspaces.services` ancestry/lifecycle checks all apply. Child event,
   challenge, file, participant, team, campaign, and range IDs must resolve to
   the requested event before policy; missing/cross-account objects deny
   opaquely. Never interpret null workspace as installation scope. Existing
   event/communication scope columns, immutable binding, uniqueness, and
   locked state transitions remain the persistence invariants.
3. **Domain and external input:** CTF event lifecycle and content mutability,
   participant eligibility, scoring/attempt limits, team capacity, and range
   rules still decide whether an authorized action is valid. Existing flag
   hashing/regex limits, signed receipt validators, file handling, HTTP
   validator SSRF checks and communication audience/link validation remain in
   force. Webhook signing remains, but `CTFWebhook.url` currently has only a
   URL shape check and `ctf.services.webhook` calls `requests.post` directly;
   that is not an outbound SSRF/DNS-rebinding gate. Expanded service-admin
   exposure must use the incumbent `ctf.validators._ssrf` pinned-destination
   policy and deployment network egress controls, including redirects. An
   authorization grant supplies none of these validations or model-access /
   cloud IAM authority.
4. **Secrets and host:** this slice needs no new secret or environment setting.
   If a new binding is genuinely required, use `config/env-manifest.json`,
   `_env_manifest.py`, bounded settings validators, `shifter/installation`
   schema/loader/render/runtime inventories, and matching AWS Helm/GCP
   Kustomize/Terraform workload bindings. OpenFGA and credential secrets stay
   in the established secret/file bindings, never argv, shell text, diagnostics,
   ConfigMaps, Terraform outputs, frontend bundles, logs, or audit. Scheduler,
   communication worker, and portal processes must see the same validated
   authority configuration; no job-local policy fallback.
5. **Errors and evidence:** `shared.api.errors` emits stable code/status/request
   ID without provider detail; `ctf.exceptions` supplies domain classification.
   Sanitized logs and low-cardinality metrics distinguish denial, evaluator
   failure, cancellation, and effect outcome. Coverage must fail closed when an
   API operation or non-API effect lacks a mapping. Negative evidence includes
   sibling account/event, revoked queued actor, service admin, service
   participant, temporary-login escape, and PostgreSQL/OpenFGA concurrency.
   The repo gates are ADR guard, import-layer and cross-layer FK checks, OpenAPI
   drift/generated client, CTF service/API tests, and the released OpenFGA plus
   PostgreSQL conformance lane. Mock external providers, not first-party services.

## Extensibility, non-goals, and anti-patterns

The extension seam is the registered action plus its exact target and
`ResourceScope`. Parent-scope creation and CTF event ancestry must accept the
validated account/organization/workspace shape; adding the next event-scoped
operation or account placement should extend the catalog and owning scope
projection, not authentication adapters, each view's role table, or the OpenFGA
SDK binding. `PrincipalRef`/`CredentialContext` remain the human/service seam;
the existing CTF participant row remains the competition seam.

Do not introduce a CTF policy engine, permission cache, identity group as team,
second principal/scope/credential DTO, second validation or exception hierarchy,
new workflow runner, or parallel audit store. Do not equate owner, creator,
staff, administrator, participant, account member, or cloud operator. Do not use
the original request's authorization result for delayed work, trust client
scope/role fields, fetch policy directly from the browser, silently skip a
failed batch decision, or repair stale ancestry during an access check.

This preflight changes no source, schema, data, deployment, route, credential,
policy grant, or S8 activation. It does not redesign CTF lifecycle, scoring,
communications, participant login, range provisioning, cloud IAM, or private
pack authorization. Public registration and truly public reads keep their
explicit publication and abuse controls; they are not made authenticated by
default. Cloud and model-access grants remain separate from application policy.
