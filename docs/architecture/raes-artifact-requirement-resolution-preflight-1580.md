# RAES Artifact-Requirement Resolution Preflight

Issue: GitHub #1580, "Resolve RAES artifact requirements against backend
capabilities."

Status: pre-implementation architecture guidance. This note does not implement
catalog ingestion, resolution, preparation, or provisioning. The issue is the
authoritative contract for this requirement-free run. ADR-053 and ADR-034 are
the governing decisions; no new ADR is needed.

## Dependency Gate

The pinned `raes==2.0.0` release provides the portable artifact-requirement,
backend-mechanism, availability, diagnostic, and satisfaction-disclosure
contracts. Use those public contracts directly.

`raes-env-packs==3.1.0` exports the public Environment Packs publication profile
(the `raes_env_packs.publication` module: `ArtifactRequirement`,
`ArtifactMechanismCapability`, `ArtifactSatisfactionRoute`,
`authored_artifact_requirements`, `validate_publication_document`,
`load_backend_profile`, and the `publication.*` diagnostic codes), and still
requires `raes==2.0.0`. Shifter pins it exactly (`pyproject.toml`, `uv.lock`,
ADR-032-R4) and consumes those public contracts directly. The gap must never be
bridged by parsing release-tool output, importing a private upstream module,
vendoring a schema, or adding a Shifter publication-profile DTO; the earlier
`3.0.0` release predated the profile and is superseded by this exact pin.

## Architecture Decisions And Guardrails

- RAES is the sole semantic authority for `exact`, `constrained`, and `open`
  requirements. Absence is `artifact_requirement is None`; it is not an open
  request, base-image request, empty constraint, or trigger for the legacy
  resolver. Consume compiled upstream requirements and their resource addresses
  rather than reparsing SDL or copying compiler address rules.
- Use the upstream `ArtifactAvailabilityContext`,
  `ArtifactMechanismCapability`, planning diagnostics, and
  `ArtifactSatisfactionDisclosureModel`. Shifter owns the facts supplied to
  those contracts: selected target, tenant policy, verified inventory,
  pack-published availability, preparation readiness, and backend mechanism
  support. It does not own alternate portable schemas or diagnostic codes.
- Declare only mechanisms the deployed backend can actually execute in
  `shared/raes/backend-manifest.json`. The current empty
  `artifact_mechanisms` declaration truthfully admits none. A mechanism becomes
  usable only when its exact upstream profile, allowed requirement kinds,
  acquisition routes, and timing routes are declared and the corresponding
  execution adapter is present.
- Keep five decisions independent: artifact selection, present or prepared
  availability, trust/admission, acquisition transport, and execution timing.
  Commercial entitlement and transport authentication remain outside semantic
  resolution. A successful pull, copy, import, or local lookup proves neither
  identity nor admission and is not a substitute for baking.
- Use one server-owned resolution seam:
  `(compiled requirement, selected backend declaration, immutable availability
  snapshot, tenant policy) -> upstream satisfaction disclosure plus a concrete
  backend binding, or an upstream stable diagnostic`. Catalog realizability,
  launch admission, preparation readiness, and operation materialization must
  call that seam rather than implement policy independently.
- Exact requirements accept only the authored immutable identity. The current
  source-name/version mapping, blank-version fallback, provider-reference
  passthrough, default base image, dynamic composition, and fresh bake can never
  satisfy an exact requirement. Constrained requirements may select only a
  candidate satisfying every bound and locked input. Open requirements may be
  delegated only through a declared compatible backend mechanism.
- Select and generation-fence the result before provisioning. Materialize the
  upstream disclosure and the minimum concrete, non-secret backend binding into
  the existing closed `OperationInput` envelope. The provisioner validates and
  executes that binding; it must not query mutable catalog/registry state,
  choose a different candidate, reinterpret the requirement, or fall back.
  Keep the serialized upstream `ProvisioningPlan` unchanged in `range_config`.
- Backend-native inventory, a pack-published artifact, completed preparation,
  bounded dynamic composition, and future upstream-defined mechanisms are
  supply or execution inputs to the same seam. Do not add a parallel registry
  or resolver. Evolve the existing image-management service as the tenant
  inventory projection, but key portable identity and candidates with the full
  upstream identifiers and evidence rather than the legacy source alias.
- Long-running VM-image construction cannot run in catalog reads, HTTP launch,
  launch-intent materialization, or the provisioner. This issue may consume a
  completed preparation result as availability. Optional in-tenant preparation
  and its scheduling belong to #1583. Bounded realization-time composition is
  allowed only when the RAES route permits it and the backend declares support.
- Use the upstream failure codes for unavailable exact artifact, unsatisfied
  constraint, missing locked input, unavailable candidate, unsupported open
  realization, and unsupported backend mechanism. Expected non-realizability is
  a typed domain result, not a new exception hierarchy. Preserve any additional
  upstream publication/materialization diagnostic instead of collapsing it to
  "image unavailable."

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Upstream contracts and pins | `pyproject.toml`, `uv.lock`; public `raes.artifact_requirements` and `raes_contracts.artifact_requirements` | Exact-pin the compatible RAES and Environment Packs releases; use public models, validators, planners, diagnostics, and disclosures. |
| Pack identity and validation | `cms.scenarios.pack_validation`, `shared.raes.package_loader`, `shared.raes.object_source`, `RaesPackageSource` validation | Preserve bounded containment/extraction, canonical associated-artifact digest verification, immutable source identity, and the thin upstream validator wrapper. Keep `RaesPackageSource` provenance-only. |
| Capability and planning | `shared.raes.manifest`, `backend-manifest.json`, `realizability`, `runtime_target`, RAES `RuntimeManager.plan` | Build the upstream availability context and validate against the selected target. Do not create a CMS compiler, capability table, or manifest shadow. |
| Inventory and matching | `engine.models.RaesImageMapping`, `engine.services._raes_image`, `cms.api.raes_image_registry`, `shared.raes.image_policy` | Evolve one managed inventory and one pure resolver seam. Legacy source aliases are not portable identities and never authorize exact fallback. |
| Durable execution input | `engine.operation_inputs`, `shared.operation_envelope`, `shared.raes.operation_input`, `OperationInput` | Extend the existing versioned, bounded, immutable, generation-fenced payload. Persist the chosen disclosure/binding, not merely a mutable candidate list. |
| Workflow and retries | launch intents, provisioner launcher/outbox, `OperationResultInbox`, result applier and heartbeat/fencing conventions | Reuse the existing state machine, retry, idempotency, ownership, and result-disposition paths. Do not add a second job table or direct provisioner registry reads. |
| Provisioning | provisioner `raes_plan`, `raes_gce_image`, `raes_range_ops`, and provider config validators | Parse the closed projection and execute the selected adapter. Provider code must not import RAES or regain selection authority. |
| Admission and authorization | `cms.api.permissions`, `_raes_range_create`, `range_instantiation_policy`, `validate_cms_authoring_user` | Keep content registration, authoring, range launch, workspace ownership, quota, feature flags, backend admission, and artifact admission as their existing independent gates. |
| Errors, logs, and audit | RAES diagnostics, `shared.api.errors`, `shared.errors`, `CMSError`, `RequestIDMiddleware`, `shared.log_sanitize`, provisioner redaction, existing registration/management audit | Return stable bounded codes; keep request correlation and strict mutation audit; never expose raw upstream, provider, storage, SQL, or parser errors. |

`shared` is the only platform layer that may import RAES. The separately
deployed provisioner remains dependency-light and consumes a plain validated
projection. Preserve `.importlinter`, `scripts/check_layer_imports/**`, ADR
guard, and the upstream parity/conformance tests.

## Cross-Cutting Layers The Design Must Pass

- **Authentication and authorization:** catalog reads retain their existing CMS
  read permission; registration/inventory mutations retain exact authoring or
  management write permissions and service-level actor validation; launch
  retains feature-flag, active-range, workspace ownership, quota, scenario
  launchability, and backend-admission checks. Artifact availability never
  grants launch authority.
- **Browser/session policy:** continue through DRF session/token permission
  classes, same-origin cookies, CSRF middleware, and the shared frontend client.
  Add no browser credential store, raw registry credential, presigned URL, CORS
  relaxation, or `csrf_exempt` path.
- **Pack and contract shapes:** pass the upstream Environment Packs validator
  and canonical digest/associated-artifact binding, RAES parse/compile and
  artifact invariants, selected backend mechanism declaration, upstream
  availability validation, tenant trust/admission policy, operation-envelope
  validation, RAES operation-input parsing, provisioner plan parsing, and the
  provider config validator. Do not duplicate validation in serializers or
  provider adapters; each boundary validates its own projection.
- **Trust and secrets:** pack integrity is not artifact authenticity,
  provenance, admission, transport authentication, or entitlement. Populate
  verified integrity/authenticity/admission/provenance/evidence references only
  from their owning trust gates. Credentials, tokens, signed URLs, secret
  values, artifact bodies, private provider responses, and raw evidence stay
  out of DTOs, operation input, range config, argv, environment projections,
  logs, metrics, audit JSON, errors, and frontend data.
- **Config and environment:** no new setting or secret is required for semantic
  resolution. If a later adapter genuinely needs configuration, keep
  `config/_raes_settings.py`, `_runtime_env.py`, `_env_manifest.py`,
  `env-manifest.json`, installation rendering, Terraform/Helm/Kubernetes/AWS
  projections, runtime inventory, and the Kubernetes provisioner environment
  allowlist in parity. Never transport a resolution or credential through env.
- **OS and process exposure:** provisioner argv remains opaque resource,
  operation, and request identifiers; execution data is fetched through the
  restricted `OperationInput` read. Do not put an artifact identity, provider
  ref, constraint, plan, token, or secret in argv or child env. Do not execute
  package code, shell, Docker, Packer, Terraform, cloud CLI, SSH, or SSM on the
  provisioning path.
- **Persistence and database access:** preserve immutable operation-input
  generations, maximum payload bounds, atomic launch-intent materialization,
  provisioner least-privilege reads, append-only result inbox, digest/replay
  checks, and stale-generation fencing. Do not broaden provisioner grants or
  store mutable resolution truth in `RaesPackageSource`, `ScenarioMetadata`,
  audit payloads, or the upstream plan.
- **Errors and observability:** expected failures use upstream stable diagnostic
  codes and bounded safe context. Non-2xx responses use
  `shared.api.errors` with request id. `safe_log_value` prevents log injection
  but is not a confidentiality control: never wrap arbitrary `str(exc)` into a
  diagnostic or response. Log only correlation/operation/scenario-safe ids,
  target, posture, mechanism-profile id, outcome code/count, and duration; omit
  artifacts, provider locations, constraints, locked inputs, trust evidence,
  payloads, and credentials.

## Extensibility Seam

The extensibility seam is the resolution input tuple above plus an execution
adapter registered by exact upstream mechanism-profile identity. A new backend,
inventory source, publication-profile version, or permitted satisfaction
mechanism contributes normalized availability facts or one adapter; it does not
add provider conditionals to CMS views, catalog DTOs, the operation-input
parser, or RAES SDL handling. Contract/profile version is explicit and
fail-closed so one future upstream version does not silently change stored
semantics.

## Whole-Repo Scope

The later implementation must evaluate together:

- ADR-053/034 and the #1566, #1567, #1578, #1579, #1581, #1583, and #1837
  boundary notes;
- exact dependency pins in `shifter/shifter_platform/pyproject.toml` and
  `uv.lock`;
- `shared/raes/{manifest,backend-manifest.json,package_loader,object_source,
  realizability,runtime_target,image_policy,operation_input}.py`;
- `cms/scenarios/{pack_validation,realizability,catalog_presentation}.py`,
  `cms/services/{_content_ingestion,_raes_range_create}.py`,
  `cms/api/raes_image_registry.py`, and `cms/models/scenarios.py`;
- `engine/models/{_raes,_operation_io}.py`, `engine/services/_raes_image.py`,
  `engine/operation_inputs.py`, launch intents, provisioner outbox/result
  applier, and their database grants;
- provisioner `raes_plan.py`, `raes_gce_image.py`, `raes_range_ops.py`, provider
  config validators, launchers, and redaction;
- `shared/{operation_envelope,api/errors,errors,log_sanitize}.py`, request-id
  middleware, audit and range-admission policy;
- `config/{_raes_settings,_runtime_env,_env_manifest}.py`,
  `config/env-manifest.json`, installation/deployment renderers,
  Terraform/Helm/Kubernetes/AWS runtime projections, and the Kubernetes
  provisioner environment validation policy;
- `.importlinter`, `scripts/check_layer_imports/**`, `scripts/adr_guard/**`, and
  upstream contract, resolver-parity, envelope/fencing, API, workflow, and
  provider tests.

## Gotchas And Anti-Patterns

- Do not translate absence to an open concern, an implicit base OS, or a default
  image lookup. Zero-artifact packs bypass artifact resolution.
- Do not treat source name/version, a filename, mutable tag, provider image
  path, pack tier, or publication metadata as an immutable artifact identity.
- Do not preserve the current blank-version fallback or concrete-reference
  passthrough for a portable exact requirement.
- Do not equate pack conformance/digest, transport success, registry login, paid
  entitlement, or backend inventory presence with artifact admission.
- Do not make pull/copy/import/local lookup competing semantic mechanisms, or
  assume every missing artifact is buildable.
- Do not re-resolve in the provisioner, at retry time, or from mutable registry
  state. Replay executes the generation-fenced decision or fails closed.
- Do not copy upstream requirement, publication, capability, availability,
  route, evidence, or diagnostic schemas into Shifter; do not add another
  exception hierarchy, registry, cache-as-truth table, or workflow engine.
- Do not parse private Environment Packs release-tool output to unblock the
  missing public publication profile.
- Do not place a long-running image build, live cloud probe, object download, or
  unbounded per-node query on catalog-list or provision-request paths.
- Do not leak raw exception text, paths, provider references, locked inputs,
  constraints, trust evidence, artifact payloads, or credentials through
  errors, logs, metrics, audit, argv, env, OpenAPI examples, or frontend state.

## Non-Goals And Implementation Boundaries

- Defining or extending the RAES portable requirement, Environment Packs
  publication profile, trust model, registry/distribution protocol,
  materialization vocabulary, or commercial entitlement model.
- Implementing the object-backed acquisition transport from #1567 or the
  optional preparation workflow from #1583. (Operated distribution channels are
  not a BigRAE concern; #1582 was closed as misconceived under ADR-053.)
- Making every artifact buildable, adding an implicit exact-artifact fallback,
  or treating preparation as the universal answer to unavailable supply.
- Moving artifact publication/promotion into the Shifter product plane or
  moving tenant admission/policy into RAES or Environment Packs.
- Replacing the upstream `ProvisioningPlan`, broadening provisioner database
  access, adding a second catalog/inventory store, or making the browser select
  a backend mechanism.
