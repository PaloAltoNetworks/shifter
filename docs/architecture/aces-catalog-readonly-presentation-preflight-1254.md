# ACES Catalog Read-Only Presentation Preflight

Issue: GitHub #1254, "13 - ACES migration: expose read-only ACES catalog
fields in CMS API and scenario editor."

Status: pre-implementation architecture guidance. This note does not implement
API endpoints, template changes, serializers, editor actions, ACES authoring,
runtime adapters, or cutover behavior.

Requirement context: requirement-free run. The GitHub issue and the parent
boundary note `docs/architecture/aces-catalog-package-boundary-preflight-1232.md`
are the implementation contract.

## Boundary

ADR-024 remains the controlling migration decision:
`docs/architecture/aces-migration-adr.md` keeps current Shifter behavior
authoritative until the parallel ACES path passes parity and cutover gates.

The package-source persistence and launchability incumbents are already
defined by:

- `docs/architecture/aces-package-source-catalog-preflight-1252.md`
- `docs/architecture/aces-registry-validation-launchability-preflight-1253.md`
- `cms.models.AcesPackageSource`
- `shared.schemas.aces_package_source.validate_package_source`
- `cms.scenarios.registry`

Issue #1254 is presentation only: expose the existing ACES package-backed
catalog projection through the CMS API and the scenario editor as read-only
catalog metadata. It must not add an ACES authoring editor, a package export
format, a second catalog, a second access model, or launch logic outside the
registry/service seams.

## Architecture Decisions

- Keep one catalog projection. API and scenario-editor presentation must build
  on `cms.scenarios.registry` and the `cms.services` facade rather than reading
  `AcesPackageSource` directly from templates, DRF views, CTF, or Mission
  Control.
- Treat ACES entries as read-only package-source catalog records. The editor
  may show identity, package/version/digest, lock digest, provenance summary,
  conformance status/report ref, access state, and launchability state. It must
  not offer edit, YAML edit, clone, delete, or export actions for ACES entries.
- Preserve legacy editor behavior. YAML defaults and DB custom scenarios keep
  the current create, edit, clone, delete, import, validate, and export flows
  through `cms.scenario_editor.services`, `_validation`, `_persistence`,
  `_metadata`, and `_yaml`.
- Keep `ScenarioMetadata` as the access overlay. Staff may toggle `enabled` and
  `staff_only` for ACES entries through the existing metadata service path, but
  package-source rows must not grow duplicate access fields.
- Keep launchability authoritative in the registry. API serializers and
  templates may display the projected `launchable` value; they must not
  recompute it from `conformance_status`, package refs, profile strings, or UI
  flags.
- Add a catalog-detail presentation seam before widening legacy detail helpers.
  Existing `get_scenario_detail()`, `export_scenario_yaml()`,
  `structural_definition_from_detail()`, and clone/edit/delete flows are legacy
  template surfaces. ACES detail display should use the unified catalog
  projection or a narrow presentation helper so ACES records are not converted
  into legacy YAML definitions by accident.
- API additions stay inside the canonical `/api/v1/cms/` DRF namespace, reuse
  `CMS_READ_PERMISSIONS` and `CMS_WRITE_PERMISSIONS`, and return the shared DRF
  error envelope. Do not add ACES-only scopes or ad hoc JSON error shapes for
  this slice.
- Expose an allowlisted response shape. The presentation DTO may include
  catalog identity, `scenario_type`, source/contract/profile, package ref,
  package version, package digest, lock ref/digest, provenance summary,
  conformance status/report ref, `enabled`, `staff_only`, and `launchable`.
  It must not include raw ACES SDL, imported module bodies, generated content,
  flags, credentials, presigned URLs, runtime config, provider diagnostics, or
  parser/conformance payload bodies.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | ADR-024 in `docs/architecture/aces-migration-adr.md` | Keep ACES parallel, read-only, and parity-gated. |
| Parent package boundary | `docs/architecture/aces-catalog-package-boundary-preflight-1232.md` | Do not widen #1254 into persistence, authoring, or launch adapter work. |
| Package-source persistence | `cms.models.AcesPackageSource` | Read its provenance-only fields through the projection; do not add access booleans or payload bodies. |
| Package-source validation | `shared.schemas.aces_package_source` | Trust the shared contract for bounded refs/digests/provenance and widen it centrally only for new source/profile values. |
| Catalog projection and launchability | `cms.scenarios.registry`, `ScenarioWorkflow`, `get_catalog_entry`, `list_all_scenarios`, `list_launchable_scenarios`, `is_scenario_launchable` | Present registry output; do not duplicate filtering or launchability rules in serializers/templates. |
| Metadata overlay | `cms.models.ScenarioMetadata`, `cms.scenario_editor._metadata.update_metadata` | Toggle `enabled`/`staff_only` through the existing service/audit path for every catalog source. |
| Scenario editor service facade | `cms.scenario_editor.services` plus `_post_helpers`, `_crud`, `_yaml`, `view_support` | Keep legacy authoring flows behind the facade; add read-only ACES presentation beside them. |
| API permissions | `cms.api.permissions.CMS_READ_PERMISSIONS`, `CMS_WRITE_PERMISSIONS`, `cms_actor_user` | Exact CMS authoring scopes and actor resolution remain canonical. |
| API errors/schema | `shared.api.errors`, `config/_drf_settings.py`, `shared/api/schema.py` | Use the shared envelope and DRF/OpenAPI conventions. |
| User auth | `shared.auth.can_edit_cms_authoring`, `validate_cms_authoring_user`, `threat_research_required` | UI visibility is not authorization; service and DRF gates stay server-side. |
| Errors | `cms.exceptions.CMSError`, `cms.scenario_editor.ScenarioEditorError`, `shared.errors`, `shared.api.errors` | Do not add an ACES presentation exception hierarchy. |
| Logging/audit | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint`, `risk_register.models.AuditLog` | Log sanitized ids, status, and digests only; audit access toggles without package payloads. |
| Import boundaries | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Keep CTF/Mission Control on `cms.services`; keep ACES contracts in `shared` or CMS seams. |

## Cross-Cutting Layers

- Auth surface: scenario-editor browser views remain behind
  `threat_research_required`; scenario-editor service mutations remain behind
  `validate_cms_authoring_user`; DRF work uses
  `IsAuthenticatedSessionOrApiToken`, `HasCMSAuthoringActor`, and exact
  `cms:authoring:read` / `cms:authoring:write` scopes. If a non-authoring
  catalog response is exposed later, it must use `list_all_scenarios(user=...)`
  or `list_launchable_scenarios(user=..., workflow=...)`, not the staff-review
  projection.
- Shape validation surface: legacy YAML stays behind slug validation, path
  containment, `yaml.safe_load`, and Pydantic `AnyScenarioTemplate` validation.
  ACES presentation consumes already-validated package-source rows and must
  not parse raw ACES SDL or infer source type from YAML shape.
- Scenario access surface: staff review may include non-launchable ACES rows.
  Non-staff and launch-facing responses must preserve `enabled`,
  `staff_only`, and launchability filtering through the registry/service layer.
- Secret-handling surface: package provenance, conformance diagnostics, CTF
  flags, private keys, bearer tokens, presigned URLs, generated scripts,
  provider payloads, and rendered runtime config must not appear in logs, audit
  rows, API responses, templates, OpenAPI examples, fixtures, process argv, env
  files, or CI output.
- Error-envelope surface: DRF responses use `shared.api.errors`; HTML views
  use `scenario_editor.view_support`. Do not serialize parser stack traces,
  package snippets, YAML bodies, storage-provider payloads, ownership internals,
  or raw model validation exceptions to clients.
- Persistence surface: `AcesPackageSource` remains provenance-only;
  `Scenario.definition` remains legacy-only; `ScenarioMetadata` remains the
  only access overlay; hydrated runtime state stays in existing persisted-spec
  envelopes.
- OS/process exposure: read-only catalog inspection must not execute ACES
  tools, shell scripts, Terraform, Docker, cloud CLIs, SSH, SSM, or storage
  fetches in request paths. It may display stored refs/digests/status only.
- Config/env surface: #1254 should not add settings, env vars, Terraform
  variables, Kubernetes manifests, buckets, prefixes, or runtime config. A
  later source variation must use the existing config/env-manifest and storage
  adapter patterns.
- Import-boundary surface: CMS may use `shared` and its own registry/editor
  modules. CTF and Mission Control continue to use `cms.services` and bridge
  facades. Direct ACES imports outside `shared` require a later ADR/import-rule
  change.
- Workflow validators: docs/architecture changes must pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`. Runtime Python
  changes under `shifter/shifter_platform` also require the Ruff and
  import-linter checks from `.gc/plan-rules.md`.

## Extensibility Seam

The required seam is a presentation DTO over the unified catalog entry, with
source-specific metadata grouped under explicit keys rather than inferred from
legacy fields:

- `source_type` / `scenario_type`: legacy default, legacy custom, or ACES;
- `contract_kind` and `contract_profile`: initially ACES/Shifter, not Polaris;
- `source_kind`: repo-managed versus object-backed package source;
- `workflow_purpose`: staff review versus user-visible listing versus launch
  selection;
- `evidence_identity`: package ref/version/digest, lock ref/digest,
  conformance status/report ref, and bounded provenance summary.

Future ACES profiles, object-backed packages, or SPA consumers should add
fields behind this DTO and the registry/service projection. They should not
require edits in CTF event forms, Mission Control templates, engine models,
provisioner internals, or legacy YAML export code.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-catalog-package-boundary-preflight-1232.md`
- `docs/architecture/aces-package-source-catalog-preflight-1252.md`
- `docs/architecture/aces-registry-validation-launchability-preflight-1253.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `shifter/shifter_platform/shared/schemas/aces_package_source.py`
- `shifter/shifter_platform/cms/models/scenarios.py`
- `shifter/shifter_platform/cms/scenarios/registry.py`
- `shifter/shifter_platform/cms/services/_scenarios.py`
- `shifter/shifter_platform/cms/scenario_editor/**`
- `shifter/shifter_platform/templates/scenario_editor/**`
- `shifter/shifter_platform/cms/api/**`
- `shifter/shifter_platform/shared/api/errors.py`
- `shifter/shifter_platform/shared/api_tokens/scopes.py`
- `shifter/shifter_platform/shared/auth.py`
- `shifter/shifter_platform/ctf/bridges.py` and CTF event selection tests only
  for launchability regressions
- `shifter/shifter_platform/mission_control/**` only for existing
  launchable-selection and non-launchable rejection regressions
- `.ground-control.yaml`, `.gc/plan-rules.md`, `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`, and `scripts/adr_guard/**`
  for enforcement

## Required Tests

- API serialization exposes the allowlisted ACES catalog fields and never raw
  package bodies, imported modules, generated content, flags, credentials,
  presigned URLs, provider payloads, parser traces, or runtime config.
- API permission tests cover session actors, API tokens with exact CMS read or
  write scopes, missing scopes, malformed bearer tokens, and the shared DRF
  error envelope.
- Scenario-editor tests cover read-only ACES detail/list presentation, metadata
  toggles for ACES entries, and the absence of edit, YAML editor, clone,
  delete, and export actions for ACES entries.
- Non-staff/user-facing catalog tests cover `enabled`, `staff_only`, and
  launchability filtering through the registry/service layer.
- Legacy YAML defaults and DB custom scenario create/edit/clone/delete/export
  tests remain unchanged.
- Redaction tests cover provenance/report refs and prove secret-like
  provenance keys or values cannot reach API/template responses.

## Gotchas And Anti-Patterns

- Do not call `export_scenario_yaml()`, `structural_definition_from_detail()`,
  clone, edit, or delete helpers for ACES entries.
- Do not make `get_scenario_detail()` polymorphic by stuffing ACES records into
  legacy YAML/detail shape unless the legacy authoring/export call sites are
  split first.
- Do not use `conformance_status == "passed"` as the UI/API definition of
  launchability. Carry the registry's `launchable` value.
- Do not let a staff-review listing become a launch selection list.
- Do not duplicate `enabled`, `staff_only`, source/profile allowlists,
  provenance validators, status enums, serializer schemas, API envelopes,
  exception hierarchies, or CTF bridge logic.
- Do not expose raw `provenance` as an unbounded JSON body if future validation
  widens it; keep presentation on a bounded summary contract.
- Do not add an ACES-only CMS API, scenario editor, access table, authoring
  editor, export format, launch path, audit path, or OpenAPI dialect.
- Do not log or expose raw ACES SDL, imported modules, generated scripts,
  flags, credentials, presigned URLs, bearer tokens, provider diagnostics,
  parser traces, terminal URLs, or runtime config.

## Non-Goals

- No ACES cutover and no reclamation of legacy `scenario_id` values.
- No ACES authoring, editing, clone, delete, export, package import, or package
  upload workflow.
- No raw ACES SDL persistence or API/template exposure.
- No new package-source persistence, conformance runner, launch adapter,
  hydrator, Terraform, Kubernetes, cloud, secret-delivery, env-var, or runtime
  config surface.
- No replacement of legacy YAML defaults or DB custom scenario behavior.
- No new Ground Control requirement for this requirement-free run.
