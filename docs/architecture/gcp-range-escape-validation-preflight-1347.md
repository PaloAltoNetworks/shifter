# GCP Range Escape Validation Preflight

Issue: GitHub #1347, "Add live-fire escape validation suite for GCP ranges."

This is requirement-free pre-implementation guidance. The GitHub issue title,
body, and acceptance criteria are the shipping contract. This note does not
implement the suite and is not an implementation plan.

## Decision Boundary

#1347 is the executable evidence gate for the GCP VM range-cell boundary
defined by #1345 and ADR-039. It proves, from participant-controlled context
inside a live range cell, that the outer boundary fails closed before the range
is trusted for live-fire use.

The suite is not a scenario topology model, a new provisioner lifecycle, a new
public scenario DSL, or a replacement for rendered firewall tests. It consumes
existing platform-owned range bindings and scenario-declared probe entrypoints.
It may let a scenario add internal checks, but the core suite must never encode
Polaris, Docker, Kubernetes, Windows/DC, service names, fixed host order, or
specific internal ports as the platform contract.

## Architecture Decisions And Guardrails

- Treat the validation result as a closed, versioned, machine-readable
  security report. Each failed check must name the exact leaked boundary
  (`cross_range_private_ip`, `cross_range_dns`, `platform_pod_cidr`,
  `metadata_server`, `internet_egress`, etc.) and carry bounded sanitized
  diagnostics.
- Run core probes from an explicitly selected participant-controlled context
  inside the range cell. For a native VM this may be a declared participant
  access target; for Polaris it should be the participant container context,
  reached through a scenario-supplied adapter. The core suite receives an
  "execute this bounded command in participant context" seam, not topology.
- Drive targets from canonical platform and cell inventory: the closed
  `shared.range_cells` result, persisted range/subnet/instance bindings,
  platform Terraform outputs, and runtime env outputs. Do not scrape names from
  GCP, Kubernetes, or scenario files when the platform already has the binding.
- Keep static/rendered and live validation separate but comparable. Existing
  pure tests for firewall planning should catch an intentionally bad fixture;
  live probes should prove the deployed boundary from inside the cell.
- Support one-range and multi-range runs through the same result contract. A
  multi-range run uses at least one peer range as a negative target for private
  IP, DNS, and management-port reachability.
- Interpret internet egress through the ADR-approved policy, not a hardcoded
  "always denied" rule. `GCP_RANGE_EGRESS_ALLOW_CIDRS`,
  `GCP_RANGE_PRIVATE_GOOGLE_ACCESS`, Private Google Access VIP behavior, and any
  operator-approved egress can be expected-pass targets; everything else is an
  expected-fail target.
- Treat metadata-token access as sensitive even in tests. The probe may record
  whether metadata was reachable and whether credentials were useful, but it
  must not print, store, snapshot, or log token values or service-account JSON.
- Management ingress success remains owned by existing access-broker and
  post-deploy smoke paths. The escape suite verifies unapproved management
  reachability from range-controlled or peer-range-controlled sources fails.
- Scenario-declared services are scenario-specific checks. The core contract
  can merge their results into the same report shape, but it does not prescribe
  which services exist or should be reachable inside the cell.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Outer range-cell contract | `shared.range_cells`, `tests/shared/test_range_cells.py`, `gcp_range_cell_outputs.py` | Consume the closed request/result and non-secret member/access bindings. Do not invent another range identity or scenario topology schema. |
| Boundary-control model | `docs/architecture/gcp-range-cell-boundary-controls-preflight-1345.md`, `gcp_range_cell_plan.py`, `gcp_range_cell_resources.py`, `tests/test_gcp_range_cells.py`, `tests/test_gcp_range_cell_resources.py` | Add leak fixtures and assertions beside the pure GCE plan/resource tests before relying on live probes. |
| Provider-neutral substrate | ADR-039, `docs/architecture/provider-neutral-range-substrate.md`, `range_terraform_runner.py`, `range_ops.py`, `aces_range_ops.py` | Keep validation evidence adjacent to lifecycle readiness; do not add a GCP-specific public status enum or controller. |
| Platform network inventory | `platform/terraform/gcp/modules/platform-core/outputs.tf`, `platform/terraform/gcp/environments/gcp-dev/outputs.tf`, `scripts/gcp/render_runtime_env.py` | Read platform/range network CIDRs and endpoint identities from Terraform/runtime outputs. Add non-secret outputs if needed; do not hardcode pod, service, node, portal, GKE, or GDC addresses. |
| Runtime config gates | `load_gce_range_cell_config`, `_GCP_PROVISIONER_ENV_KEYS`, `platform/k8s/gcp/base/validatingadmissionpolicy-provisioner-jobs.yaml`, runtime inventory tests | Any new env or provisioner command must pass the renderer, engine allowlist, sensitive-env split, and GKE admission policy deliberately. |
| Operator smoke workflow | `cms/post_deploy_smoke`, `run_post_deploy_smoke`, `scripts/post_deploy_smoke/README.md` | Reuse the ownership, provision-wait-probe-cleanup, and management-command conventions. Change probe direction and report shape; do not fork range lifecycle. |
| ACES/conformance evidence | `shared.aces.runtime_target`, `tests/shared/aces/test_backend_conformance_gate.py`, `tests/shared/aces/test_participant_runtime_conformance_gate.py` | Follow the non-vacuous conformance pattern: one honest pass, one mutated/bad fixture that fails, bounded sanitized diagnostics. |
| Errors and logs | ADR-039 failure codes, `shared.cloud.exceptions`, `shared.api.errors`, `shared.errors`, `shared.log_sanitize`, provisioner `log_redact` | Emit classified, bounded diagnostics and safe fingerprints. Raw command output, provider errors, token responses, and credentials do not cross report/log/API boundaries. |
| Secret handling | `shared.cloud.sensitive_env`, GCP task-runner per-Job Secrets, `gcp_guest_secrets`, `gcp_range_vertex_creds`, `engine.secrets` | Resolve credentials only through existing access boundaries. Persist references and non-secret evidence only. |

## Cross-Cutting Layers The Design Must Pass

- Auth and ownership: only an operator/CI context that already can provision or
  inspect the target ranges may launch the validation. Participant inputs must
  not choose arbitrary peer ranges, platform CIDRs, or cloud endpoints. Access
  to the participant probe context continues through existing CMS/Engine access
  checks and secret resolution.
- Scenario shape: scenario YAML, legacy `RangeSpec`, ACES plans, and
  participant-access declarations keep their existing validators. The core
  suite consumes only the declared probe entrypoint and platform-owned bindings;
  scenario-specific checks are additive and use the same report envelope.
- Range-cell parser/result: `validate_gcp_vm_range_cell_request` and
  `validate_gcp_vm_range_cell_result` remain the trust boundary for request,
  membership, and logical access. Do not use raw provider inventory as a more
  trusted source than the closed result without reconciling it to the result.
- Config validators: new probe targets or knobs must enter through existing
  typed config or non-secret Terraform/runtime outputs. If implementation adds a
  provisioner subcommand or env key, update `engine.ecs`,
  `scripts/gcp/render_runtime_env.py`, runtime inventory tests, and GKE
  admission together.
- OS/process exposure: command argv may carry a request id, range id, suite id,
  or a path to a bounded input file. Do not pass token values, kubeconfigs,
  service-account JSON, private keys, raw topology JSON, or long target lists in
  argv, shell strings, workflow output, or process titles. Use argv arrays and
  bounded timeouts for every probe.
- Probe runtime: probes run unprivileged unless a scenario explicitly owns a
  privileged internal check. The core suite must not disable firewalls, mutate
  routes, install permanent agents, alter DNS configuration, or leave listeners
  behind in the range.
- Metadata surface: probes may request metadata only to classify the boundary.
  They must redact token bodies, service-account emails when needed with
  fingerprints, and any returned credential material. A reachable metadata
  server is a failure only when it exposes useful credentials or violates the
  scenario's approved participant context.
- Network policy surface: cross-range private IP, cross-range DNS, platform
  namespace/pod/service/node CIDRs, GKE/GDC API, portal-private endpoints,
  metadata, internet egress, and management ingress are separate boundaries in
  the report. Do not collapse them into one "network failed" result.
- Error envelope and events: if the report is exposed through API or readiness,
  use existing safe API envelopes and ADR-039 style stable codes. The operator
  report may include precise destination labels and sanitized observations, but
  not raw stdout containing secrets or provider payloads.
- Observability: log request id, range id, suite id, boundary code, check id,
  status, elapsed time, and sanitized fingerprints. Store detailed evidence as
  bounded non-secret artifacts; never store packet captures or command logs by
  default if they can contain tokens, hostnames from private DNS, or secrets.

## Scenario-Neutral Report Contract

The code-level contract should be a platform-native closed schema under
`shared` if the report crosses process boundaries. It should contain:

- suite identity: contract, version, suite id, start/end timestamps, invocation
  mode, request/range ids, and peer request/range ids when present;
- policy inputs: non-secret fingerprints or values for the range-cell result,
  platform inventory version, approved egress policy, and approved management
  sources;
- checks: stable id, boundary code, source context, destination class,
  expected outcome, observed outcome, status (`pass`, `fail`, `skip`, or
  `not_applicable`), elapsed time, and bounded diagnostic;
- scenario section: optional scenario-owned checks using the same check record
  shape and a `scope` that distinguishes `core` from `scenario`;
- verdict: `passed` only when every required core check and required
  scenario-supplied check passes.

Skips must be explicit and narrow. For example, "no peer range supplied" may be
valid for a one-range run but invalid for the two-or-more-range gate. "No
participant-controlled probe context" is not a pass for a live-fire readiness
gate.

## Extensibility Seam

The durable seam is the probe launch adapter plus the boundary-target inventory:

- probe launch adapter: SSH target, container exec inside a scenario host,
  Windows command runner, future ACES participant-runtime runner, or another
  scenario-owned mechanism, all returning the same bounded probe result;
- boundary target inventory: peer range member IPs, platform network CIDRs,
  private service endpoints, metadata names/IPs, egress canaries, and
  management ports sourced from platform outputs and range-cell results;
- policy profile: event/live-fire policy now, with future profiles for
  zero-egress, VPC-per-range, secure tags/firewall policy, or a different GCP
  region without rewriting scenario checks.

The next expected variation is validating an ACES-native GCE range and a legacy
Polaris range with the same core suite. That should require a new probe launch
adapter or scenario check provider, not edits to the report schema, platform
network inventory, or lifecycle state machine.

## Gotchas And Anti-Patterns

- Do not make Polaris the suite. Polaris can prove reference adoption, but the
  reusable core must pass for differently composed range cells.
- Do not run probes from the provisioner pod or portal namespace and claim they
  prove participant containment. The core evidence must originate from inside
  participant-controlled range context.
- Do not accept target IPs, CIDRs, hostnames, or peer range ids from a
  participant-controlled request. Operator/CI selects ranges; platform state
  resolves targets.
- Do not treat DNS answers as harmless. A cross-range, platform, pod, service,
  node, GKE/GDC API, metadata, or portal-private answer is useful route evidence
  even if a subsequent TCP connect times out.
- Do not print metadata tokens, service-account JSON, private keys, passwords,
  kubeconfigs, headers, cookies, or full HTTP bodies into JSON reports, logs,
  test snapshots, or CI annotations.
- Do not add a duplicate exception hierarchy, validation package, status enum,
  lifecycle controller, repository, secret adapter, or cloud inventory schema.
- Do not make live probes depend on arbitrary public internet hosts. Egress
  canaries should be operator-owned or explicitly configured, and the expected
  result must come from the active egress policy.
- Do not use long sleeps as proof. Every network probe needs bounded timeout,
  bounded retries, and a deterministic failure reason.
- Do not mutate the range to test containment: no temporary firewall relaxations
  in the live environment, no route edits, no disabling guest firewall, and no
  broad debug service opened "just for validation."
- Do not mark a range READY for live fire solely because provisioning and
  management access succeeded. Escape validation is a separate readiness gate.

## Non-Goals And Boundaries

- No implementation in this preflight note.
- No formal Ground Control requirement; issue #1347 is the authoritative
  contract.
- No redesign of GCE range-cell firewalling, backend selection, GDC/GKE range
  paths, ACES participant runtime, Guacamole, Identity Platform, NGFW, or AWS
  range isolation.
- No public scenario DSL for validation topology, no standard internal service
  catalog, and no platform-owned taxonomy for VM/container/DC/Kubernetes
  internals.
- No guarantee that the GCP shared-VPC posture is stronger than VPC-per-range.
  The suite proves the selected posture at the boundaries it probes; it does not
  change the isolation architecture.
- No storage of secret-bearing evidence or raw packet captures as default CI
  artifacts.

## Required Future Evidence

- A static or fixture test intentionally adds a cross-range allow rule and the
  suite or plan checker fails with the exact leaked boundary.
- One-range and two-or-more-range invocations produce the same closed report
  shape; the multi-range gate fails if peer-range checks are skipped.
- Polaris, as reference live-fire scenario, invokes the suite before event-ready
  status, but the core suite remains scenario-neutral.
- At least two materially different range compositions pass the core suite
  without platform code branching on scenario id, role, OS, container, Windows,
  DC, Kubernetes, or service topology.
- Failure diagnostics name the leaked boundary and destination class while
  remaining bounded, single-line, and free of secret-shaped substrings.
- Touched architecture, platform, workflow, Kubernetes, Terraform, and
  `shifter_platform` surfaces still pass the repo-required ADR guard and the
  stack-native checks for the files changed.
