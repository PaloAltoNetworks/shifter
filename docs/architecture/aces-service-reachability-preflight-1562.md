# ACES Authored Service Reachability Preflight

Issue: GitHub #1562, "feat: open reachability firewalls for authored ACES
service ports."

Status: pre-implementation architecture guidance. This note and ADR-032-R8 do
not change the ACES parser, serialized plan, GCE firewall plan, cloud resources,
feature flag, or tests. The issue is the shipping contract for this
requirement-free run.

## Boundary And Decision

An ACES `Node.services` entry is layer-4 transport exposure intent. It is not
informational-only metadata, but it also does not install or start a listener,
authorize a participant, publish a browser endpoint, or override an authored
ACL. The GCE backend must therefore derive ingress policy for validated service
ports while retaining the existing default-off
`SHIFTER_ACES_NATIVE_PROVISIONING` posture.

For GCE, a service is reachable only from concrete CIDRs of networks declared
in the same compiled range. Do not use `0.0.0.0/0`, platform/portal CIDRs,
operator CIDRs, the stable range-VPC CIDR, or another range as an implicit
source. The destination remains the existing per-node network tag, so a service
on one node does not open the port on every VM in the range. A future
participant gateway or external publication feature needs its own explicit,
authorized source/audience contract; `services` alone is not that contract.

Precedence is a security invariant, not an incidental integer choice:

1. the existing management-plane allow remains highest precedence so authored
   policy cannot sever provisioner SSH/RDP reachability;
2. authored node ACL rules take precedence over service-derived allows; and
3. service-derived allows take precedence over the implied ingress deny.

The implementation must use non-overlapping priority ordering or a checked
priority allocator. It must fail before cloud mutation when the authored ACL
count or provider limits make that ordering unrepresentable. Do not depend on
same-priority GCP allow/deny tie behavior.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Authoring shape | ACES `aces_sdl.nodes.ServicePort` and the compiled `ProvisioningPlan` payload at `spec.node.services` | Do not add a Shifter authoring schema or CMS serializer. The SDL already validates authored ports and duplicate bindings/names. |
| Platform transport | `shared.aces.runtime_target.serialize_provisioning_plan`, ADR-032-R3/R7, `engine.models.Range.range_config` | Carry the compiled payload verbatim under the existing versioned envelope. Do not add a service DTO to dispatch, persistence, sidecars, or events. |
| Provisioner trust boundary | `aces_plan.parse_plan`, `AcesPlanNode`, `AcesPlanError`, and the bounded process-local projection allowed by ADR-032 | Repeat shape and supported-protocol checks here because the provisioner is a separate deployable. Keep any service value object beside the existing plan types. |
| Reference semantics | Public `aces_backend_libvirt.realization.interpret_provisioning_plan` and its `DomainSpec.services` result | Compare normalized valid service extraction through the public pure interpreter; do not import private `_service`/`_services` helpers or ship the reference backend in the provisioner. |
| Firewall policy | `aces_gcp_firewall`, `build_acl_firewalls`, `node_tag`, `acl_cidr_lookup` | Put service translation beside ACL translation and target the existing node tag. Do not create a second GCE policy module. |
| Neutral GCE plan | `aces_gcp_plan._all_firewalls`, `gcp_range_cell_plan._firewall_plan`, `FirewallPlan` | Append deterministic service-derived `FirewallPlan` values to the existing plan. Reuse the resource shape and base management/egress posture. |
| Provider rendering/lifecycle | `gcp_range_cell_resources.firewall_resource`, `gcp_range_cells._ensure_firewall` / `_delete_resource`, `aces_gcp_apply` | Reuse Compute API rendering, operation waits, cleanup, reverse-order destroy, and fingerprinted resource logging. |
| Configuration | `GCERangeCellConfig`, `load_gce_range_cell_config`, `config/_aces_settings.py`, `config/env-manifest.json` | Add no setting, env variable, Terraform input, or service-port allowlist. Service intent comes from the compiled plan; source scope comes from that plan's concrete network CIDRs. |
| Errors and observability | `AcesPlanError`, `AcesGceFirewallError`, `log_redact.safe_log_value` / `safe_log_fingerprint`, ACES operation/status events | Fail with bounded structural messages naming a node address and service index/field, not raw payloads. Keep provider names fingerprinted and lifecycle correlation keyed by request id. |
| Architecture enforcement | `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard` | Keep `aces_*` imports in `shared.aces`/tests and the provisioner dependency-light. Do not weaken existing checks. |

## Cross-Cutting Layers The Design Must Pass

- **SDL/parser policy:** ACES Pydantic parsing first bounds a concrete port to
  `1..65535` and rejects duplicate concrete protocol/port bindings and duplicate
  non-empty names. This remains the authoring validator. The implementation
  must not reproduce it in CMS or `shared`.
- **Compile and RuntimeTarget shape:** the ACES processor materializes services
  in `payload.spec.node.services`; `ShifterProvisioner.validate()` and `apply()`
  retain the existing capability and topology gates, and serialization remains
  JSON-safe and verbatim. No service-derived cloud decision belongs on this
  platform side.
- **Persisted transport:** `kind`, `contract_version`, and `aces_sdl_version`
  continue to guard `range_config`. Adding service extraction does not justify a
  transport version bump because the payload is already carried; changing the
  envelope shape would.
- **Provisioner shape check:** `parse_plan` must require `services` to be a
  sequence of mappings and each realized entry to have a real integer port
  (never `bool`/float), supported normalized protocol, and only bounded scalar
  metadata. Malformed/unsupported entries must raise `AcesPlanError`; silently
  dropping them or coercing an unknown protocol to TCP is not fail-closed.
- **Network policy:** every source CIDR must come from the current parsed
  `AcesPlan.networks` and must already satisfy the GCE subnet/IP validation path.
  Deduplicate sources deterministically and reject missing/unusable CIDRs. Never
  turn an unresolved source into the ACL helper's authored "any" sentinel.
- **GCP provider layer:** render through `FirewallPlan` and
  `firewall_resource`; target `node_tag(range_id, node.address)`. Deterministic
  provider names must derive from stable range/node identity, not raw service
  names, descriptions, scenario ids, or ports.
- **Stable VPC policy:** Terraform's range-VPC deny baseline in
  `platform/terraform/gcp/modules/range/vpc/main.tf` remains unchanged. Runtime
  service rules are narrower, range-owned exceptions above that deny; they do
  not broaden `range_provisioner_ports` or operator access.
- **OS/guest layer:** GCE firewall admission does not prove a process is
  listening and must not mutate Linux nftables/iptables, Windows Firewall,
  cloud-init, startup scripts, or service managers. Guest service realization
  and readiness are separate concerns.
- **Auth surface:** no endpoint, permission, participant binding, Guacamole
  token, terminal scope, or range-ownership check changes. Network reachability
  is not product authorization.
- **Secret surface:** service names, protocols, and ports are non-secret intent,
  but raw plan bodies and provider responses still stay out of logs, snapshots,
  events, errors, argv, and environment overrides. No credential or token is
  introduced.
- **OS/process exposure:** dispatch remains structured argv
  `aces-range provision --request-id <uuid>` with the plan DB-backed. Do not put
  a service list or serialized firewall policy in argv, shell fragments, or env.
- **Error envelope:** structural rejection remains `AcesPlanError` /
  `AcesGceFirewallError`, then the existing provisioner failure/status path.
  Messages must be bounded and sanitized before logs/sidecars; never interpolate
  the service mapping, description, plan body, or provider exception body.
- **Lifecycle/persistence:** apply must create service firewalls before
  instances, clean them up after partial failure, and reconstruct identical
  names during destroy. No model, migration, repository, sidecar kind, event
  type, or retention change is needed.

## Extensibility Seam

The seam is the normalized, process-local service projection on `AcesPlanNode`
plus a pure service-firewall builder whose source CIDRs and priority are explicit
arguments. Keep service normalization ordered like the reference backend
(`protocol`, `port`, `name`) and aggregate equivalent ports by node/protocol when
that reduces GCP rule count without changing semantics.

That seam permits one reasonable future change—an explicit service audience or
participant-access gateway—to supply a different validated source set without
editing the ACES transport, CMS/engine persistence, provider renderer, or node
tag contract. Do not infer an audience from service name, description, port,
node image, scenario id, or currently unsupported extra fields.

## Regression Evidence Expectations

- A platform-side parity test builds one public ACES `ProvisioningPlan`, passes
  it to public `aces_backend_libvirt.realization.interpret_provisioning_plan`
  and the standalone Shifter provisioner reader, and compares normalized valid
  service tuples. Private reference helpers are not an oracle.
- Parser negatives cover non-sequence services, non-mapping entries, boolean,
  fractional, zero, and out-of-range ports, unsupported protocols, and duplicate
  normalized bindings. Rejection happens before `build_aces_range_cell_plan`.
- Firewall tests prove TCP defaulting, UDP preservation, deterministic ordering,
  node-tag targeting, deduplicated same-range sources, no world/platform source,
  ACL-over-service precedence, and management-over-ACL precedence.
- Plan/apply/destroy tests prove count fan-out shares the node tag without
  duplicating policy per instance, service rules use the existing Compute
  renderer, partial failure cleans them up, and reconstructive destroy names
  exactly the same rules.
- A cross-boundary fixture with at least two authored networks proves a declared
  service port is admitted from another network in the same range while an
  undeclared port, another range CIDR, and a matching authored deny remain
  blocked. A structural firewall-plan assertion alone is not live reachability
  evidence when the cutover gate is evaluated.
- Existing no-service plans, ACL-only plans, base management rules, default-off
  launch behavior, bounded diagnostics, and ACES conformance remain unchanged.

## Whole-Repo Scope

Implementation must evaluate changes against:

- `docs/adr/index.yaml` ADR-008, ADR-031, and ADR-032;
- `docs/architecture/aces-cutover-evidence-1264.md`,
  `aces-provisioning-plan-transport-preflight-1522.md`, and
  `aces-backend-manifest-realizability-preflight-1563.md`;
- ACES `ServicePort`, compiler output, and public libvirt realization behavior
  through the pinned dependency (test-only reference oracle);
- `shifter/shifter_platform/shared/aces/runtime_target.py` and
  `tests/shared/aces/test_plan_provisioner_parity.py`;
- `shifter/engine/provisioner/aces_plan.py`, `aces_plan_types.py`,
  `aces_gcp_firewall.py`, `aces_gcp_plan.py`, `aces_gcp_apply.py`,
  `gcp_range_cell_plan.py`, `gcp_range_cell_resources.py`, and
  `gcp_range_cells.py`;
- provisioner parser, firewall, plan, apply, destroy, and resource-renderer
  tests under `shifter/engine/provisioner/tests/`;
- `platform/terraform/gcp/modules/range/vpc/main.tf` and
  `platform-core/variables.tf` as unchanged stable-policy constraints;
- `config/_aces_settings.py`, `config/env-manifest.json`, runtime inventory,
  engine task env forwarding, and provisioner CLI as unchanged config/process
  boundaries; and
- `.importlinter`, `scripts/check_layer_imports/**`, and
  `scripts/adr_guard/**`.

## Gotchas And Anti-Patterns

- The reference libvirt interpreter normalizes valid named services, but its
  current private helper silently drops some malformed/unnamed shapes and
  coerces unknown protocols to TCP. Do not copy those fail-open details. Compare
  valid behavior through the public interpreter and make Shifter's separate
  trust boundary stricter and explicit.
- An authored service is an allowed transport surface, not proof of listener
  readiness. Do not mark a range ready based only on a firewall object or add a
  fake health listener.
- Do not interpret `services` as a closed list of every reachable port. The
  existing base same-subnet allow and management rule remain distinct policy.
- The current base same-subnet ingress and first ACL rule both use priority
  `1000`; later ACL entries use larger numbers. That existing overlap can make a
  later same-subnet deny lose to the base allow. Do not extend that collision to
  service rules, and do not claim service/ACL precedence without tests covering
  all simultaneously matching rules. A broader ACL-priority repair should be
  separately bounded if it changes existing no-service behavior.
- `_ensure_firewall` is create-if-missing, not a policy reconciler. New service
  rules need new deterministic names; changing the body of an existing rule
  does not update live state. Do not disguise an update as idempotent creation.
- One firewall per node instance wastes quota when node `count` fans out; all
  instances already share the node tag. Do not multiply identical rules by
  count.
- Do not key resource identity on an optional or hostile service name, and do
  not log raw names/descriptions merely to aid debugging.
- Do not source from every subnet in the shared VPC. Only the current compiled
  plan's concrete networks are in-range sources; shared-VPC membership is not a
  trust relationship.
- Do not add service ports to `PORTAL_NETWORK_CIDRS`,
  `range_provisioner_ports`, Terraform variables, env manifests, task env,
  Kubernetes policy, guest firewall commands, or a database allowlist.
- Do not duplicate ACES `ServicePort` in `shared`, CMS, engine services, a
  migration, API schema, or sidecar. A small provisioner value object is a
  realization projection, not a new contract.
- Do not import `aces_backend_libvirt` into the production provisioner or call
  its private `_service`/`_services` functions from tests.
- Do not open egress for a declared listener. Ingress service exposure and the
  existing range-egress policy are independent directions and concerns.

## Non-Goals

- No implementation, cloud mutation, or live reachability probe in this
  preflight.
- No guest package/service installation, startup, readiness, DNS, load
  balancing, public IP, NAT/port forwarding, browser publication, or participant
  access-channel feature.
- No change to authored ACL vocabulary, base same-subnet reachability, stable
  Terraform range-VPC policy, range egress, or management ports except the
  minimum precedence work required to keep service allows subordinate.
- No new ACES schema, capability term, manifest profile, dependency version,
  transport envelope, API/UI contract, database model/migration, sidecar/event,
  setting/env variable, workflow, Terraform input, Kubernetes resource, or
  secret.
- No change to the default-off feature flag, ACES cutover, cyberscript path,
  CMS/engine service boundaries, request-id dispatch, or persisted plan.

## Validation For This Architecture Change

```bash
python3 scripts/adr_guard/adr_guard.py --files docs/adr/index.yaml docs/architecture/aces-service-reachability-preflight-1562.md --level fast
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
