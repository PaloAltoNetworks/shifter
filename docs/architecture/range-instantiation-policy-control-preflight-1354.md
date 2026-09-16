# Range Instantiation Policy Control Preflight

Issue: GitHub #1354, "Add range instantiation policy control for live-fire
backends."

This is requirement-free pre-implementation guidance. The issue title, body,
and acceptance criteria are the shipping contract. This note does not implement
the policy and is not an implementation plan.

## Decision Boundary

ADR-030 already decides the security posture: a normal Shifter range is
live-fire, and Kubernetes/GDC VM Runtime is not an approved participant
containment boundary. Issue #1348 added the current GCP live-fire gate, and
issue #1666 made its admitted backend and purpose write-once Engine ownership
state. Issue #1354 generalizes that incumbent policy seam to trusted creation
contexts; it must not introduce a parallel selector, scenario schema, lifecycle
workflow, or provider exception tree.

Keep these concepts separate:

- `RangeSource` is server-derived product provenance and active-range
  partitioning (`mission_control` or `ctf`). It is not a security purpose.
- A scenario's `scenario_type="demo"` describes authored/catalog content. A
  normal Mission Control demo still lets a user or agent execute arbitrary
  activity and is therefore `live_fire`.
- An instantiation purpose is trusted workflow authority minted by a dedicated
  server/operator path. The closed purposes must distinguish normal live-fire,
  deterministic product-demo/BAS, and operator-validation launches.
- `CLOUD_PROVIDER` selects a deployment backend bundle. `GCP_RANGE_BACKEND`
  selects a GCP realization backend. Neither grants a purpose.
- Policy admission says a selected backend may be used for a purpose.
  Realizability says that backend can realize the validated legacy/ACES
  artifact. Admission is not realizability or event-readiness evidence.
- The persisted Engine `(range_backend, instantiation_purpose)` pair is
  immutable resource ownership. It is not a mutable policy setting and must not
  be re-derived during retry, compensation, destroy, or reconciliation.

In particular, do not infer non-user demo authority from Mission Control,
staff/superuser status, a demo scenario, `ENVIRONMENT=development`, a management
command name, or `GCP_RANGE_BACKEND=gdc`. Normal CTF and Mission Control entry
points remain live-fire. A dedicated BAS/demo/operator path must explicitly
mint its closed purpose after its existing authorization gate.

## Architecture Decisions And Guardrails

- Extend `shared.range_instantiation_policy`; do not create another policy
  package. It remains dependency-light and Django-free so CMS, Engine, the
  standalone provisioner, renderers, and tests share one parser and matrix.
- Replace hard-coded "non-user permits everything" logic with a closed,
  default-deny backend-to-purpose mapping. GCE may be explicitly admitted for
  live-fire and non-user purposes. GDC may be explicitly admitted only for the
  non-user purposes named by ADR-030. A new backend starts with no permitted
  purpose until its mapping is reviewed and added.
- Keep the normal public product facade fixed to live-fire. Do not add an
  optional caller-selectable purpose to HTTP serializers, forms, query params,
  scenario YAML, `RequestSpec`, `RangeSpec`, ACES plans, event range config, or
  generic participant APIs. Dedicated trusted workflows may pass a closed enum
  to an internal CMS service seam.
- Evaluate policy once at the CMS service boundary before active-range
  reservation, Engine persistence, launch-intent creation, subnet allocation,
  secret access, or provider mutation. Both legacy and ACES create paths must
  consume that result.
- Engine must accept only a normalized, admitted result and revalidate the
  closed `(backend, purpose)` pair without rereading environment selection.
  `BackendAdmission` is a constructible dataclass, so `admitted=True` from an
  arbitrary in-process caller is not by itself authority. A direct GCP Engine
  create with a missing, denied, or malformed binding fails closed.
- Persist backend and purpose in the existing Engine `Range` binding in the
  same transaction as range creation, before dispatch. Preserve write-once
  idempotency checks. If stable new identifiers exceed the current
  `range_backend`/`instantiation_purpose` field widths, widen those scalar
  columns deliberately; do not abbreviate identifiers or add a JSON copy.
- Provision must read both persisted fields through the incumbent
  `provisioner_db` projection, parse them through the shared closed policy, and
  carry them together in the existing `RangeOperation`. The real provision
  path currently reads `range_backend` but does not consume
  `instantiation_purpose`; calling `apply_range()` with its default
  `LIVE_FIRE` cannot make a permitted GDC non-user workflow work correctly.
- Route provision and provision-failure compensation from the persisted
  binding, or fail with `prerequisite` if the deploy configuration no longer
  matches what CMS admitted. Never silently select from the current environment
  after admission. Destroy continues to route by ownership and must not rerun
  new-provision policy.
- Keep the provisioner-side policy evaluation as defense in depth before every
  GDC apply function. The purpose comes from the locked Engine row, not argv,
  Job environment, scenario content, or a direct function argument supplied by
  an untrusted caller.
- Keep ACES realizability separate. `aces_range_ops` currently realizes GCE
  only. A policy-allowed GDC non-user purpose must still fail
  `unsupported-capability` before dispatch unless a real GDC ACES adapter and
  its conformance exist. Never bind `gdc` and then run the hard-coded GCE
  adapter.
- Preserve GDC VM Runtime, scenario Pod, VLAN/L2 Network, VM-Series, secret,
  and idempotent cleanup plumbing for admitted non-user modes and historical
  resources. An allow does not promote that substrate to live-fire.
- Preserve the structured provisioner command family and launch-intent
  authorization. Backend and purpose stay out of argv, per-Job overrides,
  launch-intent JSON, events, public status DTOs, and scenario artifacts.
- Do not add an ambient `ALLOW_GDC`, `UNSAFE_MODE`, policy JSON environment
  variable, or deployment-tier bypass. Explicit code registration plus a
  trusted workflow purpose is the double opt-in.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Product auth and provenance | Mission Control DRF/session/API-token permissions, CTF organizer/participant gates, `ctf.bridges.cms_create_range`, `shared.enums.RangeSource` | Authenticate and derive provenance first. CTF always mints live-fire. `RangeSource` never grants GDC. |
| Operator validation authority | Django management-command trust boundary, especially `cms.management.commands.run_aces_backend_validation` | An operator-only path may mint operator-validation after its own checks; routing through `RangeSource.MISSION_CONTROL` alone is not sufficient. |
| Range admission | `cms.services.create_range_dispatch`, legacy `_range_create`, ACES `_aces_range_create`, `_range_backend_admission` | Use one pre-mutation policy check for every create caller. Keep the generic facade live-fire. |
| Policy contract | `shared.range_instantiation_policy`, `BackendAdmission`, `InstantiationPurpose`, `normalize_gcp_range_backend` | Extend the one parser/result/matrix. Do not add a second enum, parser, boolean gate, or provider-local copy. |
| Scenario validation | CMS registry/launchability/hydration, persisted `RequestSpec`/`RangeSpec` envelopes, ACES plan validation, `cms.scenarios.realizability`, `shared.range_cells` | Policy remains adjacent to scenario intent. Backend capability and closed request validators still run independently. |
| Engine persistence | `engine.models.Range`, `engine.services._range_backend_binding`, legacy and ACES create services | Reuse the write-once scalar binding and idempotent conflict behavior. Do not add a policy repository or another operation record. |
| Delivery and replay | `engine.launch_intents`, `ProvisionerLaunchIntent`, `Range.provisioner_operation_id`, `engine.ecs` | Preserve canonical command validation, row-lock authorization, generation fencing, and request-id-only argv. |
| Provisioner projection/routing | `provisioner_db`, `provisioner_db_aces`, `terraform_ops.RangeOperation`, `range_terraform_runner`, `aces_range_ops` | Read backend and purpose once from Engine state. Route only to an adapter that both policy and realizability admit. |
| Config selection | `installation.registry`, closed backend settings, `config._runtime_env`, `scripts/gcp/render_runtime_env.py`, `installation.runtime_inventory`, provisioner `get_gcp_range_backend` | Keep provider-bundle registration distinct from GCP range-backend registration. Reuse the one selector parser and fail invalid values closed. |
| Errors and retry | ADR-039 failure codes, `CMSError.details`, `CTFRangeError.code`, `CloudError.code`, `shared.api.errors`, `shared.errors` | Map denied pairs to `identity-or-policy`, malformed/missing config to `prerequisite`, unsupported adapters to `unsupported-capability`, and binding mismatch to `conflict`. Do not parse prose for retry. |
| Logging/audit | module loggers, `shared.log_sanitize`, provisioner `log_redact`, existing range audit/status/outbox flows | Record stable code, normalized backend, trusted purpose, path/source, and request/range correlation. Keep payloads and credentials out. |
| Secrets and host policy | provider secret stores, `shared.cloud.sensitive_env`, GCP TaskRunner ephemeral Secrets, both provisioner Job admission-policy copies | No new secret or Job field is needed. Preserve ConfigMap equality, env allowlists, pinned image, workload identity, non-root/read-only runtime, and private temporary kubeconfig handling. |
| GDC implementation | `gdc_range_networks`, `gdc_vmruntime_assets`, `gdc_scenario_pods`, GDC config loaders and ownership labels | Reuse retained apply/destroy behavior only after trusted admission and realizability checks. |

`installation.registry.BACKEND_BUNDLES` registers deployment providers such as
AWS and GCP. It is not the registry for `gce` versus `gdc`; putting those
sub-backends there would conflate deployment selection with per-range
realization. The registration authority for range instantiation remains the
closed mapping in `shared.range_instantiation_policy`.

## Security And Cross-Cutting Validation Layers

1. **HTTP/product authorization.** Existing Mission Control and CTF permissions,
   CSRF/session/token rules, organizer gates, participant ownership, and
   workspace resolution run unchanged. No external request can choose backend
   or purpose. CTF batch, spare, recovery, scheduler, and direct bridge calls
   all arrive as live-fire.
2. **Argument and scenario shape.** Existing serializers and CMS argument
   validators reject malformed user input; scenario registry/hydration and ACES
   compilation validate authored intent. No backend or purpose field enters
   those DTOs, so duplicate validation and author-controlled escalation are
   avoided.
3. **Policy/config shape.** `InstantiationPurpose` and backend identifiers are
   closed values. `normalize_gcp_range_backend` remains the only
   `GCP_RANGE_BACKEND`/`GCP_RANGE_PLANE` parser. Unknown selector, unknown
   purpose, unregistered pair, or missing explicit allow fails closed before
   reservation. The GCP renderer should call that parser rather than reproduce
   its allowed strings; the runtime inventory continues checking key
   ownership/parity without reading values.
4. **Realizability shape.** Legacy persisted envelopes, ACES plan validation,
   `cms.scenarios.realizability`, and the closed `shared.range_cells` GCE
   contract remain authoritative for what an adapter can realize. Policy
   approval cannot turn an absent adapter into support.
5. **Persistence and concurrency.** Engine validates and commits the admitted
   pair with the `Range`; idempotent reuse requires equality. Existing
   transaction locks, active-range uniqueness, operation-generation fencing,
   and launch-intent authorization remain in force. Neither status updates nor
   selector changes rewrite the pair.
6. **Provisioner trust boundary.** Request-scoped DB projections return the
   scalar binding. The provisioner parses it, evaluates policy again, and
   chooses the existing lifecycle route before mutation. Direct
   `apply_range(purpose=...)` use is a unit seam, not production authority.
7. **OS/process exposure.** Container argv remains
   `range|aces-range <operation> --request-id <uuid> [--operation-id <uuid>]`.
   Backend/purpose are non-secret but still stay off argv, environment, mounted
   blobs, and process listings because Engine state already carries them.
   Existing subprocess argv arrays, restrictive temporary files, bounded
   workspaces, and cleanup rules remain.
8. **Kubernetes admission/runtime.** GCP Jobs still pass
   `_GCP_PROVISIONER_ENV_KEYS`, `sensitive_env` splitting, ConfigMap equality,
   the base/Helm `restrict-provisioner-jobs` policies, pinned image and service
   account checks, drop-ALL/non-root/read-only-root posture, and ephemeral
   Secret cleanup. No policy env key means no admission-manifest change.
9. **Secret handling.** Backend and purpose contain no secret. GDC kubeconfig
   material remains behind `GDC_ACCESS_SECRET_ID` in Secret Manager and a
   restrictive temporary file. Database/field-encryption values remain
   Secret-backed. No secret value, secret reference, scenario payload,
   provider response, or kubeconfig enters the admission result, binding,
   event, metric, error, or log.
10. **Errors and observability.** Internal layers retain stable ADR-039 codes
    and authored single-line reasons. Participant/public API envelopes may say
    that the configured backend is unavailable for the requested range mode
    without disclosing topology; operator logs include the closed backend and
    purpose. Raw `str(exc)`, SDK/Kubernetes stderr, config maps, and full DB rows
    do not cross API/event boundaries. CTF retry logic treats policy denial as
    permanent and prerequisite/config failures as operator-correctable.

## Backend Registration And Extensibility Seam

The extensibility seam is one immutable, closed mapping in
`shared.range_instantiation_policy`, keyed by the canonical range-backend slug
and containing its provider plus explicitly permitted `InstantiationPurpose`
values. Allowed-purpose sets are enumerated per backend, never derived from
environment, maturity, or "all enum members."

Registering another range backend means:

- add its stable slug and provider association to that one mapping with an
  explicit allowed-purpose set (empty until approved);
- extend the same selector normalization path without changing the default away
  from an approved live-fire backend;
- implement it behind the existing range lifecycle router and satisfy ADR-039
  lifecycle/error/ownership conformance plus ADR-030 security evidence for any
  live-fire allow;
- ensure its realization-path capability is advertised and checked separately,
  including legacy versus ACES support;
- persist and route from the same Engine binding; and
- add policy-matrix, service-boundary, Engine-binding, provisioner
  defense-in-depth, cleanup, and documentation coverage.

A new cloud provider additionally belongs in
`installation.registry.BACKEND_BUNDLES`; a new range substrate within an
existing provider does not. Do not introduce an adapter factory or provider
plugin system as part of #1354; ADR-039 owns the future provider-neutral
substrate port.

## Whole-Repository Surfaces In Scope

- Architecture/operator truth: ADR-030, ADR-039,
  `gdc-vm-runtime-live-fire-gate-preflight-1348.md`,
  `range-backend-ownership-binding-preflight-1666.md`,
  `provider-neutral-range-substrate.md`, GCP deployment docs, and
  `gdc-provisioning.md`.
- Shared contracts: `shared.range_instantiation_policy`, `shared.enums`,
  `shared.range_cells`, persisted schema envelopes, API errors, log
  sanitization, and cloud exceptions.
- Product entry points: Mission Control legacy/DRF launch, CTF bridge plus
  participant/batch/spare/recovery/scheduler flows, direct CMS services, ACES
  dispatch, scenario realizability, and operator validation commands.
- Engine: legacy/ACES create services and dispatch port, `Range` binding,
  migrations/backfill compatibility, launch intents, ECS/GCP Job delivery,
  operation generations, outbox/status handling, and reconciliation.
- Provisioner: request-scoped DB projections, `terraform_ops`,
  `terraform_vars`, `range_terraform_runner`, `aces_range_ops`, GCE/GDC config
  loaders, apply/destroy/compensation, subnet allocation, persisted state,
  events, and redaction.
- Runtime configuration: root installation loader/schema/registry and published
  contract, GCP runtime renderer and inventory, Django cloud settings, env
  forwarding/parity tests, and selector parser.
- Host/runtime enforcement: GCP TaskRunner, sensitive-env classification,
  launcher RBAC/workload identity, base and Helm admission policies, Pod
  security context, ephemeral Secrets, and private kubeconfig lifecycle.

## Required Test Boundaries

- Pure policy matrix: every registered backend against live-fire,
  demo/BAS, and operator-validation purposes; unknown backend/purpose and an
  unlisted pair fail closed.
- Normal-path regression: CTF participant, batch, spare, recovery, and scheduler
  flows remain live-fire and deny GDC before reservation/dispatch. A normal
  Mission Control `scenario_type="demo"` also remains live-fire and denies GDC.
- Trusted non-user paths: a dedicated demo/BAS path and the operator-validation
  path can explicitly admit retained GDC plumbing; neither can obtain that
  purpose from request or scenario data.
- Legacy and ACES parity: both CMS creation paths call policy. Each selected
  backend must also pass its own realizability check; the current ACES/GDC
  combination fails `unsupported-capability` before dispatch.
- Binding/replay: Engine persists the exact admitted pair, rejects fabricated,
  missing, malformed, denied, and conflicting pairs, and keeps it write-once
  across retry and destroy.
- Provisioner defense: it reads the persisted purpose, denies live-fire GDC
  before any apply call, allows an admitted GDC non-user pair, rejects selector
  or binding mismatch, and still destroys historical GDC ownership.
- Error/retry/observability: stable codes survive CMS/CTF/provisioner wrapping;
  permanent denial is not retried; public messages are authored and bounded;
  logs contain safe closed decision fields and no payload/secret material.
- Config/host parity: selector parsing, runtime renderer/inventory, provisioner
  env forwarding, sensitive-env classification, and both Job admission-policy
  copies remain consistent. If the preferred no-new-env design is preserved,
  tests should assert no purpose/allow key was added.

## Gotchas And Anti-Patterns

- Do not make every Mission Control "demo" a non-user demo/BAS launch. Existing
  demos are normal live-fire unless a dedicated trusted workflow says otherwise.
- Do not use `RangeSource`, scenario type/id, user role, deployment tier, feature
  flag, or selector value as a purpose.
- Do not expose purpose/backend in public schemas or accept a generic
  `allow_gdc` boolean. Booleans lose the reason and become permanent bypasses.
- Do not keep `NON_USER_VALIDATION` as a catch-all that silently admits every
  future backend. If retained for stored-row compatibility, map it deliberately
  and do not let it erase the distinct demo/BAS and operator paths required by
  the issue.
- Do not trust a constructible `BackendAdmission`, a direct
  `apply_range(..., purpose=...)` call, or the operator backfill command as
  new-provision authority. Backfill repairs ownership for cleanup; it is not an
  admission path.
- Do not ignore the persisted purpose in the actual provisioner. Today only the
  direct runner seam can pass `NON_USER_VALIDATION`; that is insufficient.
- Do not admit GDC for ACES and then execute `aces_range_ops`, which currently
  hard-codes GCE. Policy allow and adapter availability are separate gates.
- Do not reread `GCP_RANGE_BACKEND` after CMS admission to choose a different
  provision route. Use the persisted binding or fail closed on mismatch.
- Do not add a second range-backend registry under `installation`, a new
  exception hierarchy, lifecycle command, event family, repository, or
  scenario/plan schema.
- Do not put purpose/backend into argv, per-Job env, ConfigMaps, Secrets,
  launch-intent payloads, events, public status, or provider state blobs.
- Do not deny cleanup of an existing GDC range because its historical purpose is
  now forbidden. Admission governs new mutation; owned destroy is mandatory.
- Do not interpret successful GDC boot, VLAN uniqueness, namespace isolation, or
  backend registration as live-fire promotion evidence.

## Non-Goals And Implementation Boundaries

- No runtime policy, product workflow, migration, tests, or implementation plan
  is part of this note.
- No relaxation of ADR-030 or promotion of GDC/Kubernetes to a live-fire
  participant boundary.
- No conversion of ordinary Mission Control demos into non-user mode.
- No public caller-selectable backend or purpose.
- No new BAS product, demo UX, operator portal, scenario taxonomy, or ACES GDC
  adapter; this issue provides the control seam those paths may consume.
- No provider-neutral substrate refactor, adapter factory/plugin system,
  installation-registry redesign, task-runner redesign, public lifecycle/event
  redesign, or persistence repository redesign.
- No removal of GDC VM Runtime/VLAN/Pod/VM-Series plumbing, credentials required
  for owned cleanup, or historical GDC destroy support.
- No change to backend containment promotion, escape-validation, or
  event-readiness evidence requirements.
