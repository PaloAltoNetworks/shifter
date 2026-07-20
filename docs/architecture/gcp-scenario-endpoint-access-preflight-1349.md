# GCP Scenario Endpoint Access Preflight

Issue: GitHub #1349, "Implement portal access to scenario-declared GCP
range-cell endpoints."

Status: pre-implementation architecture guidance. The issue is the shipping
contract. This note selects boundaries and guardrails; it neither implements
the feature nor supplies an implementation plan.

## Decision

Use the existing bidirectional peering between the platform and range VPCs as
the private data path. Do not add public VM addresses, an Internet ingress
path, IAP participant tunnels, a bastion, or a second access proxy.

The browser never connects to a range address. It authenticates to the portal,
and an existing platform access workload makes the private connection:

- the portal ASGI terminal path remains the dialer for the existing browser SSH
  websocket; and
- `guacd` remains the dialer for Guacamole SSH/RDP sessions. The
  `guacamole-client` signs and serves sessions but does not dial range guests.

The platform must treat these as explicit access-plane identities, distinct
from the provisioner management path. GKE NetworkPolicy permits range egress
only for the relevant workload and approved channel ports. GCE firewall policy
admits only a configured access-workload source CIDR (or a stronger workload
identity primitive approved later), targets the current range's network tag,
and opens only ports represented by that range's validated declarations.
Provisioner/bootstrap ingress remains a separate rule and must not become a
participant-access wildcard. A shared platform-pod CIDR by itself is not a
sufficient identity boundary: if source-CIDR firewall rules remain the GCE
enforcement primitive, the access workloads need dedicated, non-overlapping pod
source ranges whose placement and rendered NetworkPolicies are tested.

IAP remains an operator/break-glass control path for explicitly approved
private hosts. It is not the participant data plane and must not be exposed as
a portal-generated tunnel credential.

## Contract And Persistence Boundary

The endpoint contract already exists and must not be duplicated:

- scenario YAML uses `cms.scenarios.schema.ParticipantAccessConfig` and the
  hydrator maps names to stable authored member UUIDs;
- the persisted `RangeSpec.participant_access` and
  `shared.range_cells` request carry closed `{target_ref, channel}` logical
  declarations;
- `build_gcp_vm_range_cell_result` returns the closed realized binding
  `{target_ref, channel, address, port, credential_ref}` after proving the
  target is a realized member, the channel was declared, the address/port are
  valid, and the credential is a provider secret reference; and
- CMS/CTF/portal responses expose a response-safe projection, never the secret
  reference, private credential, provider response, or signed URL.

Persist the validated realized access binding through the existing Engine
range/instance state writers and `Range.provisioned_instances` compatibility
projection. Do not add an access repository, a second endpoint JSON column, or
re-derive authorization from `role`, `os_type`, a scenario id, or the mere
presence of an SSH/RDP credential. The closed range-cell result is the source
of truth; state projections may retain only fields needed for authorization,
connection resolution, display, and cleanup. Secret values never enter state.

The access service must resolve by stable target reference and declared
channel, then re-check the current range/participant authorization, READY
state, target membership, persisted binding, and supported channel before
fetching a credential or opening a socket. An address supplied by an HTTP
request, scenario document, CMS view, or stale bootstrap row is never dialed.
This is the SSRF and cross-range boundary.

## Authorization And Revocation

Reuse the current Mission Control/CTF authentication and ownership sources;
do not create an independent access-grant model. Session/API-token auth,
Mission Control actor and scope permissions, CTF participant gates, range
ownership/source, participant active/deleted state, and READY lifecycle state
must all be current at access time. Operators use an explicit existing
operator authorization policy; ownership must not be bypassed merely because
the caller is staff.

Authorization is checked both when a bootstrap/connect request is accepted and
immediately before the credential is resolved or the private connection is
opened. A queued bootstrap must therefore fail closed if access changes while
it waits.

Revocation has two parts:

- range pause/destroy or removal of the declared binding makes new access fail
  and removes/blocks the provider path as part of the convergent lifecycle; and
- participant authorization removal terminates or expires already-open browser
  SSH and Guacamole sessions within a documented, tested bound, as well as
  invalidating pending/undelivered bootstraps.

The current five-minute JSON-auth/bootstrap expiry only limits token delivery;
it is not proof that an established Guacamole or SSH session was revoked. The
implementation must use the existing terminal session registry/lifecycle hooks
where applicable and the supported Guacamole connection/session termination or
bounded-lease facility for Guacamole. If the platform cannot actively terminate
a protocol session, its maximum lease is a security parameter and reconnect
must pass full authorization again. Range destruction additionally revokes by
removing the target and per-range credential, but that does not replace the
participant-removal path.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Scenario and endpoint validation | `cms/scenarios/schema.py`, `hydrator.py`, `cyberscript/schemas/range.py`, `shared/range_cells.py` | Extend the existing versioned channel vocabulary only; no parallel DTO or validation tree. |
| Realization and provider safety | `gcp_range_cell_scenario.py`, `gcp_range_cell_plan.py`, `gcp_range_cell_outputs.py`, `gcp_range_cell_resources.py` | Resolve member addresses from provider-owned plans/results; no external IP; keep cell-tagged firewall rules convergent with destroy. |
| Persistence | `state_helpers.py`, `provisioner_db.write_provisioned_state`, Engine `Range`/`Instance` state | Persist the validated binding once through current writers; preserve references, never secret values. |
| Browser SSH | `engine.services._terminal`, `mission_control.consumers.SSHConsumer`, `terminal_sessions` | Preserve owner/status/member checks, bounded executor/session admission, and websocket audit. |
| Guacamole | `mission_control.api.guacamole`, `views/_guacamole*`, `guacamole.py`, `guacamole_bootstrap.py`, `GuacamoleBootstrapRequest` | Preserve DRF auth/scopes, asynchronous just-in-time credential resolution, one-time URL delivery, bounded token lifetime, and sanitized failures. |
| API and views | Mission Control DRF serializers/permissions, CMS query services, CTF participant gates/bridges, existing range views | Project the same safe endpoint shape; do not let frontend availability become authorization. |
| Network | platform/range VPC peering, range VPC deny baseline, per-cell firewall plan, Helm/Kustomize NetworkPolicies | Separate access identities/ports from provisioner management and deny every other platform workload. |
| Secrets | GCP Secret Manager, `engine.secrets`, `shared.cloud`, entrypoint secret hydration | Store references only and fetch just in time; never put secrets or signed URLs in events, argv, manifests, metadata, logs, or responses. |
| Errors, logs, and audit | `shared.api.errors`, `shared.errors`, `shared.log_sanitize`, provisioner `log_redact`, `shared.audit.audit_session_event` | Stable authored errors; log/audit actor, range, target fingerprint, channel, decision, and correlation—not addresses, credentials, payloads, or token URLs. |

## Cross-Cutting Security Gates

- **Auth surface:** Django session or scoped API-token authentication, Mission
  Control actor/scope permissions, CTF active-participant policy, ownership or
  explicit operator policy, READY state, member target, and declared channel
  all fail closed before enqueue and again before dial.
- **Shape and parser surface:** scenario Pydantic validation, persisted-envelope
  schema/version/digest validation, the closed range-cell request/result
  validators, DRF serializers, and response serializers each validate their
  own boundary. Unknown channels/fields, duplicates, dangling targets,
  non-private/foreign addresses, invalid ports, or malformed secret references
  fail before cloud mutation or connection.
- **Configuration surface:** `shifter/installation`, provisioner
  `load_gce_range_cell_config`, Terraform variable validation, bootstrap runtime
  rendering, Helm values/schema, and Kustomize/Helm parity own environment
  shape. Access source ranges and approved channel-to-port mappings are typed
  configuration, not ad hoc env reads. Any new env key must also pass
  `env-manifest.json`, sensitive-env handling, and GCP Job/admission allowlists
  where the provisioner consumes it.
- **Cloud and OS exposure:** range VMs have no `access_config`; only peered
  private addresses are dialed. Scenario data, addresses, secret references,
  credentials, Guacamole payloads, and tokens never appear in process argv,
  shell strings, GCE metadata/startup scripts, Kubernetes Job literals, Helm
  values, workflow output, or command history.
- **Network surface:** Kubernetes default deny, access-workload egress policy,
  dedicated source identity/range, cell-targeted GCE ingress, and per-declared
  ports must all agree. Peering supplies routing, not authorization.
- **Secret surface:** only provider secret references cross provision/persistence;
  values are resolved in the existing off-request-thread access boundary and
  passed only to the connection builder. Bootstrap token URLs retain existing
  one-time delivery and at-rest pruning.
- **Error and observability surface:** DRF uses the canonical error envelope;
  legacy/websocket paths use authored classifications/close codes. Raw
  provider/parser/secret exceptions and private endpoint data stay out of user
  envelopes, metrics, durable events, and logs. Connect, deny, disconnect, and
  revocation use the shared audit vocabulary and trusted client-IP policy.

## Extensibility Seam

The seam is the versioned logical `channel` discriminator plus a
platform-owned channel policy registry: protocol, allowed port set, dialer
workload, credential kind, session lifetime/revocation behavior, and UI
capability. The scenario chooses only a supported channel and member; it cannot
supply a dialer, arbitrary port, URL scheme, hostname, or firewall rule.

The corresponding infrastructure parameters are the dedicated access-workload
source ranges and the channel-to-port projection. Adding one approved protocol
should extend that registry, its broker adapter, policy rendering, and
conformance tests without changing scenario topology, range lifecycle APIs, or
the endpoint state envelope. Multi-cell ranges remain possible because every
binding resolves through stable member/cell identity rather than a singleton
range address.

## Gotchas And Anti-Patterns

- Do not infer access from OS/role, credential existence, image family, or
  scenario name. Windows/DC and attacker/victim are scenario semantics.
- Do not expose `private_ip`, `credential_ref`, provider resource ids, or signed
  URLs in CMS/CTF list views merely because they are persisted.
- Do not accept arbitrary host/port/protocol input at the portal or treat a
  validated scenario target as a generally reachable proxy destination.
- Do not let all platform pods reach range ports, combine provisioner admin
  ingress with participant ingress, or rely on peering/routing as an auth gate.
- Do not use IAP, public IPs, NAT ingress, SSH port-forward subprocesses, or
  per-session firewall churn as the participant mechanism.
- Do not duplicate range-cell schemas, endpoint validators, exception classes,
  audit vocabulary, secret adapters, Guacamole bootstrap logic, lifecycle
  controllers, or state repositories.
- Do not consider URL/token expiry sufficient revocation evidence for an
  established session, and do not leave queued bootstraps valid after an auth
  change.
- Do not log raw exception text from provider/secret/connection boundaries or
  private addresses; use stable codes, safe classifications, and fingerprints.

## Non-Goals And Boundaries

- No scenario topology, mandatory range host, Windows/DC model, internal DNS,
  service discovery, arbitrary port publishing, or universal endpoint schema.
- No replacement of the browser terminal or Guacamole UX, and no new public
  tunnel API, bastion service, VPN, participant IAP role, or general-purpose
  proxy.
- No change to backend selection, GCE range-cell lifecycle ownership, AWS
  access topology, ACES cutover policy, or operator break-glass policy.
- No implementation in this preflight. The implementation owns migration and
  compatibility details while preserving the boundaries above.

## Required Evidence

- At least two materially different scenario compositions map their validated
  declarations to the existing CMS/CTF/portal projection without role/OS or
  scenario-id branching.
- SSH and RDP declarations produce only their approved private paths and ports;
  undeclared channels, foreign members, arbitrary addresses/ports, cross-range
  access, non-access platform pods, and non-READY ranges fail closed.
- Tests cover every validation/config/network layer above, no external VM IP,
  Helm/Kustomize parity, and the rendered effective GCE firewall semantics.
- Revocation tests cover pending bootstrap, undelivered token, open browser SSH,
  open Guacamole session, participant deletion/access removal, pause, destroy,
  repeated destroy, credential cleanup, and the documented maximum revocation
  bound.
- Logs, events, API payloads, audit rows, database projections, manifests, and
  process argv are checked for credentials, token URLs, and unintended private
  endpoint disclosure.
