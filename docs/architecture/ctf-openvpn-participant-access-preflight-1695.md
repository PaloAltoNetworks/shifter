# CTF OpenVPN Participant Access Preflight

Issue: GitHub #1695, "OVPN download button for CTF users to connect to
their Kali box."

This is requirement-free pre-implementation guidance. The issue title, body,
and acceptance criteria are the shipping contract. This note does not implement
the change and is not an implementation plan.

ADR-039 already owns provider-neutral remote-access bindings and their range
lifecycle. ADR-040 owns the runtime-first HTTP/OpenAPI contract, and ADR-029
owns the SPA API-client boundary. This note specializes those decisions for a
participant-held OpenVPN credential.

## Decision Boundary

The downloaded profile is a security credential for a platform-owned CTF
remote-access capability. It is not a challenge attachment, a scenario-authored
service, another browser workspace transport, or a public description of range
topology.

The logical OpenVPN termination is per range and inside that request-owned
range's containment boundary. An adapter may realize it as a dedicated gateway
or on another request-owned edge resource, but it must not use a cross-range
shared gateway and must not run the gateway on the participant-controlled Kali
host. Provider differences stay behind ADR-039's substrate adapter.

The trusted CTF launch path requires the participant-client-OpenVPN capability
through ADR-039's existing remote-access capability/profile seam, adjacent to
rather than inside `RangeSpec`, ACES `ProvisioningPlan`, or scenario YAML. A
scenario's `participant_access` remains the authority for selecting the Kali or
attacker member target; it does not authorize a VPN service or contain client
certificate policy. The platform resolves that authored member to a concrete
request-owned member and rejects absence or ambiguity. No HTTP caller supplies
a target, endpoint, route, provider, range id, or credential generation.
CMS mints the closed capability only for `RangeSource.CTF`, binds it to the
single participant-access Kali member (or the unique hydrated Kali member for
legacy templates with no participant-access declarations) and the event cleanup deadline, and
Engine persists it atomically beside the range. Mission Control and unsupported
adapters carry no capability; member roles or operating-system topology alone
never activate a VPN edge.

## Architecture Decisions And Guardrails

- Provisioning creates one participant client identity and one profile secret
  for a range generation. A successful ADR-039 `provision` result carries only
  a closed, non-secret OpenVPN access binding: authoritative target reference,
  endpoint and port, profile-format/version, generation, readiness, and the
  provider secret reference. Profile bytes and key material never enter the
  result.
- `READY` means the required OpenVPN gateway, server policy, credential, and
  route to the authorized Kali target are ready. Infrastructure existence or VM
  state alone is pending: the provisioner must complete a bounded gateway
  service-and-target-policy probe before it publishes the binding. The download
  click retrieves the existing generation's profile; it does not mint an
  unbounded new client certificate on every request. Explicit credential
  rotation is a separate lifecycle action, not a side effect of download.
- The profile and client identity are bound to the participant owner, CMS
  `RangeInstance` primary key, Engine request/generation, and one authorized
  target. Because a downloaded credential cannot be recalled, spare adoption or
  participant reassignment is refused while the old generation has a VPN
  binding. Spare selection checks this before old-range teardown and the
  ownership write rechecks it. Recovery for a new owner destroys that
  generation and provisions a new range/client identity before the replacement
  becomes `READY`.
- The client, server, and issuer certificates use the known event/range teardown
  deadline as `notAfter`. A new capability is rejected before provider mutation
  when the deadline is stale or more than 397 days away, so a maximum-lifetime
  cap cannot silently expire credentials while the range is still intended to
  be active. Expiry is defense in depth: destroy deletes the client/server/issuer
  material and gateway. Ownership
  cannot change until that deletion completes; the new owner receives a new
  generation. `pause` disables remote access; `resume` restores the same
  generation unless an explicit rotation occurred.
- A per-range VPN client subnet and server-side firewall/forwarding policy
  allow only the participant's resolved Kali address, normally as a `/32`.
  Disable client-to-client traffic and block other scenario members, other
  ranges, platform/control-plane networks, cloud metadata/provider APIs, and
  management paths. Do not push a default route or grant a whole RFC1918/range
  CIDR merely because the profile asks for it. The server policy, not client
  routes, is the enforcement boundary.
- The gateway is the only new public range ingress. It uses mutual TLS and a
  hardened OpenVPN control channel. Only its UDP client listener is public; the
  service-and-policy readiness responder is private to the portal network. Kali
  remains private. Per-range termination also prevents overlapping
  participant/range CIDRs from becoming a shared routing or authorization
  problem.
- The CA signer stays in the provider-owned credential issuer or provider
  secret store and is usable only by the substrate provisioning identity. The
  portal and gateway never receive the CA private key; the gateway receives
  only its server identity and trust material. The issuer is immutable and
  retained until generation teardown so a completed-generation retry reuses the
  exact server and participant identities instead of creating material the live
  gateway does not trust. Client profiles, client private keys, and CA signing
  material are prohibited from Terraform variables, outputs and state, Django
  rows/JSON, events, task payloads, ConfigMaps, argv, diagnostics, logs, and
  metrics.
- GCE creates a no-role service account for each range generation, attaches it
  only to that generation's gateway, and grants it `secretAccessor` only on the
  corresponding server-identity secret. The shared range-host service account
  is not a VPN secret reader. Teardown deletes the generation service account
  after deleting its secrets.
- The canonical endpoint is a bodyless unsafe operation such as
  `POST /api/v1/ctf/range/vpn-profile/`. POST preserves the existing CSRF gate
  and avoids browser/link prefetch and cache semantics for credential delivery.
  It returns the profile bytes directly rather than a presigned object-store
  URL. Success uses an explicitly documented profile media type, a fixed
  server-authored `.ovpn` filename, `Content-Disposition: attachment`,
  `Cache-Control: private, no-store`, and no `ETag`; failures remain JSON in the
  shared error envelope. Preserve appropriate `Vary` handling for session and
  token authentication so no intermediary can reuse an authenticated response.
- Use `CTF_PARTICIPANT_PERMISSIONS` and a new exact API-token read capability,
  for example `CTF_VPN_PROFILE_READ = "ctf:vpn-profile:read"`, on both the POST
  write-scope attribute and the scope registry. Reusing broad `ctf:play:read`
  would grant existing programmatic tokens delivery of a new private key.
  Session callers remain covered by DRF session authentication and CSRF.
- Resolve the active event participant with `_resolve_active_participant`, then
  use the participant's server-side `range_instance_id` and linked user. The
  CTF service calls a new bridge into the public `cms.services` facade; CMS
  validates primary-key ownership, `RangeSource.CTF`, request linkage, current
  generation, and `READY` state before Engine resolves the provider secret.
  CTF must not import Engine or Mission Control directly.
- Return authored, stable errors: non-participant is `403`; no active event,
  participant, or assigned active range is a non-enumerating `404`; a paused,
  provisioning, failed, or generation-mismatched range is `409`; rate limit is
  `429` with `Retry-After`; unavailable provider material is a bounded `503`.
  Raw provider, certificate, secret-reference, endpoint, and topology details
  never enter the error envelope.
- Treat successful delivery as a security audit event through `shared.audit`.
  Its current action vocabulary has no download/delivery action, so add one
  generic stable `DOWNLOAD` member there and use the existing `CREDENTIAL`
  entity type; do not mislabel delivery as `CONNECT`, because this endpoint
  cannot observe tunnel establishment. Keep the `risk_register.AuditLog` field
  choices and migration state in sync with the canonical vocabulary. Audit only
  range/participant correlation, channel, profile version/generation, and
  outcome. Do not create a VPN audit table or record profile content, secret
  reference, certificate serial, IP, route, or provider response.
- Use the existing CTF credential-delivery fixed-window limiter backed by the
  `launch_rate_limit` cache, or minimally relocate that helper for the canonical
  API. It must remain shared across workers and fail closed with the existing
  bounded `429`/`503` behavior. Do not introduce an in-process or view-local
  second counter.
- Rollout is capability-gated, not provider-branched. Every CTF live-fire
  adapter admitted by `shared.range_instantiation_policy` must pass the same
  real-client handshake, Kali reachability, negative isolation, lifecycle, and
  secret-deletion contract before the control is enabled. An adapter without
  the capability fails admission before mutation; the SPA must not inspect
  `CLOUD_PROVIDER` or offer a button that predictably returns unavailable.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| SPA range state and actions | `frontend/src/features/ctf/RangePage.tsx`, `frontend/src/api/ctf.ts`, TanStack mutations | Show the control only for the active ready binding; keep data fetching and download orchestration out of the component. |
| Browser transport, CSRF, request correlation, errors | `frontend/src/api/client.ts`, `frontend/src/api/errors.ts` | Add a binary/download response mode to the one client while retaining JSON error-envelope parsing, same-origin credentials, CSRF, abort signals, and `X-Request-ID`. Do not call `fetch` directly from the component. |
| Frontend contracts | runtime DRF schema, committed `openapi/v1.json`, generated `frontend/src/api/schema.d.ts`, ADR-040 | Describe binary success and JSON errors in the runtime endpoint, regenerate artifacts, and import generated types. Do not hand-write a duplicate response DTO or edit generated files manually. |
| CTF HTTP authorization | `ctf.api._base.CTF_PARTICIPANT_PERMISSIONS`, `HasCTFEndpointScope`, `shared.api_tokens.scopes` | Preserve active actor, active participant, exact-scope, session/token, and CSRF behavior. Add one exact scope at the registry, not another token permission system. |
| Active-event participant resolution | `ctf.api.organizer._base._resolve_active_participant`, `ctf_actor_user`, `ctf.services.range._get_participant_with_range` | Derive participant and range from the authenticated actor's active event and existing participant link. Never accept either identifier from the request. |
| Cross-domain boundary | `ctf.bridges`, public `cms.services` facade, `.importlinter` | CTF calls CMS through its bridge; CMS calls Engine through its existing service seam. No CTF import of Engine/Mission Control and no controller call into a provider adapter. |
| Range identity and ownership | `cms.services._range_queries.get_active_range`, CMS primary-key lifecycle loaders, Engine `Range`/request state | Keep CMS `RangeInstance.pk` distinct from nullable legacy `range_id` and Engine request/member UUIDs. Validate owner, CTF provenance, status, request, and generation at access time. |
| Authorized member target | existing `RangeSpec.participant_access`, CMS hydrator, Engine realized member/access projections, ADR-039 remote-access result | Reuse the logical Kali/attacker target and its authored UUID; add no VPN service to Cyberscript and accept no hostname/IP from the participant. |
| Provider selection and realization | installation backend bundle, `shared.range_instantiation_policy`, ADR-039 substrate capability profile, AWS Terraform and GCP GCE live-fire paths | Select one adapter from validated root configuration and enforce provider-neutral capability conformance. Do not branch in CTF, CMS, Engine domain policy, or the SPA. |
| Secret storage and resolution | provider secret stores through `shared.cloud`, provisioner credential helpers, `engine.secrets` bounded resolver/cache, Engine terminal access-time pattern | Persist only a generation-specific reference and resolve/validate profile material after ownership/state checks. Extend the existing resolver; do not add a portal secret client, profile table, attachment bucket, or unbounded cache. |
| Persistence and recovery | Engine-owned request/range/member state, existing state writers, operation generation, outbox/reconciler | Persist the one canonical access binding with adapter state. CTF keeps only its existing range link/status cache. Retain deletion evidence after partial failure; do not expand direct provisioner SQL beyond its current seam (#478). |
| Errors | ADR-039 failure classification, CTF `_CtfApiError`, `shared.api.errors`, SPA `ApiError` | Translate once at each boundary into fixed codes/messages. Do not introduce an OpenVPN exception hierarchy or serialize `str(exc)`. |
| Rate limiting | `shared.rate_limit.consume_fixed_window`, `ctf.views._access._check_credential_delivery_rate_limit`, `launch_rate_limit` cache, Mission Control fail-closed throttle pattern | Use the existing cross-worker credential-delivery budget and `Retry-After`/unavailable semantics. |
| Audit and logging | `shared.audit` event/port/vocabulary, `risk_register.AuditLog`, `ctf.services.audit`, `shared.log_sanitize`, provisioner `log_redact`, ECS JSON logging | Extend the one vocabulary with generic `DOWNLOAD`, keep ORM choice migration state aligned, emit one bounded credential event, and use structured safe correlations/fingerprints. Never log or measure credential/profile/topology material. |
| Configuration and runtime | installation closed backend settings, generated runtime inventory, `config/env-manifest.json`, `config._runtime_env`, `config._cloud`, `engine.ecs` env allowlist, Kubernetes admission policies | Prefer safe fixed defaults. Any operator setting is non-secret, closed, validated once, rendered through every canonical projection, and admitted consistently. Secret material never becomes env or ConfigMap data. |

The challenge-attachment path in `ctf.api.organizer.attachments`, `ctf.s3`, and
the SPA challenge download flow is not a credential-delivery incumbent. Its
presigned object URL is intentionally not reused for profiles; only its user
experience can inform the button interaction.

## Cross-Cutting Security And Validation Layers

1. **Browser and SPA boundary.** `RangePage` consumes safe readiness from the
   canonical range-access projection and invokes a typed mutation. The shared
   client sends same-origin credentials, CSRF and request correlation, verifies
   success media/size, constructs a short-lived Blob URL, clicks a fixed safe
   filename, and revokes the URL. The profile is not stored in React/TanStack
   cache, local/session storage, IndexedDB, analytics, error state, or a service
   worker cache. The UI identifies the file as a private credential; a browser
   cannot promise POSIX file mode on the participant's machine, so it must not
   claim to enforce local-device storage security.
2. **DRF authentication and token shape.** The configured API authentication
   order remains API token then session. `IsAuthenticatedSessionOrApiToken`,
   `HasActiveCTFActor`, `HasCTFParticipant`, and `HasCTFEndpointScope` all run.
   `validate_scopes()` admits the new exact registry member and still rejects
   unknown, blank, or wildcard scopes. Session POSTs pass the existing CSRF
   validator; tokens do not bypass role/ownership/state checks.
3. **CTF role/event/participant policy.** `_resolve_active_participant` binds the
   actor to `UserProfile.active_ctf_event_id`; active-participant status excludes
   disqualified/inactive rows. `_get_participant_with_range` verifies the linked
   user and server-owned range link. This prevents a second participant id,
   event id, or range id from becoming an insecure direct-object reference.
4. **HTTP shape and media contract.** The endpoint accepts no JSON/form/query
   target input. DRF/OpenAPI declares a bodyless POST, the profile success media
   and headers, plus the shared JSON error envelope at every failure status.
   Profile byte length and UTF-8/text shape are bounded before headers are sent.
   The response filename is constant or derived only from a safe server-side
   opaque identifier, never from email, scenario title, or request data.
5. **CMS/Engine ownership and state.** CMS verifies the authoritative
   `RangeInstance.pk`, owner, `RangeSource.CTF`, non-deleted active row, `READY`
   status, and Engine request linkage. Engine verifies the same request and
   current generation under its existing access-time ownership/member resolver
   before using the binding. A stale secret cache entry cannot authorize access:
   current ownership/state/generation is checked on every request.
6. **Closed realization and profile shapes.** Existing scenario and ACES parsers
   validate authored topology; OpenVPN is not added to them. The ADR-039 adapter
   validates its closed capability/result and rejects missing, duplicate,
   foreign, or wrong-generation target/binding data before mutation or delivery.
   A versioned, deterministic profile renderer permits only the directives the
   platform owns and re-parses its output before storage/delivery. Reject script,
   plugin, external credential-file, shell hook, arbitrary route/DNS, inline
   include, management, and other client-code-execution or policy-bypass
   directives.
7. **Secret handling.** Credential generation happens inside the selected
   adapter/issuer and writes directly to the provider secret store. The Engine
   access boundary receives only a reference, resolves the small bounded value
   in memory, validates version/integrity, and returns it without a temporary
   file. If a provider tool requires files, use a restrictive per-operation
   temporary directory, mode `0600`, argv arrays without a shell, and guaranteed
   cleanup. Generation-specific references prevent cache aliasing after rotate;
  destroy deletes provider material and invalidates the authoritative binding.
  A binding also prevents an in-place owner change; recovery destroys and
  reprovisions rather than leaving an external client credential valid after
  authority moves.
8. **Process, task and host exposure.** Existing structured
   `range <operation> --request-id <uuid>` argv remains. Profiles, PEM blocks,
   signing keys, endpoints, routes, and secret references do not enter argv,
   process listings, task definitions, Kubernetes Job specs, ConfigMaps, shell
   command strings, or Terraform plans/state. Existing pinned-image,
   least-privilege workload identity, non-root/read-only-root, dropped
   capabilities, admission, bounded workspace, and cleanup rules remain in
   force.
9. **Network enforcement.** The range adapter validates request ownership,
   endpoint allocation, unique VPN client subnet, mutual-TLS server identity,
   target-member membership, `/32` route, forwarding firewall, public gateway
   ingress, and negative management/metadata/cross-range/default-route controls.
   Profile contents are not an authorization oracle. Provision, pause, resume,
   destroy, replay, and partial-failure cleanup all observe those controls.
10. **Errors, audit and observability.** Provider/issuer/parser failures map to
    ADR-039 codes, then to fixed CTF API messages and the shared envelope with
    request id. `shared.log_sanitize.safe_log_fingerprint` and provisioner
    `log_redact` protect sensitive identifiers. Logs/audit may contain action,
    outcome, stable failure class, operation/generation and safe correlation;
    no profile bytes, PEM, secret reference, CA/certificate identity, target IP,
    endpoint, route, raw exception, or provider response crosses the boundary.
11. **Root config and deployment validators.** Any non-secret tuning (for
    example certificate maximum lifetime or an adapter port/policy) is declared
    in the existing closed backend settings, range-checked, rendered through
    installation/runtime inventory, compared by config parity/startup checks,
    and added to task env/admission allowlists only if a process truly needs it.
    Unknown fields and deployed missing values fail closed. Never put a profile,
    key, CA, full OpenVPN config, or secret reference in root YAML, environment,
    generated output, Helm values, Terraform variables, or command flags.
12. **Provider parity and release evidence.** AWS Terraform and every GCP
    live-fire backend currently admitted for CTF must run an identical
    provider-neutral conformance fixture plus disposable real-provider tests
    using a standard OpenVPN client. Evidence proves handshake, only-Kali
    reachability, denied other-range/member/platform/metadata paths, pause and
    resume behavior, teardown revocation/deletion, replay, rotation, and no
    secret leakage. GDC's validation-only posture is not a parity substitute.

## Extensibility Seam

The seam is ADR-039's trusted remote-access capability/profile on the range
operation plus the product-neutral CMS/Engine profile resolver. Its parameters
are a closed access channel (`openvpn`), renderer/profile version, current range
generation, and authoritative member target; the selected adapter supplies the
provider endpoint and secret reference.

The blocked non-CTF follow-up adds another product controller and its own role /
ownership policy, then calls the same CMS/Engine service. It must not add CTF
group logic to Engine, a `user_type` field to the credential, a second download
endpoint inside CMS, or a second provider profile renderer. A future profile
format or explicit rotation adds a new closed renderer/capability version at
this seam, without changing scenario schemas or provider branches in the SPA.

Expose only a safe derived readiness/capability field in the CTF range-status
projection so the SPA can render the control. Do not expose endpoint, target IP,
secret reference, certificate metadata, provider, or adapter state. The field
is derived from the current authoritative generation's access binding, not from
cached `CTFParticipant.range_status` alone or a frontend provider check.

## Whole-Repository Surfaces In Scope

- CTF SPA and API contract: `RangePage`, CTF hooks, the shared fetch/error
  client, generated OpenAPI types, range API URLs/views/serializers, and their
  component/contract tests;
- CTF identity and workflow: DRF permissions/scopes, active-event participant
  resolver, participant range service, CTF bridge, credential-delivery limiter,
  and CTF audit helper;
- CMS/Engine boundaries: public CMS service facade, CTF-primary-key ownership
  loaders, Engine request/range/member access services, secret resolver/cache,
  operation generation, state writers, outbox, and reassignment/recovery paths;
- scenario/realization: `shared.schemas`, Cyberscript `participant_access`, CMS
  hydrator, ACES presentation projections, GCP closed range-cell contract and
  output renderer. These are target authorities, not a place for VPN policy;
- substrate/provider: ADR-039 capability/result, AWS Terraform range resources,
  GCP GCE range-cell resources, provider secret stores/issuer, network allocation
  and firewall policy, lifecycle cleanup, state/locking, and real-provider
  conformance evidence;
- config/runtime: installation loader/schema/registry/runtime inventory, Django
  env manifest/startup validators, Engine task env allowlist, provisioner config,
  Terraform/TFLint/Checkov, Kubernetes base/Helm admission parity, Pod Security,
  kube-linter, and kubeconform; and
- cross-cutting enforcement: `.importlinter`, ADR guard, ADR-029/039/040,
  `shared.api.errors`, `shared.rate_limit`, `shared.audit`, ECS JSON logging,
  `shared.log_sanitize`, provisioner `log_redact`, gitleaks, API schema drift,
  and frontend lint/test/build checks.

## Gotchas And Anti-Patterns

- Do not confuse `CTFParticipant.range_instance_id` / CMS `RangeInstance.pk`
  with the nullable legacy `RangeInstance.range_id`, Engine request UUID, or an
  authored member UUID. Ownership and lookup helpers must name which identity
  they accept.
- Do not model OpenVPN as Cyberscript's CTF `service_type: vpn`, add it to every
  scenario template, or extend scenario `participant_access` merely to switch
  on a platform access plane. Scenario services run inside the challenge;
  participant client access is platform infrastructure.
- Do not terminate on Kali, expose Kali publicly, use a shared cross-range VPN
  server/CA, trust client-pushed routes, enable client-to-client traffic, or
  route the entire range/default network.
- Do not generate a new certificate on each download, share one profile between
  participants/ranges, permit reassignment while an old downloaded profile is
  live, or rely on expiry instead of generation teardown.
- Do not store the profile in a CTF attachment model/S3 bucket, Django field,
  state JSON, outbox/event, audit state, TanStack/browser persistence, temp file,
  ConfigMap, environment variable, Terraform state, or a presigned URL.
- Do not introduce a second secret-store facade, cache, range repository,
  validator, status enum, API error envelope, audit model, rate limiter,
  exception hierarchy, lifecycle workflow, or provider selection switch.
- Do not return raw `str(exc)`, certificate-parser text, secret references,
  provider resource names, addresses/routes, or the malformed profile in an API
  error, log, metric label, trace attribute, or audit state.
- Do not bypass the shared SPA client for Blob handling, parse every response as
  JSON, treat a binary error as a profile, use caller-controlled filenames, or
  omit `no-store` because the URL is authenticated.
- Do not show the button from `status == ready` alone unless readiness is
  defined to include the current OpenVPN binding. Do not key availability from
  `CLOUD_PROVIDER`, silently omit parity, or make one provider return a
  permanent `503` after the feature is advertised.
- Do not consider Terraform apply, secret creation, gateway process start, or a
  port-open check sufficient readiness. A standard client handshake plus
  positive target and negative isolation probes are required promotion evidence.

## Non-Goals And Implementation Boundaries

- Extending participant VPN access to non-CTF user types remains the blocked
  follow-up; only the lower service seam is kept reusable.
- Existing SSH terminal and Guacamole behavior, URLs, credentials, and browser
  workspace UI are unchanged.
- This issue does not redesign scenario authoring, ACES semantics, public range
  lifecycle state, general cloud capability taxonomy, provider selection,
  task dispatch, or the #478 provisioner persistence boundary.
- A user-facing rotate/revoke endpoint, multiple simultaneous participant
  devices, client inventory, operator VPN administration UI, shared VPN hub,
  full-range routing, split-DNS, internet egress through the range, and support
  for non-OpenVPN protocols are outside this issue.
- Provider-internal gateway packaging and certificate issuer implementation may
  differ, but may not weaken the common ownership, lifecycle, secret, network,
  profile, or conformance contract.
