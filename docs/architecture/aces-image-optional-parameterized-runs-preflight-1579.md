# Image-Optional Packs And Parameterized Runs Preflight

Issue: GitHub #1579, "Support packs with no images and parameterized
experiment runs."

Status: pre-implementation architecture guidance. This note does not implement
pack parsing, catalog fields, realizability logic, APIs, UI, launch behavior, or
an experiment runner. The issue body is the shipping contract for this
requirement-free run. ADR-034 is the governing decision.

## Boundary

The implementation must make "image-bearing" optional across ingestion, catalog
projection, and realizability. A pack with zero authored image references is a
valid content pack when the upstream ACES pack and SDL contracts accept it. The
absence of pack image references must not be treated as a missing package
artifact, missing catalog identity, or automatic non-realizability.

That is different from runtime boot-image resolution. A VM node with no authored
`source` may still require the backend to supply a base OS image at realization;
the provisioner already treats that as backend policy through the tenant-managed
ACES image registry. A node with an authored source still requires an exact
mapping, concrete provider image reference, or fail-loud rejection.

Parameterized experiment runs are the multi-run unit over one scenario/profile:
a run is a selected parameter binding set, not a second scenario definition and
not a resurrected legacy `cms.experiments` runtime path.

## Decisions

- Reuse the upstream pack authority. `aces-scenario-packs.validate_pack`,
  `pack_content_digest`, and `verify_pack_content_digest` own pack shape,
  bounded reads, SDL parsing, and byte identity. Do not add a Shifter-side
  "images required" validator or duplicate pack schema.
- Keep `AcesPackageSource` provenance-only. It records package identity,
  refs/digests, contract/profile, conformance status, and bounded provenance;
  it must not grow raw SDL, image inventories, run matrices, parameter values,
  runtime config, generated content, credentials, or package bodies.
- Keep one catalog projection through `cms.scenarios.registry` and
  `cms.scenarios.catalog_presentation`. ACES entries can carry read-only
  capability/realizability metadata, but access remains `ScenarioMetadata` and
  launchability remains the registry decision.
- Treat parameterized runs as ACES instantiation data. The existing
  `shared.aces.package_loader.launch_aces_package(parameters=...)` and ACES
  `RuntimeManager.plan(..., parameters=...)` seam is the compiler/runtime
  boundary. Do not introduce a second template language, YAML preprocessor, or
  Shifter-owned variable substitution layer.
- Realizability must answer "can this selected scenario/profile/run binding be
  realized by this backend?" It must not answer "does this pack declare images?"
  For no-image packs, evaluate actual compiled plan requirements against
  `shared.aces.manifest`, `shared.aces.runtime_target`,
  `shared.aces.realization_ledger`, and provisioner parser policy.
- Preserve ADR-027. The removed legacy experiment tables, routes, feature flag,
  event bridge, and executor are not the compatibility surface for this issue.
  Future experiment execution still needs its own ACES-backed design; this issue
  only makes parameterized run units representable in the catalog/realizability
  model.

## Required Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Uniform ingestion | `cms.services.register_pack`, `PackRegistrationRequest`, `cms.scenarios.inbox` | Every in-box/API/CLI import continues through the same service; no image-bearing branch or bypass. |
| Pack validation and identity | `cms.scenarios.pack_validation` over `aces-scenario-packs==1.2.0` | Delegate pack shape, resource limits, SDL parse, associated-artifact digest, and diagnostics. |
| Package-source schema | `shared.schemas.aces_package_source`, `cms.models.AcesPackageSource` | Keep reference-only persistence and central allowlists; widen centrally only for new source/profile values. |
| Catalog and launchability | `cms.scenarios.registry`, `ScenarioWorkflow`, `list_launchable_scenarios`, `is_scenario_launchable` | Add any run/realizability projection here or behind this service seam, not in CTF/Mission Control callers. |
| Presentation DTO | `cms.scenarios.catalog_presentation`, `CatalogEntrySerializer`, `AcesCatalogFieldsSerializer` | Expose only bounded read-only fields; do not recompute launchability or leak raw pack/run bodies. |
| ACES parameterization | ACES SDL `variables`, `aces_sdl.instantiate_scenario`, `aces_runtime.RuntimeManager.plan(parameters=...)` | Validate bindings against declared variables/defaults/allowed values through ACES, not ad hoc substitution. |
| Backend capability | `shared.aces.manifest`, `shared.aces.runtime_target`, `shared.aces.realization_ledger` | Use the existing capability envelope and independent realization evidence; do not make image count a capability proxy. |
| Provisioner plan transport | `serialize_provisioning_plan`, `engine/provisioner/aces_plan.py::parse_plan` | Persist and realize the serialized ACES plan only; no new Shifter runtime spec for parameterized runs. |
| Image resolution | `engine.services._aces_image`, `engine.models.AcesImageMapping`, `engine/provisioner/aces_gce_image.py`, `aces_image_resolver.py` | Keep source-less node base-OS policy and authored-source fail-loud matching in one resolver. |
| Errors/logging/audit | `cms.exceptions.CMSError`, `shared.api.errors`, ACES `Diagnostic`, `shared.log_sanitize`, `shared.audit` | Return bounded classes/messages; log and audit ids/status/digests/counts only. |

## Cross-Cutting Layers

- **Auth surface:** pack registration remains behind CMS authoring gates:
  `validate_cms_authoring_user`, `CMS_WRITE_PERMISSIONS`, exact
  `cms:authoring:write`, and browser `threat_research_required`. Catalog
  reads stay behind `CMS_READ_PERMISSIONS` or existing user-filtered registry
  calls. Run parameter metadata is not a new entitlement or authorization axis.
- **Shape validation:** HTTP serializers may check transport types and size
  limits, but authoritative domain validation remains the shared
  package-source validator, upstream ACES pack validation, ACES SDL variable
  instantiation, and runtime capability diagnostics. Do not restate those
  contracts in a view, template, management command, or model clean hook.
- **Realizability:** missing images are not a pack-level failure. Realizability
  fails only on concrete unsupported requirements: unsupported source/contract
  profile, failed conformance, digest/ref invalidity, unsupported backend
  terms, unresolved authored image source, missing base-OS mapping for a
  source-less node, or unsupported parameter binding.
- **Persistence:** `Scenario.definition` remains legacy-only, `AcesPackageSource`
  remains provenance-only, and engine/CMS range rows continue to carry the
  serialized ACES plan or existing persisted-spec envelope. If catalog-visible
  run descriptors need persistence, use first-class bounded fields with
  contract/profile/version identity rather than unvalidated JSON in provenance,
  audit, range config, or metadata.
- **Secret handling:** parameter sets, provenance, conformance reports, package
  docs, image refs, private registry credentials, presigned URLs, prompt/script
  bodies, CTF flags, provider diagnostics, and generated runtime config must not
  appear in logs, audit JSON, API examples, argv, environment literals, CI
  output, or user-facing error details. Secret-bearing per-run input is out of
  scope and must use the platform secret-binding surfaces in a later issue.
- **OS/process exposure:** registration, catalog reads, and request-time
  realizability checks must not execute package scripts, shell commands, Docker,
  Terraform, cloud CLIs, SSH, SSM, or ACES author tooling. Native launch keeps
  the plan DB-backed and passes only bounded operation identifiers through
  structured argv.
- **Config/env shape:** no new setting, env var, Terraform variable, Helm value,
  or Kubernetes manifest is required for repo-backed zero-image packs. If
  `ACES_PACKAGE_ROOT` or object-backed resolution changes, keep
  `config/_aces_settings.py`, `config/env-manifest.json`, runtime renderers, and
  object storage adapters in parity.
- **Error envelope:** DRF responses use `shared.api.errors`; browser flows use
  scenario-editor helpers; service failures translate through `CMSError`;
  ACES/runtime failures stay bounded diagnostics. Do not expose parser traces,
  package snippets, parameter payloads, storage-provider payloads, path
  internals, or provider stderr.
- **Import boundaries:** ACES imports stay in `shared.aces` or tests. CMS, CTF,
  Mission Control, and engine code use service/dispatch seams. Do not weaken
  `.importlinter`, layer checks, ADR guard, or API-token scope checks.

## Extensibility Seam

The required seam is explicit and data-driven:

- `source_kind`, `contract_kind`, and `contract_profile` continue to identify
  the package resolver and ACES/Shifter contract;
- `workflow` / `ScenarioWorkflow` identifies staff review, range launch, CTF,
  or future experiment-style selection;
- a run descriptor, when represented, is `scenario_id + profile + parameter
  binding identity + bounded display metadata`, validated against ACES variable
  declarations before planning;
- image resolution remains per node at realization, through authored
  `source`/version or source-less base-OS mapping.

The next likely variation is another run profile or package source, not another
catalog table or caller-specific branch. Add values behind these seams rather
than editing CTF forms, Mission Control templates, engine models, provisioner
internals, or legacy YAML export logic for each variation.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/uniform-content-ingestion-contract.md` and
  `docs/architecture/uniform-content-ingestion-preflight-1578.md`
- `docs/architecture/aces-catalog-package-boundary-preflight-1232.md`
- `docs/architecture/aces-package-source-catalog-preflight-1252.md`
- `docs/architecture/aces-registry-validation-launchability-preflight-1253.md`
- `docs/architecture/aces-catalog-readonly-presentation-preflight-1254.md`
- `docs/architecture/aces-backend-manifest-realizability-preflight-1563.md`
- `docs/architecture/aces-experiment-core-preflight-1235.md` and
  `docs/architecture/experiments-removal-adr.md`
- `docs/ops/content-ingestion.md` and
  `docs/how-to/manage-aces-image-registry.md`
- `shifter/shifter_platform/cms/services/_content_ingestion.py`
- `shifter/shifter_platform/cms/scenarios/pack_validation.py`,
  `registry.py`, `catalog_presentation.py`, `inbox.py`, `loader.py`, and
  `legacy_ids.py`
- `shifter/shifter_platform/cms/models/scenarios.py`,
  `cms/api/{serializers,views,permissions,urls}.py`, and
  `cms/scenario_editor/**`
- `shifter/shifter_platform/shared/schemas/aces_package_source.py`
- `shifter/shifter_platform/shared/aces/package_loader.py`,
  `runtime_target.py`, `manifest.py`, `realization_ledger.py`, and
  `sdl_validation.py`
- `shifter/shifter_platform/engine/services/_aces_image.py`,
  `engine/models.py`, and `shifter/engine/provisioner/{aces_plan.py,
  aces_gce_image.py, aces_image_resolver.py}`
- CTF and Mission Control selection paths only through existing CMS service and
  registry seams
- `.ground-control.yaml`, `.gc/plan-rules.md`, `.importlinter`,
  `scripts/check_layer_imports/**`, `scripts/adr_guard/**`, and
  `docs/adr/{index.yaml,exceptions.yaml}` if enforcement rules or exceptions
  change

## Gotchas And Anti-Patterns

- Do not reject a pack solely because no SDL node declares `source` or because
  the pack has no image list. Image lists are not the pack identity contract.
- Do not make "zero images" mean "always launchable." A source-less VM still
  needs a base OS mapping; unsupported backend terms still fail closed.
- Do not infer run matrices from README files, compatibility prose, directory
  names, scenario ids, package paths, or Polaris-specific strings.
- Do not store run parameters in `AcesPackageSource.provenance`,
  `Scenario.definition`, `RangeInstance.range_spec`, audit JSON, request bodies
  beyond the validated launch request, or provider task env.
- Do not revive `cms.experiments`, `EXPERIMENTS_ENABLED`, legacy experiment
  routes, old run tables, or the removed executor/event bridge.
- Do not duplicate source/profile allowlists, image resolution, variable
  validation, launchability, status enums, API envelopes, exception
  hierarchies, audit paths, or CTF/Mission Control selection logic.
- Do not execute validation tooling, shell scripts, Docker, Terraform, cloud
  CLIs, SSH, or SSM from catalog/import request paths.
- Do not surface raw ACES diagnostics, parameter values, package fragments,
  image registry credentials, presigned URLs, flags, provider output, or path
  internals to users.

## Non-Goals

- No ACES cutover, legacy id reclamation, or replacement of YAML defaults / DB
  custom scenarios.
- No ACES package authoring, editing, clone/delete/export, package upload,
  marketplace, entitlement, or object-storage resolver implementation.
- No new experiment executor, artifact collector, evaluator/orchestrator claim,
  websocket topic, event bus, task runner, or runtime feature flag.
- No new image distribution redesign, image bake pipeline, registry credential
  flow, secret store abstraction, Terraform/Kubernetes surface, or env var.
- No new Ground Control requirement UID for this requirement-free run.

## Validation Expectations

For this documentation-only preflight:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation under `shifter/shifter_platform` must also run
the stack-native Ruff, format, import-linter, and targeted pytest checks
required by `.gc/plan-rules.md` for the files it touches. If provisioner image
resolution changes, include the provisioner ACES plan/image resolver tests.
