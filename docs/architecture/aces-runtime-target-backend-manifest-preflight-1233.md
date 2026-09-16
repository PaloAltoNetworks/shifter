# ACES RuntimeTarget and Backend Manifest Preflight

Issue: #1233, "04 - ACES migration: design Shifter ACES RuntimeTarget and backend manifest"

Implementation follow-up: #1262, "ACES migration: implement Shifter
RuntimeTarget adapter over engine services"

Status: pre-implementation architecture guidance. This note does not implement
the adapter, manifest, conformance runner, or live validation gate.

## Decision

Shifter's first ACES backend claim is `provisioning-only`.

The initial backend manifest must declare a provisioner capability set and the
contracts required by the ACES `provisioning-only` backend profile:

- `backend-manifest-v2`
- `operation-receipt-v1`
- `operation-status-v1`
- `runtime-snapshot-v1`

The first slice must not declare ACES `orchestrator`, `evaluator`, or
`participant_runtime` capabilities. Shifter has existing orchestration,
experiment, CTF, participant, Mission Control, status, and observation surfaces,
but they are product-specific contracts today. They are not ACES workflow,
evaluation, or participant-runtime protocol implementations until a later slice
adds the required ACES plan/result/history/lifecycle contracts and conformance
evidence.

The RuntimeTarget boundary is an adapter around existing Shifter range creation
and provisioning. It maps an ACES provisioning/runtime model into Shifter's
existing `RangeSpec`/`RequestSpec` path, then hands off through the current
CMS, engine, task-runner, and provisioner services. It must never call
Terraform, SSM, SSH, Docker, AWS, or GCP directly from ACES-facing CMS/API code.

Backend-owned realization stays backend-owned. Terraform modules and variables,
SSM/bootstrap commands, GCP/AWS provider choices, images, machine sizes,
provider executors, subnet allocation, NGFW attachment, secret lookup, and
Shifter-specific resource realization are implementation details of the Shifter
backend, not authored ACES scenario semantics.

LilRAE (formerly APTL) is useful prior art only at the pattern level: it made
the backend manifest
the source of truth, created RuntimeTarget components from that manifest, and
gated cutover with target conformance plus a published `aces conformance backend`
run. Shifter must apply that pattern through its portal/CMS/engine/provisioner
boundaries rather than copying LilRAE's former local Docker Compose backend
shape.

## Capability Mapping

| ACES capability | Shifter incumbent | First-slice claim |
| --- | --- | --- |
| Provisioner | `cms.scenarios.hydrator`, `RangeSpec`, `cms.services.create_range`, `engine.services.create_range`, `engine.ecs`, `shifter/engine/provisioner` | Claim only what current range provisioning can validate and realize. |
| Orchestrator | Provisioner setup orchestrator, CMS experiments, CTF flows | Do not claim. Guest bootstrap and product workflows are not ACES workflow protocol results/history. |
| Evaluator | CTF flag/scoring services, experiment status/artifacts | Do not claim. These lack ACES `EvaluationPlan`, result envelope, and history stream contracts. |
| Participant runtime | CMS participant ranges, Mission Control terminal/session access | Do not claim. These do not expose ACES initialize/reset/restart/terminate lifecycle state and history. |
| Observation | Engine/CMS range status, range event outbox, provisioned state | Expose only provisioning status/snapshot projections required by `provisioning-only`. |

## Canonical Incumbents to Reuse

- Scenario/catalog entry: `cms.scenarios.loader`, `cms.scenarios.registry`,
  `cms.scenarios.hydrator`, `cms.models.Scenario`, and
  `cms.models.ScenarioMetadata`.
- Service handoff: `cms.services.create_range`, `engine.interpreter`, and
  `engine.services.create_range`.
- Persisted specs and status: `shared.schemas.persistence.wrap_persisted_spec`,
  `engine.models.Range`, `engine.models.Request`, `engine.models.Instance`,
  `engine.models.Subnet`, CMS `RangeInstance`, and `RangeEventOutbox`.
- Runtime dispatch: `engine.ecs` and `shared.cloud` task-runner factories.
- Provisioning realization: `range_terraform_runner`, `terraform_ops`,
  `terraform_base`, `provisioner_db`, setup orchestrators, and provider
  executors.
- Auth and API envelopes: `shared.auth`, `cms.api.permissions`,
  `shared.api_tokens.scopes`, `shared.api.errors`, `shared.errors`, and
  `cms.exceptions.CMSError`.
- Logging and audit: `shared.log_sanitize`, provisioner `log_redact`,
  `risk_register` audit logging, and transactional range event outbox events.
- Import enforcement: `.importlinter`, `scripts/check_layer_imports`, and
  `scripts/adr_guard`.

Do not introduce parallel schemas, validators, exception hierarchies, event
pipelines, cloud dispatchers, Terraform workspace management, secret routing, or
status stores for the ACES path.

## #1262 RuntimeTarget Adapter Guardrails

The #1262 adapter must be a translation boundary, not a second launch path. It
may translate validated ACES RuntimeTarget/provisioning input into Shifter
`RangeSpec` / `RequestSpec` objects, but it must then hand off through the
existing catalog, hydrator, `cms.services.create_range`,
`engine.interpreter`, `engine.services.create_range`, and request-id
provisioner CLI path. CMS/API code facing ACES must not call `engine.ecs`,
`shared.cloud`, Terraform, SSM, SSH, Docker, AWS, or GCP directly.

That full hand-off chain is the eventual path across the #1262-#1264 arc, not a
single-PR deliverable. The #1262 translation-boundary slice lands the adapter
and proves it *emits a valid wrapped Shifter spec through the incumbent
hydration path* (`hydrate_scenario` -> `wrap_persisted_spec`, the same spec
`cms.services.create_range` builds before it persists and dispatches) while
rejecting unsupported capability claims. Binding the live launch context (user,
agents, launchable catalog scenario) and dispatching through
`cms.services.create_range` / `engine.services.create_range` / the request-id
provisioner CLI is the #1264 live-validation slice; catalog launchability
(`_LAUNCH_ADAPTER_CONTRACT_PROFILES`) stays fail-closed until then. This keeps
the guardrail intact (translation only; no direct infra calls) without folding
#1264's live provisioning into the adapter PR.

Unsupported ACES capabilities are a boundary error. The first adapter slice is
`provisioning-only`; orchestrator, evaluator, participant-runtime, direct cloud
realization, provider-variable authoring, runtime command execution, and raw
snapshot/history requests must fail before Shifter spec hydration. Failures use
existing CMS/service exceptions and DRF error envelopes, with sanitized
diagnostics, not ACES-specific exception hierarchies or silent no-op behavior.

The adapter output contract is Shifter's existing shared schema contract. Do
not add duplicate `RangeSpec`, `RequestSpec`, status, lifecycle, credentials,
or provider DTOs under an ACES package. If ACES persistence or projection
metadata is needed, keep it in the ACES sidecar/profile surfaces from the
operation-status preflight; runtime truth remains the wrapped Shifter specs and
engine/provisioner models.

Boundary tests for #1262 should prove the adapter emits a valid wrapped
Shifter spec through the incumbent service path and rejects unsupported
capability claims without touching Terraform, task runners, provisioner
modules, cloud SDKs, or secret stores from the ACES-facing layer.

## Cross-Cutting Gates

The implementation must pass each cross-cutting layer below:

- Auth surface: any CMS/API endpoint for manifests, conformance, or ACES launch
  must reuse the existing session/API-token permission model and exact CMS
  authoring scopes. UI hiding is not authorization.
- ACES contract surface: use the ACES contract/profile/manifest models and
  conformance runner as the source of truth. Do not reimplement backend profile
  validation with local string checks.
- Scenario input surface: legacy YAML still goes through slug/path containment,
  `yaml.safe_load`, and Pydantic template validation. ACES packages enter
  through the package/catalog boundary from the package preflight, with an
  explicit profile discriminator rather than YAML shape detection.
- Persistence surface: persisted range/request specs must remain wrapped and
  validated through `wrap_persisted_spec`, `engine.interpreter`, and the existing
  engine/CMS models. Raw ACES payloads must not become an alternate source of
  persisted runtime truth.
- Runtime dispatch and OS exposure: runtime operations must continue through
  `engine.ecs` structured argument lists and provisioner CLIs keyed by validated
  request IDs. No request-supplied shell fragments, tokens, Terraform variables,
  or provider credentials may appear in argv, logs, snapshots, docs, or API
  errors.
- Secret handling: use `shared.cloud` secret stores, `shared.cloud.sensitive_env`,
  provisioner secret lookup, and existing encrypted-field handling. The backend
  manifest and ACES snapshots disclose capabilities and state, not secrets.
- Error envelopes: user/API errors must use existing safe error classification
  and envelopes. Raw ACES parser, conformance, Terraform, cloud provider, SSM,
  SSH, or Docker errors stay in sanitized diagnostics/logs.
- Logging/observability: portal logs use `shared.log_sanitize`; provisioner logs
  use `log_redact`; outbox events carry IDs and statuses, not embedded specs or
  secrets.
- Import and architecture gates: ACES imports remain behind `shared` and the
  established CMS/engine service seams. Import-linter, layer import checks, and
  ADR guard remain hard gates.
- Platform policy: range egress, isolation, placement, and provider constraints
  from ADR-017, ADR-020, ADR-021, and ADR-024 are backend constraints to
  disclose in capabilities or realization support, not scenario-authored escape
  hatches.

## Extensibility Seam

The canonical seam is an explicit backend profile/capability discriminator at
the manifest and adapter boundary. The first value is `provisioning-only`; later
values may add orchestration, evaluation, or participant runtime only when the
corresponding ACES protocols, result/history contracts, and conformance gates
exist.

Provider/runtime variation belongs behind existing backend-owned factories:
`shared.cloud`, engine task runners, provisioner provider runners, and backend
manifest realization support. A future AWS, GCP, local, or additional ACES
profile variant should add a manifest/adapter capability branch, not new
scenario fields that leak Terraform, SSM, SSH, image, subnet, or provider
details into authored scenario semantics.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md` and
  `docs/architecture/aces-migration-parity-inventory.yaml`
- the ACES scenario/catalog preflight notes for issues #1231 and #1232
- `shifter/shifter_platform/cms/scenarios/**`
- `shifter/shifter_platform/cms/models/scenarios.py`
- `shifter/shifter_platform/cms/services/**` and any CMS/API endpoints
- `shifter/shifter_platform/shared/**`
- `shifter/shifter_platform/engine/**`
- `shifter/engine/provisioner/**`
- provider-owned `platform/terraform/**` and `platform/k8s/**` only when
  realization changes require them
- `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard`, and ADR
  registry/exception files when guardrails change

## Gotchas and Anti-Patterns

- Do not equate Shifter's setup orchestrator with ACES `Orchestrator`.
- Do not equate CTF scoring or experiments with ACES `Evaluator`.
- Do not equate Mission Control participant access with ACES
  `ParticipantRuntime`.
- Do not create an ACES-only range lifecycle, status enum, event bus, or
  persistence model.
- Do not store raw ACES SDL or package payloads as executable `Scenario.definition`.
- Do not infer launchability or profile from YAML shape, Polaris branch names,
  file paths, or scenario IDs.
- Do not let ACES scenario semantics author provider details such as Terraform
  variables, SSM documents, SSH keys, image IDs, instance types, GCP VM Runtime
  profiles, CIDR blocks, or NGFW attachment choices.
- Do not weaken existing import, ADR, Terraform, Kubernetes, actionlint,
  secret-scanning, or live-cloud guardrails to make the ACES path pass.

## Non-Goals

- No wholesale provisioner rewrite in the first slice.
- No ACES orchestrator/evaluator/participant runtime claim in the first slice.
- No replacement of CMS catalog, range creation, engine services, provisioner
  runner, Terraform workspace management, or cloud provider factories.
- No user-authored cloud/provider realization semantics.
- No migration of Shifter product-specific CTF, experiment, or Mission Control
  contracts into ACES without separate design and conformance evidence.

## Follow-Up Implementation Issues

The implementation track should have separate issues for:

- #1261: publish the Shifter `provisioning-only` backend manifest and profile
  claim.
- #1262: implement the RuntimeTarget/provisioner adapter over the existing
  CMS/engine/provisioner path.
- #1263: add the ACES backend conformance gate and sanitized diagnostics.
- #1264: add live validation that proves the adapter path provisions and
  reports a snapshot through the normal Shifter backend.
