# ACES Registry Validation And Launchability Preflight

Issue: GitHub #1253, "12 - ACES migration: implement registry validation and
launchability for ACES packages."

Status: pre-implementation architecture guidance. This note does not implement
the registry changes, launch adapter, parser, conformance runner, UI, API, or
cutover.

## Boundary

ADR-024 remains the controlling migration decision:
`docs/architecture/aces-migration-adr.md` keeps current Shifter behavior
authoritative until the parallel ACES path passes parity, package/profile
validation, backend manifest/conformance, portal, CMS, engine, provisioner,
status, and validation gates.

The package-source sidecar from #1252 is the incumbent persistence boundary.
`cms.models.AcesPackageSource` and
`shared.schemas.aces_package_source.validate_package_source` already enforce
the provenance-only shape for ACES catalog records. Issue #1253 should build on
that record and the unified `cms.scenarios.registry` projection. It must not
add a second ACES catalog, duplicate package schema, duplicate access model, or
Polaris-specific launch path.

## Architecture Decisions

- Keep one catalog projection. Staff review listings may include non-launchable
  ACES entries, but Mission Control launch, CTF event selection, CTF
  participant provisioning, and any experiment-style launch selector must ask
  the registry/service layer for entries launchable for that workflow.
- Make launchability a registry decision over explicit data, not caller-side
  filtering. The decision must combine source/contract/profile support,
  package and lock references, package and lock digests, conformance status or
  report evidence, no-shadowing, and workflow support. Do not let each view or
  form reinterpret `launchable`.
- Preserve legacy validation exactly. YAML defaults stay under
  `cms.scenarios.loader` with slug validation, path containment,
  `yaml.safe_load`, and `TypeAdapter(AnyScenarioTemplate)`. DB custom
  scenarios keep `Scenario.to_template()`. Do not infer ACES from raw YAML
  shape and do not make `Scenario.definition` polymorphic.
- Preserve active legacy `scenario_id` values during the parallel phase. An
  ACES row whose id collides with a YAML default or active DB custom scenario
  is review evidence at most; it must not become launchable or selectable until
  a later accepted cutover defines rollback posture.
- Keep ACES package records provenance-only. `AcesPackageSource` may identify a
  package, lock, profile, digest, report ref, actor, and bounded provenance. It
  must not store raw ACES SDL, imported module bodies, generated content,
  hydrated Shifter specs, flags, credentials, tokens, presigned URLs, provider
  diagnostics, or runtime config.
- Keep runtime handoff through the existing seams. A launchable ACES entry
  adapts at the registry/hydrator boundary into Shifter `RangeSpec` or
  `CTFRangeSpec` semantics, then flows through `cms.services.create_range`,
  `wrap_persisted_spec`, `engine.services`, `engine.interpreter`, and the
  provisioner path.
- Treat the published `provisioning-only` backend manifest as capability
  evidence, not a launchability shortcut. Launchability requires package/profile
  validation and the accepted ACES conformance evidence for the claimed profile.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | ADR-024 in `docs/architecture/aces-migration-adr.md` | Keep ACES parallel and parity-gated; do not cut over by declaration. |
| Package-source persistence | `cms.models.AcesPackageSource`, `shared.schemas.aces_package_source` | Reuse the sidecar and validator; widen allowlists centrally only when a new source/profile lands. |
| Catalog projection | `cms.scenarios.registry` | Add purpose/workflow-aware selection here or in `cms.services` over this projection, not in CTF or Mission Control views. |
| Legacy validation | `cms.scenarios.loader`, `cms.scenarios.schema`, `Scenario.to_template()` | Keep legacy YAML and DB custom behavior unchanged. |
| Metadata/access | `ScenarioMetadata` | Continue to apply `enabled` and `staff_only`; do not duplicate access flags on ACES rows. |
| Hydration | `cms.scenarios.hydrator` | Add an ACES adapter seam here or adjacent to it; do not bypass hydration from request paths. |
| CMS launch | `cms.services.create_range` | Preserve user validation, agent checks, active-range checks, request/range persistence, audit, failure status, and engine dispatch. |
| CTF integration | `ctf.bridges`, `ctf.forms`, `ctf.services.range.*` | CTF continues to call CMS services; it must not import ACES or engine internals directly. |
| Mission Control | `mission_control.views`, `mission_control.api`, `mission_control.api.serializers` | Keep request validation, participant blockers, owner permissions, and safe error classification. |
| Backend manifest | `shared.aces.manifest`, tests in `tests/shared/aces/` | Use the published `provisioning-only` claim as bounded capability evidence only. |
| Persisted specs | `shared.schemas.persistence.wrap_persisted_spec`, `engine.interpreter` | Persist hydrated Shifter specs through the existing envelope; no raw ACES blobs in range rows. |
| Errors | `cms.exceptions.CMSError`, `shared.errors`, `shared.api.errors`, CTF exceptions | Do not add an ACES-only exception hierarchy or API envelope. |
| Logging/audit | `shared.log_sanitize`, `risk_register.services.audit_log`, provisioner redaction | Log ids, status classes, digests, report refs, and counts only. |
| Import rules | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Keep ACES imports behind `shared` and service seams. |

## Cross-Cutting Layers

- Auth surface: staff catalog review remains behind
  `threat_research_required`, `HasCMSAuthoringActor`, and exact CMS authoring
  scopes when exposed through DRF. Mission Control launch remains behind
  `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, range write
  scopes, and participant lifecycle blockers. CTF event/range work remains
  behind organizer/participant permissions and exact CTF API-token scopes.
- Shape validation surface: legacy YAML keeps the loader/Pydantic gates. ACES
  rows pass the shared package-source validator for source kind, contract kind,
  profile ref, package ref/version/digest, lock ref/digest, conformance status,
  report ref, and bounded provenance before they enter launchability logic.
- ACES conformance surface: a `passed` row is launchable only when it matches a
  supported contract/profile and the accepted ACES parser/profile/backend
  manifest evidence. If the conformance evidence cannot be verified for the
  package ref, lock ref, digests, and profile, fail closed.
- Config/env surface: this issue should not need new settings, env vars,
  Terraform variables, Helm values, or Kubernetes manifests. If a later source
  needs bucket/prefix/profile selectors, it must use `config/settings.py`,
  `config/env-manifest.json`, runtime inventory/renderers, and tests.
- Secret-handling surface: package provenance, conformance diagnostics, CTF
  flags, private keys, bearer tokens, presigned URLs, generated scripts,
  terminal URLs, provider payloads, and rendered runtime config must not appear
  in logs, audit JSON, API responses, docs examples, process argv, env files,
  or CI output.
- OS/process exposure: request-time catalog or launch code must not execute
  package commands, shell scripts, Terraform, Docker, cloud CLIs, or ACES tools.
  Any validator/tool invocation belongs behind bounded worker/service code with
  structured argv containing ids, refs, digests, and profile names only.
- Error-envelope surface: DRF responses use `shared.api.errors`; browser flows
  use existing view helpers and `shared.errors.classify_user_message`. Raw ACES
  parser/conformance exceptions, package snippets, YAML bodies, storage
  provider payloads, stack traces, and ownership internals stay out of client
  responses.
- Persistence surface: `AcesPackageSource` remains provenance-only;
  `Scenario.definition` remains legacy-only; hydrated runtime state remains in
  wrapped CMS/engine range specs; audit rows carry sanitized summaries only.
- Import-boundary surface: CMS may use `shared`, `management.services`, and
  `engine.services` through allowed seams. CTF and Mission Control use
  `cms.services` and bridges. Direct ACES imports outside `shared` require a
  later ADR/import-rule change.

## Extensibility Seam

The required seam is a data-driven launchability selector:

- source kind: repo-managed versus object-backed package source;
- contract kind and contract profile: initially ACES/Shifter, not Polaris;
- workflow purpose: staff review, Mission Control launch, CTF event selection,
  CTF participant provisioning, and any later experiment/runtime selector;
- backend profile/capability: initially the published `provisioning-only`
  Shifter backend claim;
- evidence identity: package ref/version/digest, lock ref/digest, and
  conformance report ref/status.

Future ACES profiles, package sources, or workflow purposes should add values
behind this seam. They should not require edits in CTF event forms, Mission
Control templates, engine models, provisioner internals, or Polaris-specific
branches.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-catalog-package-boundary-preflight-1232.md`
- `docs/architecture/aces-package-source-catalog-preflight-1252.md`
- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-polaris-acceptance-parity-gate-preflight-1237.md`
- `docs/architecture/aces-migration-parity-inventory.yaml` rows
  `scenario.yaml-defaults`, `scenario.any-template-union`,
  `scenario.hydration-range-spec`, `polaris.content-packages`,
  `polaris.portal-template`, and `validation.aces-manifest-conformance`
- `shifter/shifter_platform/shared/schemas/aces_package_source.py`
- `shifter/shifter_platform/shared/aces/manifest.py`
- `shifter/shifter_platform/cms/models/scenarios.py`
- `shifter/shifter_platform/cms/scenarios/loader.py`,
  `registry.py`, `hydrator.py`, and `schema.py`
- `shifter/shifter_platform/cms/services/_scenarios.py` and
  `_range_create.py`
- `shifter/shifter_platform/cms/scenario_editor/**` for review-only
  projection and metadata toggles, not package authoring
- `shifter/shifter_platform/mission_control/views/_ranges.py` and
  `mission_control/api/ranges.py` for launchable-only choices
- `shifter/shifter_platform/ctf/bridges.py`, `ctf/forms.py`,
  `ctf/services/range/**`, and CTF event APIs for launchable-only choices
- `shifter/shifter_platform/engine/**` and `shifter/engine/provisioner/**`
  only when an ACES hydrator/adapter is explicitly scoped
- `.ground-control.yaml`, `.gc/plan-rules.md`, `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`, and
  `scripts/adr_guard/**` for enforcement

## Gotchas And Anti-Patterns

- Do not treat `cms_list_scenarios(user)` as a universal launchability check if
  it can include staff-review entries.
- Do not make `launchable=True` mean only `conformance_status == "passed"`.
  It must also mean supported profile, supported workflow, valid refs/digests,
  no active legacy shadow, and accepted conformance evidence.
- Do not infer ACES from YAML keys, package paths, branch names, scenario ids,
  or the string `polaris`.
- Do not make Polaris the adapter type system. Polaris is the proving case; the
  public seam is the ACES Shifter profile.
- Do not duplicate `enabled`, `staff_only`, scenario schema models, validation
  helpers, status enums, API envelopes, exception hierarchies, CTF bridge logic,
  or launch services.
- Do not let an ACES row shadow active legacy ids such as `polaris`, `basic`,
  or active custom scenarios before a reviewed cutover and rollback posture.
- Do not execute ACES validators, package scripts, Terraform, Docker, cloud
  CLIs, SSH, or SSM from CMS, CTF, or Mission Control request paths.
- Do not log or expose raw package bodies, flags, credentials, presigned URLs,
  generated scripts, terminal URLs, provider payloads, or parser traces.
- Do not weaken import-linter, ADR guard, API-token scopes, persisted-spec
  validation, secret scanning, Terraform/Kubernetes/actionlint gates, or CTF
  permission checks to make ACES launchability pass.

## Non-Goals

- No ACES cutover and no reclamation of legacy `scenario_id` values.
- No replacement of legacy YAML defaults or DB custom scenarios.
- No ACES package authoring, editing, clone, delete, export, or second editor.
- No raw ACES SDL persistence in CMS.
- No new ACES-only catalog API, UI product, exception hierarchy, or access
  model.
- No new Terraform, Kubernetes, cloud, secret-delivery, env-var, or runtime
  config surface.
- No ACES orchestrator, evaluator, or participant-runtime claim beyond the
  published `provisioning-only` backend capability.
- No new Ground Control requirement for this requirement-free run.

## Validation Expectations

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation must also run the stack-native checks required
by `AGENTS.md` and `.gc/plan-rules.md` for every touched path.
