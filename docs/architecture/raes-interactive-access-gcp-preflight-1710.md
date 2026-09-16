# RAES Interactive Access on GCP Preflight

Issue: GitHub #1710, "Consume RAES interactive_access for RAES-native GCP
range participant access."

Status: pre-implementation architecture guidance. The issue is the shipping
contract. This note selects boundaries and guardrails; it does not implement the
feature or provide an implementation plan.

## Current Baseline

The requested package upgrade is already present on the development baseline:
`shifter/shifter_platform/pyproject.toml` and `uv.lock` pin
`raes==2.0.0` and `raes-env-packs==3.0.0`. The provenance-ledger v2,
backend-manifest v2, bounded producer read window, and associated conformance
fallout are therefore incumbents to preserve, not migrations to repeat.

`raes` validates authored `agents.*.interactive_access`, and the RAES
compiler lowers it into
`RuntimeModel.participant_behaviors[*].interactive_access`. Each compiled entry
already carries the resolved provisioning node address, channel, and optional
resolved account address. It is intentionally absent from the
`ProvisioningPlan`: Shifter publishes a provisioning-only backend and has no
RAES participant-runtime lifecycle/history implementation.

The GCE realizer currently discards this participant-domain intent:
`raes_gcp_plan._instance_plans_for_node()` writes
`participant_access_channels: []`, and the RAES operation-result path records
only redacted runtime-snapshot evidence before marking the range READY. It does
not currently persist the returned GCE instance outputs into
`Range.provisioned_instances`, which is the portal access projection used by
the #1349 terminal and Guacamole services.

## Decision

### Preserve the RAES domain boundary

Extract interactive access only from the typed, compiled
`ParticipantBehaviorRuntime.interactive_access` collection inside
`shared.raes`, after RAES instantiation, semantic admission, compilation, and
planning have succeeded. Do not read raw YAML, reparse `agent_specs`, inspect
`realization_instance`, or infer access from provisioning node/account payloads.

The extracted data is a versioned, bounded participant-access realization
sidecar beside the serialized `ProvisioningPlan`, never inside it. Its
non-secret entries contain only the resolved compiled node address, closed
channel, and resolved compiled account address. Authoring-only access ids and
agent descriptions may appear in bounded diagnostics but are not authorization
or provider identity. The sidecar is participant intent, not a Shifter SDL,
provisioning resource, manifest capability, public DTO, or runtime-snapshot
entry.

Shifter must continue to publish no RAES `participant_runtime` capability. This
slice brokers one declared access surface through the existing Shifter product
and range substrate; it does not implement participant episodes, behavior
history, shared state, observations, or the RAES participant control protocol.

### Do not collapse participant identity into range ownership

RAES interactive access is participant-local, while the current Mission
Control/CTF range model authorizes a Shifter range owner and has no trusted
mapping from that actor to an RAES participant behavior. Unioning endpoints
from red, blue, or other agents would broaden every actor to the most privileged
agent and is prohibited.

For the current product contract, interactive access is realizable only when
the normalized binding set is participant-invariant across every compiled
participant behavior. A participant with an empty set and another with a
non-empty set is ambiguous and must fail before dispatch. A future product may
provide a server-derived participant selection at the CMS launch boundary; that
selection belongs beside the existing user, workspace, backend admission, and
request id, and must be persisted as trusted ownership context. It must not be
chosen by a terminal/Guacamole target request or inferred from entity role,
agent name, CTF team name, `RangeInstance.agent_name`, or endpoint possession.

### Keep the sidecar immutable and operation-scoped

Persist the validated sidecar separately from `Range.range_config`, in the same
Engine transaction that creates the range and its existing immutable launch
bindings. Follow the `RaesContentDeliveryBinding` pattern: one Engine-owned
row per binding, uniqueness on range plus compiled target/channel, cascade
cleanup, and no credential or provider data. Idempotent request reuse must
compare the persisted bindings and reject same-request/different-access intent.

`engine.operation_inputs` must project the sidecar into the existing immutable
RAES operation input. `shared.raes.operation_input` owns its exact-key,
version, count, string, channel, and duplicate validation. The provisioner
continues to read one generation-fenced operation-input row and receives no new
direct table grant. Do not put the sidecar in `range_config`, task argv,
environment variables, GCE metadata, startup scripts, operation receipts, or
the redacted RAES runtime snapshot.

### Join participant intent to provisioning truth before mutation

The standalone provisioner keeps `raes_plan.parse_plan()` as the only
`ProvisioningPlan` consumer and keeps participant access as a separate
process-local value. Before any network, VM, Secret Manager, SSH, or guest
mutation, a cross-contract gate must prove:

- every target address resolves to exactly one parsed VM node;
- the target node materializes exactly one instance; `count != 1` is
  unsupported until RAES supplies an instance selector or explicit multiplicity
  semantics;
- every binding carries an explicit account address; Shifter has no approved
  default participant account, and omission must not expose the reserved
  `raes` management account;
- the account resolves, targets the same node, is enabled, and is a local
  account handled by the existing account-credential realizer;
- SSH uses the existing public-key account strategy and RDP uses the existing
  password account strategy; do not silently add a second authentication method
  to an authored account;
- the channel is one of the existing range-cell `ssh`/`rdp` values and maps to
  the existing fixed port policy; and
- no target/channel is missing, duplicated, or emitted in excess of the
  participant sidecar.

Domain-scoped/directory accounts are not eligible until the directory realizer
offers the same bounded `(login name, credential reference)` broker contract
and its portal login form is specified. The local account secret functions in
`raes_account_credentials` and `gcp_guest_secrets` remain canonical. Extend
their existing result seam to retain the reference returned while installing
and verifying a credential; do not call a second secret adapter, mint a
parallel credential, or expose the host-management secret.

The resolved per-channel login name is non-secret realization metadata. Preserve
it per channel in the instance projection; one shared `ssh_username` must not be
used to conflate different SSH and RDP `account_ref` values.

### Reuse the closed #1349 access and lifecycle path

The RAES instance plan feeds the validated channel set into the existing neutral
GCE range-cell plan, resource, firewall, credential-reference, and output
helpers. The existing management key remains separate. The existing
`ACCESS_NETWORK_CIDRS`/`portal_network_cidrs` policy, access-workload
NetworkPolicy, private VPC path, range tags, and fixed port mapping remain the
only network path. RAES `Node.services`, authored ACLs, OS family, image name,
credential existence, and successful VM creation are not participant
authorization and must not synthesize a binding.

A binding may be published only after the account credential was installed and
verified and the declared endpoint is ready through the approved private path.
SSH host identity continues to come from the provisioner-injected host key.
RDP readiness cannot be inferred merely from a password or Windows label.
Unsupported image/channel combinations fail as unsupported capability rather
than producing a READY but unusable endpoint.

The existing #1349 portal services remain the dial boundary:

- `engine.services._terminal` rechecks authenticated ownership, READY state,
  current member, and declared channel before resolving a credential;
- the browser SSH terminal remains the SSH dialer;
- `mission_control.guacamole_session` and
  `_guacamole_session_builders` retain the bounded asynchronous bootstrap and
  guacd path; and
- pause, destroy, binding removal, and ownership/participant revocation retain
  the existing fail-closed behavior.

Do not add an RAES endpoint API, participant tunnel, public IP, IAP role,
bastion, generic proxy, or second Guacamole bootstrap workflow.

### Make realized state authoritative before READY

ADR-043's operation-result inbox remains the sole authoritative return path.
The RAES provisioner must not regain direct writes to `Range`,
`provisioned_instances`, Engine instance state, or RAES sidecar tables.

The closed terminal-ready result carries the bounded realized member/access
projection needed by `Range.provisioned_instances`. The Engine applier validates
membership, private addresses, fixed ports, GCP secret-reference syntax,
per-channel usernames, channel equality with the immutable declaration
sidecar, and host-key material before it atomically persists the projection,
strict audit record, READY transition, and range notification. A terminal
success must not be applicable when the realized member/access projection is
missing, stale, conflicting, or belongs to another operation generation.

Keep the RAES runtime snapshot separate and redacted. It remains evidence of
compiled resource realization and must not acquire IPs, usernames, credential
references, host keys, participant ids, or provider resource ids.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Package/version contract | `shifter_platform/pyproject.toml`, `uv.lock`, ADR-032-R4, package/conformance tests | Preserve the exact released 2.0.0/3.0.0 pair and the exact-producer-version rule; do not repeat the upgrade or pin a git ref. |
| SDL shape and semantics | RAES `ParticipantInteractiveAccess`, `analyze_participant_interactive_access`, compiled `ParticipantBehaviorRuntime.interactive_access` | Consume the typed resolved compiler output. Do not copy target/account/duplicate validation into CMS or the provisioner. |
| RAES import boundary | ADR-031-R1, `.importlinter`, `shared.raes` | Only `shared.raes` imports `raes_*`; Engine and the standalone provisioner consume a closed plain-data sidecar. |
| Provisioning transport | `shared.raes.runtime_target`, `dispatch_port`, `package_loader`, `raes_plan.parse_plan` | Keep the serialized `ProvisioningPlan` byte-shape free of participant additions. |
| Immutable sidecars | `RaesContentDeliveryBinding`, `engine.operation_inputs`, `shared.raes.operation_input`, `shared.operation_envelope` | Use the existing persist -> generation-fenced projection -> exact parser pattern; add no provisioner table read. |
| Account realization | `raes_composition.RaesPlanAccount`, `raes_account_credentials`, `raes_active_directory`, `gcp_guest_secrets` | Reuse the existing account and Secret Manager operations. Local account support is bounded; directory accounts remain rejected until their broker contract exists. |
| GCE plan and access output | `raes_gcp_plan`, `gcp_range_cell_types`, `gcp_range_cell_firewall`, `gcp_range_cell_outputs`, `shared.range_cells` | Reuse stable member ids, private addresses, channel/port policy, access-workload ingress, and closed binding checks. Do not add an RAES firewall stack or endpoint schema. |
| Authoritative results | `shared.operation_results`, `operation_result_payloads`, `engine.services._operation_apply_raes` | Extend the closed generation-fenced result/apply path and make realized access state a prerequisite of READY; no direct SQL fallback. |
| Persistence/projection | `Range.provisioned_instances`, `state_helpers` projection conventions, `engine._range_state`, `cms.services._queries` | Persist one response-safe realized instance projection. Do not add a second endpoint repository or authorize from the immutable declaration row alone. |
| Portal authorization | `engine.services._terminal`, Mission Control permissions, CTF participant services, `guacamole_session` | Preserve authentication, owner/participant policy, READY/member/channel checks, late credential resolution, and bounded bootstrap delivery. |
| Secrets | `engine.secrets`, provider Secret Manager adapters, account/host secret ops | Persist and transport references only. Values exist only during guest installation or connection construction. |
| Errors/logging | RAES `Diagnostic`, `RaesPackageError`/`CMSError`, `RaesRealizationError`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact` | Use existing boundary mappings and stable codes. Do not add an access exception hierarchy or surface raw account/provider/secret errors. |
| Network/config | `config._gce`, `gcp_range_cell_firewall`, `platform/charts/shifter/templates/networkpolicies.yaml`, `scripts/gcp/render_private_service_netpol.py` | Reuse current access-source configuration and deployment parity. No new setting, env key, public ingress, or per-session firewall mutation. |

## Cross-Cutting Security Layers

| Layer | Gate and required behavior |
| --- | --- |
| Product auth | Mission Control session/API-token permissions or CTF participant/organizer policy run before CMS. User, workspace, backend purpose, package, and any future participant selection remain server-derived. |
| Pack/source identity | Existing repo/object pack containment, archive limits, canonical pack validation, identity match, and digest verification complete before SDL loading. Interactive access never supplies a file, URL, path, or package selector. |
| RAES parser/semantic gate | Pydantic shape, variable instantiation, declaration references, VM target, account target/starting authority, and per-participant duplicate checks run in released RAES code. Compiler-resolved addresses are the only extraction source. |
| Backend validate/apply | The common `RuntimeTarget` validate/apply path rejects ambiguous participant scope and an unsupported Shifter access profile before dispatch. Rejection remains a bounded RAES `Diagnostic`; no range or sidecar row is created. |
| Dispatch/persistence shape | The sidecar parser is exact, versioned, bounded, duplicate rejecting, and non-secret. Range create persists it atomically beside the plan; request-id replay checks equality. |
| Operation input | `shared.operation_envelope` binds request, resource, operation, generation, digest, and exact RAES input. The RAES input parser validates the sidecar again before any provider client is built. |
| Provisioner plan/join | `raes_plan.parse_plan` validates producer/version/resources/topology. A separate join validates target, count, account, account-target, disabled state, auth method, channel, and declaration equality before cloud or secret mutation. |
| Config/network | `load_gce_range_cell_config`, CIDR validation, dedicated access-workload source ranges, Kubernetes default-deny/egress, private peering, and cell-tagged GCE ingress remain mandatory. Routing or an open port is never authorization. |
| Guest/credential | The reserved management account/key is never brokered. Existing local-account install/readback creates the participant credential, and an endpoint readiness check succeeds before the binding is returned. No secret value enters a result. |
| OS/process exposure | Task argv remains the structured `raes-range <operation> --request-id ...` generation-fenced command. Sidecars, plan JSON, account data, IPs, host keys, secret refs/values, and Guacamole payloads stay out of argv, environment, shell command strings, workflow output, and process titles. |
| Result envelope | A closed, bounded operation result carries only the minimum realized projection and secret references. The Engine revalidates generation, membership, addresses, ports, refs, usernames, declaration equality, and result ordering before an atomic state/READY write. |
| Portal/error envelope | HTTP/websocket adapters expose the existing safe response and close-code shapes. Raw RAES, database, GCE, SSH, guest, secret-store, and Guacamole errors and all private endpoint/credential details remain out of user responses and durable diagnostics. |
| Observability/audit | Existing request/range/operation correlation and audit vocabulary remain authoritative. Log stable codes, counts, and fingerprints; do not log raw access sidecars, account names, IPs, secret references, credential values, signed URLs, or provider responses. |

## Extensibility Seams

Two explicit seams prevent the next reasonable change from rewriting the
boundary:

1. **Participant selection:** a future product-owned, server-derived RAES
   participant reference may select one compiled participant policy. Until it
   exists, only participant-invariant policies are admitted; union is never the
   fallback.
2. **Target multiplicity:** a future released RAES contract may define an
   instance selector or explicit fan-out semantics for a node with `count > 1`.
   Until then, one interactive target must materialize exactly one stable member.

The existing versioned channel policy remains the protocol seam. A future
channel extends the upstream RAES vocabulary, shared range-cell policy, broker,
network rules, credential kind, result parser, portal adapter, and conformance
evidence together; arbitrary host/port/protocol fields do not enter the sidecar.

## Whole-Repository Scope

The implementation must evaluate all of these surfaces, even where no edit is
required:

- ADR-031, ADR-032, ADR-039, ADR-043 guidance and the #1349 endpoint-access
  preflight;
- RAES dependency pins, lockfile, package loader, runtime target, manifest,
  backend-manifest artifact, dispatch port, package/conformance/parity tests,
  and import-linter boundary;
- CMS RAES repo/object package launch, workspace/backend admission, active-range
  reservation, range create, idempotent reuse, audit, and CTF/Mission Control
  entry points;
- Engine RAES persistence models, operation-input materialization,
  launch-intent generation, result contracts/inbox/applier, range state,
  `Range.provisioned_instances`, lifecycle notification, and destroy cleanup;
- provisioner RAES plan parsing, account/directory credential realization,
  GCE planning/apply/destroy, Secret Manager naming/deletion, firewall/resource
  rendering, host-key handling, endpoint readiness, result append, and
  redaction;
- portal target listing, terminal/SSH connection resolution, RDP resolution,
  Guacamole bootstrap/session builders, secret readers, READY/member/channel
  checks, CTF participant removal, pause, destroy, and ownership transfer; and
- `ACCESS_NETWORK_CIDRS`/portal CIDRs, Helm and generated NetworkPolicies,
  private-service policy rendering, GCE firewall tests, admission/runtime
  hardening, ADR guard, layer/import checks, secret scanning, and real-provider
  endpoint/isolation evidence.

## Gotchas And Anti-Patterns

- Do not union interactive access across RAES agents or treat a scenario-global
  endpoint list as equivalent to participant-local authority.
- Do not confuse RAES participant identity with a Shifter user, CTF
  participant/team, XDR `Agent`, `RangeInstance.agent_name`, entity role, or
  workspace role.
- Do not add `interactive_access` to provisioning node payloads, `RaesPlan`,
  `range_config`, backend capabilities, or the redacted runtime snapshot.
- Do not claim RAES participant-runtime support merely because portal access
  works.
- Do not reparse raw SDL or copy RAES semantic validators. A plain dict, type
  hint, dataclass construction, or ORM row is not boundary validation.
- Do not authorize from `account_ref`, account existence, OS family, role,
  image, Node.services, ACL, credential existence, private IP, or open port.
- Do not expose or reuse the reserved `raes` management account/key. An omitted
  account is unsupported, not permission to choose the first account or a
  default OS user.
- Do not silently fan one node declaration out across `count` instances or
  choose `#0`; both invent participant semantics.
- Do not use one username field when SSH and RDP bindings may name different
  accounts.
- Do not treat credential installation, VM success, TCP reachability, or a
  firewall allow individually as complete endpoint realization.
- Do not let a terminal READY result overtake or omit its realized access
  projection. Rank ordering alone is not proof that every required result
  exists.
- Do not restore direct provisioner writes or grants after the ADR-043 cutover,
  add a second result/event workflow, or persist raw provider outputs.
- Do not add a second secret naming scheme, endpoint repository, validator,
  exception tree, audit vocabulary, browser dialer, or firewall stack.
- Do not put private addresses, usernames, host keys, secret references/values,
  sidecars, or signed URLs into diagnostics, logs, metrics labels, audit detail,
  operation receipts, or public list responses unless an existing bounded
  response contract explicitly requires the non-secret field.

## Non-Goals And Boundaries

- No RAES participant episode/control/history implementation and no manifest
  profile change.
- No multi-agent actor-to-participant assignment in this issue; ambiguous
  policies fail closed at the declared seam.
- No multi-instance selector/fan-out semantics and no domain-account broker.
- No arbitrary service exposure, account provisioning model, generic remote
  access schema, VPN, IAP participant access, bastion, public guest address, or
  general-purpose proxy.
- No change to RAES provisioning/image/content/domain realization semantics,
  backend selection, AWS access behavior, or the cyberscript `RangeSpec` path.
- No replacement of browser SSH, Guacamole, Engine lifecycle state, the
  operation-result inbox, or provider Secret Manager.
- No implementation in this preflight.

## Required Evidence

- A real 2.0.0 SDL fixture proves compiler-resolved node/account/channel
  extraction without raw-SDL parsing; malformed references continue to fail in
  RAES before Shifter dispatch.
- Participant-invariant access succeeds, while different agent policies, an
  access-bearing agent beside an empty agent, omitted account, foreign/disabled
  account, auth-method mismatch, domain account, duplicate binding, unknown
  channel, dangling address, and `count > 1` all fail before cloud mutation.
- SSH and RDP use the declared account's credential reference and per-channel
  login name; the management secret/reference never appears in the binding,
  result, state projection, response, log, or diagnostic.
- The operation-input and operation-result parsers reject unknown fields,
  oversize collections, malformed refs/addresses/ports, missing/extra bindings,
  stale generations, conflicting replay, and terminal READY without complete
  realized state.
- Engine applies realized endpoints and READY atomically. Portal target listing,
  browser SSH, Guacamole SSH/RDP, pause/destroy, participant/owner revocation,
  and credential deletion reuse the #1349 tests and add RAES-native coverage.
- Effective NetworkPolicy and GCE firewall evidence proves only the dedicated
  access workloads reach approved private ports; non-access pods, arbitrary
  ports, public ingress, foreign/cross-range targets, and metadata/API paths
  remain denied.
- Logs, durable results, sidecars, audit rows, API/websocket envelopes, process
  argv/environment, and checked-in fixtures are checked for credential values,
  management refs, private endpoint leakage, and signed Guacamole URLs.
