# ACES Catalog And Scenario Package Boundary Preflight

Issue: GitHub #1232, "03 - ACES migration: design legacy-safe catalog and
scenario package boundary."

Status: pre-implementation guidance.

ADR-027 note: legacy `cms.experiments` references in this preflight describe the
pre-removal state. Future experiment capability must use a new ACES-backed
design and must not restore the deleted app as the compatibility surface.

This note records the catalog and package-boundary decisions for the first
ACES vertical slice. It is not an implementation plan and does not change
runtime behavior.

## Boundary

ADR-024 remains the controlling migration decision:
`docs/architecture/aces-migration-adr.md` keeps current Shifter behavior
authoritative until a parallel ACES path passes the parity inventory and
cutover gates in `docs/architecture/aces-migration-parity-inventory.yaml`.

The catalog boundary for #1232 is:

- Shifter owns the scenario catalog projection users select from, scenario
  enablement, staff-only access, launchability, audit, UI/API presentation,
  and runtime handoff into CMS, CTF, engine, Mission Control, and provisioner
  services.
- ACES owns authored scenario package semantics, modules/imports, package
  locks, profile/conformance vocabulary, and backend manifest claims.
- Legacy YAML defaults and DB custom scenarios stay available through the
  current registry while ACES entries are added in parallel.
- ACES package records are source/provenance references, not a second CMS,
  second scenario editor, or second runtime spec store.

## Architecture Decisions

- Keep one user-facing scenario catalog. Future code should extend
  `cms.scenarios.registry` into a unified catalog projection that can list
  legacy YAML defaults, legacy DB customs, and ACES package-backed entries.
  Do not build a separate ACES catalog UI/API with separate enablement,
  access, errors, or launch workflows.
- Keep `ScenarioMetadata` as the enablement and staff-only overlay for every
  scenario id. ACES package-source records must not duplicate `enabled` or
  `staff_only`.
- Do not let an ACES row shadow a launchable legacy `scenario_id` during the
  parallel phase. `CTFEvent.scenario_id`, `Experiment.scenario_id`,
  `RangeInstance.scenario_id`, and persisted range specs all treat
  `scenario_id` as the selector/correlation key; reusing `polaris` for both
  legacy and ACES before cutover would make event/range history ambiguous.
  The first slice should use a distinct catalog id such as `polaris-aces` or a
  read-only migration link to the legacy id. Reclaiming the legacy id is a
  deliberate cutover step with rollback posture.
- The first ACES persistence addition should be a small package-source sidecar
  keyed by `scenario_id`, not raw ACES SDL stored in `Scenario.definition`.
  It stores source references and provenance needed to validate and display
  the package; it does not store module contents, generated content, hydrated
  runtime specs, CTF challenge state, experiment state, or editor drafts.
- Minimal package-source fields for the first vertical slice:
  `scenario_id`, `contract_kind` (initially an ACES/Shifter profile value),
  `contract_profile`, `package_ref`, `package_version`, `package_digest`,
  `lock_ref`, `lock_digest`, bounded `provenance` JSON, conformance status or
  report reference, `registered_by`, and timestamps. If implementation chooses
  different names, preserve these concepts and keep the record provenance-only.
- ACES modules/imports/locks are referenced as ACES-owned package artifacts.
  Shifter should store the package root ref, the lock artifact ref, and their
  digests. It should not decompose the ACES module graph into Shifter tables or
  use imports as launch rules outside the ACES parser/conformance gate.
- Legacy YAML defaults remain code-managed under
  `cms/scenarios/templates/*.yaml`. Legacy DB custom scenarios remain
  `cms.models.Scenario` rows validated by `Scenario.to_template()`. Their
  behavior, editability, soft-delete semantics, and metadata overlays do not
  change for the first ACES slice.
- ACES entries are read-only in the existing scenario editor until a later
  issue intentionally scopes authoring. Existing YAML edit, clone, delete, and
  export behavior applies to legacy custom/default scenarios only unless a
  later design defines safe package export semantics.
- Launchability is explicit metadata/projection state, not inferred from YAML
  shape. An ACES entry may be visible to staff for review while non-launchable;
  CTF event creation, experiment creation, and participant flows must only use
  entries that the registry/hydrator declare launchable for that workflow.

## Minimal Persistence Shape

For the first vertical slice, persist only what Shifter needs to identify,
review, validate, and gate an ACES package:

| Concern | Minimal storage | Guardrail |
| --- | --- | --- |
| Catalog identity | `scenario_id` and ACES contract/profile discriminator | No collision with active YAML/DB ids during migration. |
| Source package | Repository-relative path or object-storage key plus immutable version/ref | No arbitrary URL fetches from request-time code. |
| Integrity | SHA-256 digest for package content or manifest, plus lock digest | Digest validates source identity; it is not a secret and not an auth boundary. |
| Provenance | Bounded JSON with repo/commit/tool/conformance report refs | No secrets, private keys, flags, generated runtime config, or raw package bodies. |
| Access | Existing `ScenarioMetadata.enabled` and `staff_only` | Do not add duplicate access booleans to package rows. |
| Runtime handoff | Existing `wrap_persisted_spec` on hydrated Shifter specs | Do not persist raw ACES payloads in CMS/engine runtime rows. |

If the first implementation can keep ACES package entries code-managed in a
checked-in manifest, the same field shape should be used there and the database
sidecar can wait. If ACES entries need to be registered or toggled without a
deploy, use the sidecar above. In both cases, the runtime catalog projection is
the same.

## Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration decision | `docs/architecture/aces-migration-adr.md`, ADR-024 | Do not create a second migration doctrine in package docs or issue bodies. |
| Parity tracking | `docs/architecture/aces-migration-parity-inventory.yaml` | Cite existing row ids for follow-up work; do not turn inventory rows into runtime schema. |
| Legacy scenario loading | `cms.scenarios.loader` | Keep slug validation, path containment, `yaml.safe_load`, and `TypeAdapter(AnyScenarioTemplate)` for legacy YAML. |
| Catalog projection | `cms.scenarios.registry` | Extend the registry rather than adding ACES-only listing/access logic elsewhere. |
| Legacy scenario models | `cms.models.Scenario`, `ScenarioMetadata` | Keep `Scenario.definition` legacy-validated and keep `ScenarioMetadata` as the overlay for enabled/staff-only. |
| Scenario editor | `cms.scenario_editor.services` facade plus `_validation`, `_persistence`, `_metadata`, `_yaml` | Do not add a second parser/editor workflow for ACES in this issue. |
| Hydration | `cms.scenarios.hydrator` | ACES launch must adapt into Shifter `RangeSpec`/`CTFRangeSpec` semantics here or at an adjacent adapter seam. |
| CMS launch | `cms.services.create_range` and public service facade | Preserve user/agent validation, active-range checks, persisted CMS state, audit, failure status, and engine dispatch. |
| CTF bridge | `ctf.bridges` and `ctf.services.range.*` | CTF continues to call CMS through bridge/service seams using `scenario_id`; no direct ACES/engine imports. |
| Experiments | `cms.experiments.schemas`, `cms.experiments.services`, `cms.experiments.orchestrator.execution_plan` | Scenario instance lookup and script execution remain behind existing experiment validation and `ScriptExecutionContext`. |
| API auth/errors | `cms.api.permissions`, `shared.api.errors`, `shared.api_tokens.scopes` | Use CMS authoring permissions and shared DRF envelopes for any API additions. |
| User auth | `shared.auth.can_edit_cms_authoring`, `validate_cms_authoring_user`, `threat_research_required` | Service-layer authorization remains canonical; UI hiding is not authorization. |
| Errors | `shared.errors`, `shared.api.errors`, `shared.exceptions.CMSError`, existing CTF/experiment exceptions | Do not add a parallel ACES exception hierarchy for catalog operations. |
| Logs | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Log sanitized ids, digests, counts, and status only; never log package bodies or secret-bearing provenance. |
| Storage | `shared.cloud.get_object_storage`, `shared.cloud.types.ObjectStorage`, `shared.s3.sanitize_s3_filename`, `shared.uploads.inspection` | If packages are uploaded or object-backed, reuse storage adapters and inspection patterns; do not shell out to cloud CLIs. |
| Persisted specs | `shared.schemas.persistence.wrap_persisted_spec`, `engine.interpreter` | ACES-derived runtime specs must still enter engine rows through the Shifter envelope. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Future ACES imports need the same shared-boundary discipline as current CyberScript imports. |

## Cross-Cutting Layers

- Auth surface: browser catalog/editor work stays behind
  `threat_research_required` and service calls stay behind
  `validate_cms_authoring_user`. DRF work uses
  `IsAuthenticatedSessionOrApiToken`, `CMS_READ_PERMISSIONS` or
  `CMS_WRITE_PERMISSIONS`, and exact `cms:authoring:*` scopes.
- Scenario access surface: all listing/selection paths go through
  `cms.scenarios.registry` and preserve `enabled`, `staff_only`, and
  launchability filtering. Staff visibility for review is distinct from
  participant/event launchability.
- Legacy YAML shape: legacy template ids keep loader/editor slug validation,
  template path containment, `yaml.safe_load`, and existing Pydantic scenario
  adapters. ACES entries do not reuse the legacy `ScenarioTemplate` validator.
- ACES package shape: package refs, lock refs, versions, profiles, and digests
  must validate through a shared-native package-source contract and the ACES
  parser/conformance gate before any launch path treats the package as ready.
  Prose in an ADR, issue, or manifest is not a substitute for conformance.
- Storage/config shape: prefer repo-relative package refs for the first slice.
  If object storage is introduced, use configured bucket/prefix settings,
  `shared.cloud` adapters, `sanitize_s3_filename`-style key normalization, and
  server-side inspection where uploads are accepted. Do not add arbitrary
  remote URL fetches or request-supplied filesystem roots.
- Secret-handling surface: package provenance, content packages, CTF flags,
  credential placeholders, private keys, presigned URLs, upload tokens, bearer
  tokens, provider diagnostics, rendered runtime config, and generated scripts
  must not appear in logs, audit JSON, docs snippets, OpenAPI examples, issue
  bodies, shell traces, process argv, environment files, or CI output.
- OS/runtime exposure: catalog registration and validation should not execute
  arbitrary package commands at request time. Any later ACES conformance or
  backend tooling invocation must use bounded worker/service boundaries with
  structured argv, sanitized logs, and no secret-bearing command arguments.
- Error envelopes: DRF responses use `shared.api.errors`; HTML views use
  existing scenario-editor error helpers and generic unexpected-error pages.
  Raw parser/conformance exceptions, YAML bodies, package snippets, stack
  traces, storage provider payloads, and ownership internals must not be
  serialized to clients.
- Persistence surface: legacy custom scenario validation remains
  `Scenario.to_template()`; ACES package-source rows remain provenance-only;
  hydrated runtime specs are wrapped with `wrap_persisted_spec`; engine rows
  are still created by `engine.interpreter` in transactions.
- Import-boundary surface: CMS may use `shared`, `management.services`, and
  `engine.services` through allowed seams. CTF and Mission Control must use
  bridge/service facades. Do not introduce direct ACES or CyberScript imports
  outside `shared` without a later ADR/import-rule change.
- Workflow validators: architecture/doc changes must pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`. Runtime Python
  under `shifter/shifter_platform` also needs Ruff and import-linter; API or
  workflow/config changes inherit the checks in `.gc/plan-rules.md`.

## Extensibility Seam

The extension seam is an explicit catalog contract/profile discriminator plus
a package-source adapter at the registry/hydrator boundary. The discriminator
must be data, for example legacy demo, legacy CTF, and ACES Shifter profile,
not implicit YAML-shape detection and not a Polaris-specific branch.

The first future variation is another ACES profile or package source
(repository path versus object storage). That variation should add a new
profile/source adapter behind `shared` and `cms.scenarios`, not edits in CTF
event code, Mission Control templates, experiment flows, engine internals, or
the scenario editor.

## Whole-Repo Scope

Likely implementation surfaces for the later coding work are:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `docs/adr/index.yaml` and `docs/adr/exceptions.yaml` only if enforceable
  rules or exceptions change.
- `shifter/shifter_platform/cms/models/scenarios.py` and CMS migrations for
  package-source persistence if DB-backed registration is needed.
- `shifter/shifter_platform/cms/scenarios/schema.py`, `loader.py`,
  `registry.py`, and `hydrator.py`.
- `shifter/shifter_platform/cms/scenario_editor/**` for read-only ACES catalog
  presentation and metadata toggles.
- `shifter/shifter_platform/cms/api/**` for read-only/API projection fields if
  API work is scoped.
- `shifter/shifter_platform/cms/services/**` for launchability-aware scenario
  listing and range creation handoff.
- `shifter/shifter_platform/shared/**` for shared-native ACES package-source
  contracts, validation helpers, and import shims.
- `shifter/shifter_platform/ctf/**` only through existing bridge/service usage
  and form/listing impacts.
- `shifter/shifter_platform/cms/experiments/**` for scenario-instance lookup
  and launchability impacts, not package parsing.
- `shifter/shifter_platform/engine/**` and `shifter/engine/provisioner/**`
  only when a launch adapter is intentionally scoped.
- `scenario-dev/polaris/sdl/**`,
  `scenario-dev/polaris/content-packages/**`, and
  `scenario-dev/polaris/containers/images.yaml` as ACES package evidence.
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, and
  `scripts/adr_guard/**` if import or guardrail policy changes.

## Follow-Up Implementation Issues

The design identifies these concrete implementation scopes:

- #1252: add ACES package-source catalog persistence/projection with
  provenance, digest, lock, and launchability fields while reusing
  `ScenarioMetadata`; see
  `docs/architecture/aces-package-source-catalog-preflight-1252.md` for the
  issue-specific persistence/projection guardrails.
- #1253: add ACES package/profile validation and registry integration behind
  `cms.scenarios.registry`, with no legacy `scenario_id` shadowing; see
  `docs/architecture/aces-registry-validation-launchability-preflight-1253.md`
  for the issue-specific launchability guardrails.
- #1254: expose ACES catalog read-only fields in the scenario editor and CMS
  API, with no new editor and with existing authoring/API permissions; see
  `docs/architecture/aces-catalog-readonly-presentation-preflight-1254.md` for
  the issue-specific presentation/API guardrails.
- #1233 owns the Shifter ACES RuntimeTarget/backend-manifest design that later
  implementation work should use for the RuntimeModel-to-Shifter range adapter.
- #1237 owns the Polaris acceptance and parity-gate design that later
  implementation work should use for backend manifest/conformance launch
  evidence.

## Gotchas And Anti-Patterns

- Do not add an ACES-only CMS, UI, API envelope, metadata table, access model,
  status taxonomy, parser stack, or exception hierarchy.
- Do not store raw ACES SDL, imported module bodies, generated content,
  generated runtime config, or hydrated specs in a provenance sidecar.
- Do not let ACES package rows reuse active legacy ids such as `polaris` before
  cutover; use a distinct id or an explicit migration link.
- Do not infer contract type by probing YAML keys. Use an explicit
  contract/profile discriminator.
- Do not make `Scenario.definition` a polymorphic raw blob for legacy and ACES.
  It is currently the validated legacy custom scenario definition.
- Do not duplicate `enabled` or `staff_only` on ACES package rows.
- Do not bypass `cms.scenarios.hydrator`, `cms.services.create_range`,
  `engine.services`, or `engine.interpreter` to launch ACES packages.
- Do not call ACES backend tools, Terraform, Docker, cloud CLIs, or shell
  scripts directly from CMS/CTF/Mission Control request paths.
- Do not treat package digests as secrets or auth controls, and do not log
  package bodies, flags, credentials, presigned URLs, upload tokens, bearer
  tokens, or provider payloads.
- Do not use Polaris as the adapter type system. Polaris is the parity proving
  case; the public seam is the ACES Shifter profile.
- Do not remove CyberScript, current scenario templates, current Polaris
  launch material, CTF behavior, experiment execution, Mission Control
  behavior, provisioner paths, artifacts, statuses, or validation gates in this
  issue.

## Non-Goals

- No ACES parser, conformance CLI, backend manifest, range adapter, data
  migration, UI editor, or launch selector is implemented by this note.
- No legacy scenario is removed, renamed, or cut over.
- No CTF scoring, challenge, flag, hint, participant, or event lifecycle
  semantics are moved into ACES by this issue.
- No experiment script execution, artifact collection, or `ScriptExecutionContext`
  behavior changes.
- No new env knob, Kubernetes manifest, Terraform module, cloud runner, or
  secret delivery path is required for a repo-backed first slice.
- No new Ground Control requirement is created for this requirement-free run.
