# Non-CTF OpenVPN Range Access Preflight

Issue: GitHub #1696, "extend OVPN access to non-CTF range user types."

This is requirement-free architecture guidance. The issue is the shipping
contract. This note records the accepted lifecycle, access, and presentation
boundaries for that implementation.

## Decision Boundary

The only non-CTF range product currently represented by the platform contract is
a Mission Control range (`RangeSource.MISSION_CONTROL`). "Non-CTF" is therefore
range provenance, not `UserProfile.user_type`, a Django group, staff status, or
an organizer role. A user may own one Mission Control range and one CTF range at
the same time; each product endpoint must resolve only its own source.

The #1695 OpenVPN capability, binding, profile validator, Engine resolver,
provider secret lifecycle, request-owned gateway, and target-only network policy
remain canonical. #1696 adds a Mission Control product controller and
presentation, not another VPN stack. The v1 lower contract authorizes exactly one
server-selected member target. It does not authorize the whole range, every
member, or a caller-selected host.

For the initial non-CTF surface, a supported range is a newly provisioned,
Mission-Control-owned legacy/Cyberscript range whose server-authored
`RangeSpec.participant_access` resolves to exactly one Kali/attacker member and
whose admitted live-fire backend can satisfy the existing OpenVPN conformance
contract. ACES-native provisioning does not currently carry this capability and
must remain capability-false rather than being papered over in the API or SPA.

## Unified Range Lease Contract

Every newly created Mission Control or CTF range has one server-owned lease on
`RangeInstance`: `expires_at` is the automatic cleanup deadline and
`maximum_expires_at` is the immutable generation ceiling used for VPN
certificate `notAfter`. Both fields are present together and the current
deadline may never exceed the ceiling.

Mission Control receives a long initial lease of 30 days. An authenticated
owner may extend it by a server-selected increment of up to 30 days, capped at
365 days from creation. The bodyless extension endpoint accepts neither a
timestamp nor an increment, locks the range row, rejects expired or terminal
ranges, and audits the previous and resulting deadlines. Extending the cleanup
deadline does not rotate the generation-bound VPN credential; its certificate
already uses the immutable maximum deadline.

CTF derives both lease fields from the event's authoritative cleanup time
(`event_end` plus the configured cleanup delay). This applies to participant
ranges and spare ranges irrespective of the event's optional post-completion
bulk-cleanup preference: the event end transition and the scheduler no longer
own a second automatic destruction mechanism.

When an organizer changes that cleanup time, the event service reconciles the
current lease of every linked participant and spare range in the same database
transaction. Earlier deadlines take effect immediately. A later deadline may
advance only as far as the generation's immutable `maximum_expires_at`; an edit
beyond that credential ceiling is rejected and requires a new range generation.

The DB-authoritative range reconciler expires due leases in bounded batches,
claims each row under a lock, rechecks the deadline and terminal state, and
calls the canonical CMS destroy boundary with system audit attribution. The
existing range-status projection then clears CTF participant and spare links.
Manual cancel, destroy, and organizer cleanup actions continue to use the same
canonical lifecycle boundaries.

## Architecture Decisions And Guardrails

- The range lease is the sole automatic cleanup authority for both Mission
  Control and CTF. Product controllers calculate the trusted deadline at
  launch, CMS persists it, the reconciler enforces it, and provider credentials
  may not outlive `maximum_expires_at`.
- The Mission Control current-range response includes only the safe lease
  projection: current deadline, maximum deadline, fixed extension size, and
  whether extension is currently allowed. The SPA shows a live countdown and
  absolute timestamps and offers the bodyless extension action. Do not add this
  feature to the legacy server-rendered UI.
- The Mission Control endpoint is a bodyless `POST`, for example
  `/api/v1/mission-control/range/vpn-profile/`. It derives the active
  `RangeSource.MISSION_CONTROL` range from the authenticated actor. It accepts no
  request id, CMS primary key, Engine range id, target id, endpoint, route,
  provider, deadline, filename, or generation.
- Add an exact token capability such as
  `mission_control:vpn-profile:read`. Existing
  `mission_control:range:read`, `mission_control:range:write`, and Guacamole
  scopes must not gain private-key delivery transitively. Session callers keep
  DRF session authentication and CSRF enforcement.
- The current-range response exposes only a top-level safe
  `vpn_profile_available` boolean, false when there is no active/ready/current
  binding. Do not add endpoint, target, secret reference, provider, certificate,
  or adapter state to `RangeContext` or the response. Historical ranges never
  advertise live credential delivery.
- Generalize the existing CMS VPN ownership loader and its three error
  categories (not found, conflict, unavailable) by `RangeSource`; do not add a
  parallel Mission Control loader, repository, or exception hierarchy. The CTF
  bridge continues to map those generic CMS categories to CTF domain errors;
  Mission Control maps them directly to fixed API errors.
- CMS validates the active non-deleted row, exact owner, exact Mission Control
  provenance, `READY` status, and request linkage. Engine independently
  validates request ownership, `READY`, binding owner, request generation, and
  the current ready Kali/attacker member before resolving the secret. A same-user
  CTF range must never be selected by the Mission Control endpoint.
- Provisioning remains eager and generation-bound. A download resolves the
  existing profile; it does not create infrastructure or mint a certificate.
  Existing ranges without a binding remain unavailable and require a new range
  generation unless a separately designed rotation/retrofit workflow is
  accepted.
- Keep the v1 target contract singular. Reuse the unique server-authored
  participant-access target and `/32` enforcement. If "range hosts" is intended
  to mean multiple independently authorized members, that is a versioned
  capability/binding and network-policy change, not a list squeezed into
  `target_ref` or a whole-subnet route.
- Capability enablement belongs to trusted product/backend admission before
  mutation. Unsupported GDC/local/ACES-native paths stay unavailable; CTF, CMS,
  Engine domain code, and the SPA do not branch on `CLOUD_PROVIDER`. A persisted
  ready binding remains the UI authority.
- Reuse the shared cross-worker credential-delivery counter before secret
  resolution. Relocate or parameterize the incumbent CTF helper if necessary;
  do not create a view-local/in-process Mission Control counter. Backend failure
  is a bounded fail-closed `503`; exhaustion is `429` with `Retry-After`.
- Reuse `AuditAction.DOWNLOAD`, `AuditEntityType.CREDENTIAL`, and the shared
  audit port. Generalize the existing VPN delivery helper rather than adding a
  Mission Control audit vocabulary/table. Record actor, product provenance,
  range/generation, channel, profile version, and outcome only.
- Success reuses `application/x-openvpn-profile`, a fixed server-authored
  `.ovpn` filename, `Content-Disposition: attachment`, `Cache-Control: private,
  no-store`, bounded `Content-Length`, no `ETag`, and `Vary: Cookie,
  Authorization`. Failures use the shared JSON error envelope: non-enumerating
  `404`, lifecycle/generation `409`, throttle `429`, and bounded provider/profile
  `503`.
- Extending the population does not authorize a wider network. The audited
  public mutual-TLS UDP/1194 edge remains per range; the readiness responder
  remains private; forwarding and cloud egress remain limited to the
  authoritative target `/32` plus the existing private provider-secret path.
  Capacity evidence must cover the larger gateway/NLB/public-address,
  secret-version, IAM/service-account, and provisioning-time footprint.
- Pause, resume, destroy, retry, partial failure, and ownership reassignment use
  the existing range lifecycle. Profile availability is false outside `READY`;
  destroy removes the gateway and every generation secret; an ownership transfer
  remains blocked while a downloaded binding exists.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Mission Control range identity | `RangeSource.MISSION_CONTROL`, `cms.services.get_active_range`, the active-per-user/source constraint | Resolve the actor's one active Mission Control range; never infer product provenance from a role or user-type claim. |
| Mission Control HTTP/auth | `mission_control.api._base`, `mission_control.api.permissions`, `shared.api.permissions`, `shared.api_tokens.scopes` | Preserve session/token actor resolution, active-user checks, CSRF, and exact scopes; add one narrow delivery scope. |
| SPA state and binary transport | `frontend/src/api/mission-control.ts`, `ActiveRangePanel`, `frontend/src/api/client.ts::apiDownload` | Use a mutation and the shared bounded Blob/error client; keep profile bytes out of query caches and components. |
| API contract | runtime DRF views/serializers, ADR-040, `openapi/v1.json`, generated `frontend/src/api/schema.d.ts` | Author binary success plus JSON errors at runtime and regenerate; do not hand-edit generated contracts or add a second DTO. |
| Product-to-domain boundary | public `cms.services` facade and `.importlinter` | Mission Control calls CMS; CMS calls Engine. No controller imports Engine, provisioner, CTF, or provider code. |
| VPN contract and validation | `shared.remote_access` | Reuse the exact capability, binding, profile media type, directive allow-list, size limit, and versions. Version the seam for genuinely new semantics. |
| Ownership and secret access | `cms.services._range_vpn`, `engine.services._vpn`, `engine.secrets` | Generalize the CMS product/source gate and reuse Engine's independent owner/status/generation/member checks and bounded in-memory resolver/cache. |
| Persistence and lifecycle | CMS `RangeInstance` lease fields and canonical destroy service; Engine `Range.remote_access_capability`, `Range.vpn_access_binding`, request/member state; ADR-025 outbox/reconciler; reassignment guard | Use the one persisted lease and reconciler for CTF and Mission Control automatic cleanup. Add no profile field/table, CTF-specific cleanup scheduler, Mission Control cache, or second lifecycle workflow. |
| Provider realization | `vpn_access.py`, `vpn_secrets.py`, AWS `modules/range/vpn.tf`, GCE range-cell VPN plan/resources/firewall, backend binding | Keep issuer/profile generation, request-owned gateway, target-only routing, provider selection, readiness, and cleanup unchanged by product. |
| Rate limiting | `shared.rate_limit.consume_fixed_window`, `launch_rate_limit`, current credential-delivery helper | One cross-worker budget before secret access, with fail-closed backend handling. |
| Audit/errors/logging | `shared.audit`, `shared.api.errors`, `shared.errors`, `shared.log_sanitize`, provisioner `log_redact` | Translate once per boundary using fixed messages and safe correlations; never serialize provider/parser exceptions. |
| Configuration/admission | installation closed settings/registry/runtime inventory, backend admission, Django env/startup validation, task env allowlists | Any new deadline/capability setting is non-secret, closed, range-checked, rendered everywhere, and admitted before mutation. |

## Cross-Cutting Security And Validation Layers

1. **Browser/SPA.** `apiDownload` supplies same-origin credentials, CSRF, and
   request correlation, checks media type and size, and parses JSON failures.
   The mutation creates only a short-lived Blob URL and revokes it. Profile
   bytes do not enter TanStack query state, local/session storage, IndexedDB,
   analytics, service-worker caches, or rendered errors. The control labels the
   file as a private credential without claiming the browser can enforce local
   filesystem permissions after download.
2. **DRF authentication and scope shape.** `ApiTokenAuthentication` runs before
   `SessionAuthentication`; `IsAuthenticatedSessionOrApiToken` and
   `HasMissionControlActor` require an active actor. The new exact registry scope
   is required for tokens; `validate_scopes` continues to reject unknown, blank,
   and wildcard scopes. Session POSTs pass the existing CSRF gate.
3. **HTTP input/output shape.** The endpoint rejects body and query input. DRF
   and OpenAPI describe binary success, fixed headers, and the shared JSON error
   envelope. The filename is fixed and the response is private/no-store.
4. **CMS product ownership.** The loader checks `user_id`,
   `RangeSource.MISSION_CONTROL`, active/non-deleted state, `READY`, and the CMS
   request FK. Missing, foreign, CTF, historical, paused, and destroying ranges
   fail before Engine or the secret store.
5. **Engine authorization.** The existing resolver checks the authenticated
   owner against Engine `Range` and request, binding `owner_user_id`, binding
   generation against request UUID, current `READY`, and a live ready
   Kali/attacker member with the bound UUID. The secret cache is downstream of
   every check and is never an authorization source.
6. **Closed contract/profile parsers.** `parse_openvpn_capability`,
   `parse_openvpn_binding`, the 397-day window validator, and
   `validate_openvpn_profile` reject unknown fields/versions, invalid target or
   reference shapes, oversized/non-normalized content, a mismatched remote, and
   any directive outside the fixed allow-list.
7. **Secret handling.** The provisioner-only issuer writes server identity and
   client profile directly to the selected provider secret store. Only a bounded
   reference is persisted. Portal resolution is in memory; no attachment,
   object URL, Django JSON value, event, audit field, Terraform value/state,
   ConfigMap, or durable browser cache contains the profile/private key/CA key.
8. **Process and OS exposure.** Existing structured argv carries operation and
   request ids only. Credential material and secret references do not enter
   process argv, environment, task payloads, shell commands, or diagnostics.
   Gateway bootstrap writes only its server identity under root-owned `0600`
   files and uses argv-array subprocess calls. No new temporary-file path is
   needed for the product extension.
9. **Provider/network policy.** Backend admission and the provisioner revalidate
   the capability before mutation. AWS/GCE validate prerequisites, unique member
   target, request ownership, gateway identity, private readiness, public
   mutual-TLS listener, default-deny forwarding, target `/32`, provider API
   egress, metadata hardening, and generation cleanup. Client routes never grant
   authority.
10. **Lifecycle, errors, and observability.** The persisted lease is the
    authority for automatic cleanup. Extension and expiry are serialized and
    audited, and the reconciler reuses canonical destroy and CTF status
    projection. Non-`READY` state makes the capability bit false and delivery a
    conflict. Errors cross each boundary as fixed categories; raw
    provider/certificate/profile text is not logged or returned. Audit/log/
    metrics may use action, product, outcome, stable failure class,
    request/generation, and safe fingerprints only—not profile bytes, secret
    refs, endpoint/IP/route, certificate identity, or provider payload.
11. **Config and repository enforcement.** The product lease constants remain
    server-owned and range-checked alongside the 397-day credential window; no
    browser or HTTP input can override them. The implementation also remains
    subject to `.importlinter`, ADR guard, OpenAPI drift/breaking checks, gitleaks,
    the audited SG-CIDR rule, GCP IAM-scope checks, TFLint/Checkov, and provider
    conformance.

## Extensibility Seam

The seam remains the product-neutral `OpenVpnCapability` / `OpenVpnBinding` and
CMS/Engine profile resolver. The product-side parameters are **range provenance,
authoritative member target, and an enforced access deadline**. Provider and
profile version remain closed lower-layer parameters. Product provenance must
not be added to the credential or provider adapter.

A future product source supplies its own ownership policy and enforced deadline,
then calls the same CMS/Engine seam. Multiple VPN targets, multiple devices,
explicit rotation, or another protocol require a new closed capability/profile
version; they do not add provider branches, user-type switches, or optional
fields to v1.

## Whole-Repository Surfaces In Scope

- Mission Control SPA/API: current-range response, active-range panel, Mission
  Control hooks, shared download client, URL/view/serializer/permissions,
  OpenAPI artifact and generated types;
- identity and policy: API token registry/permissions, session CSRF, Mission
  Control actor resolution, `RangeSource`, active-range uniqueness and history;
- CMS/Engine: public service facade, source/owner loader, generic VPN error
  translation, current request/range/member checks, secret resolver/cache,
  persisted capability/binding, lifecycle/reassignment/outbox/reconciler;
- provisioning/providers: `shared.remote_access`, range operation/state,
  `vpn_access.py`, `vpn_secrets.py`, AWS Terraform gateway/NLB/IAM/SG, GCE
  gateway/address/firewall/service account, packer image, readiness and cleanup;
- configuration/runtime: installation schema/registry/runtime inventory,
  Django env/startup validation, ECS task variables/IAM, Terraform roots,
  Kubernetes/Helm runtime and admission constraints; and
- enforcement/evidence: ADR-039/040, `.importlinter`, ADR guard, SG CIDR and GCP
  IAM checks, schema drift, frontend lint/test/build, provider-neutral unit tests,
  and disposable real-client handshake/isolation/lifecycle/capacity evidence.

## Gotchas And Anti-Patterns

- Do not equate "non-CTF" with `user_type == "standard"`; that mutable claim is
  not range provenance or authorization. Do not grant organizer, staff, or
  Threat Research users access to a range they do not own.
- Do not let the Mission Control endpoint select the same user's CTF range, or
  confuse CMS `RangeInstance.pk`, nullable legacy `range_id`, Engine range id,
  request UUID, and authored member UUID.
- Do not duplicate the CTF HTTP controller, CMS exceptions, rate counter, audit
  vocabulary, DTO, profile renderer, validator, secret adapter, binding field,
  repository, or provider switch under Mission Control names.
- Do not infer VPN enablement from the presence of Kali, a role/OS string,
  `participant_access`, `CLOUD_PROVIDER`, or a frontend flag alone. The trusted
  product launch policy and backend admission must explicitly authorize it.
- Do not route an entire range/subnet or every host to satisfy the plural wording
  in the issue. V1 is one authoritative target. A broader acceptance meaning is
  a contract change that must be decided explicitly.
- Do not retrofit a missing profile on download, issue a new certificate on
  every click, or make profile delivery mutate range/provider lifecycle state.
- Do not let HTTP or SPA callers select a deadline or extension duration,
  change lease constants client-side, extend an expired range, exceed the
  immutable ceiling, or weaken the 397-day validator.
- Do not expose the profile through a presigned URL, attachment model, temp file,
  Django/event/audit JSON, local storage, ConfigMap, environment, argv, Terraform
  state, log, metric label, trace attribute, or raw error.
- Do not show the control from `status == ready` alone, or leave it visible on an
  unsupported backend and normalize permanent `503` responses as expected
  behavior.
- Do not treat Terraform apply, secret creation, VM start, or an open UDP port as
  readiness. Preserve service/policy probing and real-client positive and
  negative isolation evidence.
- Do not overlook rollout scale: one gateway and public edge per standard range
  can move NLB/address/IAM/service-account/secret quotas and cost far beyond the
  CTF-only population.

## Non-Goals And Implementation Boundaries

- No change to the CTF participant endpoint, active-event policy, or CTF UI.
  Automatic event cleanup is deliberately unified behind the persisted lease
  and CMS reconciler; explicit organizer cleanup remains available.
- No ACES-native OpenVPN realization, GDC/local emulation, provider-specific SPA
  behavior, or claim that an unsupported adapter has parity.
- No access to all range members, whole-range/default routing, shared VPN hub or
  CA, split DNS, participant internet egress, or non-OpenVPN protocol.
- No lazy retrofit for already provisioned ranges, client inventory, multiple
  devices, user-facing rotate/revoke, or silent certificate renewal.
- No redesign of range lifecycle/status, scenario/ACES authoring, API token
  authentication, Guacamole/terminal access, provider selection, or the #478
  provisioner persistence boundary.
