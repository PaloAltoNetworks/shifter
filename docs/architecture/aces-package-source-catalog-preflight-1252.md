# ACES Package-Source Catalog Persistence Preflight

Issue: GitHub #1252, "11 - ACES migration: implement package-source catalog
persistence and projection."

Status: pre-implementation guidance.

Requirement context: requirement-free run. The GitHub issue and the parent
boundary note `docs/architecture/aces-catalog-package-boundary-preflight-1232.md`
are the implementation contract.

This note narrows the #1232 boundary for the first persistence slice. It is not
an implementation plan and does not change runtime behavior.

## Decisions

- Keep one catalog projection. ACES package-source rows are a third source for
  the existing `cms.scenarios.registry` projection, beside YAML defaults and
  active DB custom `Scenario` rows. They are not a separate ACES CMS, API
  dialect, access model, editor workflow, launch path, or exception hierarchy.
- Keep `ScenarioMetadata` as the only `enabled` / `staff_only` overlay. ACES
  package-source persistence must not add duplicate access booleans, even if
  the source package has its own lifecycle or conformance status.
- Use a small provenance-only sidecar if DB-backed registration is needed. The
  row may store `scenario_id`, an explicit source/contract discriminator,
  `contract_profile`, `package_ref`, `package_version`, `package_digest`,
  `lock_ref`, `lock_digest`, bounded provenance JSON, conformance status or
  report reference, actor, and timestamps. It must not store raw ACES SDL,
  imported module bodies, generated content, hydrated specs, flags, credentials,
  runtime config, presigned URLs, tokens, or provider diagnostics.
- Prevent active legacy `scenario_id` shadowing fail-closed. During the parallel
  phase an active ACES row must not make a catalog id launchable or selectable
  when the same id is already a YAML default or an active DB custom
  `Scenario`. Cross-source collision checks must cover both
  `cms.scenarios.loader.list_scenario_ids()` and `Scenario.objects` because a DB
  constraint cannot see checked-in YAML files.
- Preserve legacy source behavior. YAML defaults stay code-managed under
  `cms/scenarios/templates/*.yaml`, and DB custom scenarios keep
  `Scenario.definition` validated by `Scenario.to_template()`. Do not make
  `Scenario.definition` polymorphic for ACES.
- Make launchability explicit projection state. Visibility/access still comes
  from `ScenarioMetadata`, while launchability comes from contract/profile
  support and conformance readiness. Staff may need to see a non-launchable
  ACES entry for review; range creation and CTF event selection must reject it.
- Use an explicit contract/profile discriminator. Do not infer ACES versus
  legacy by probing YAML keys, package paths, or Polaris-specific strings.
- Keep all runtime handoff behind the existing CMS/engine seams. Any
  ACES-derived runtime spec must enter through the registry/hydrator adapter,
  `cms.services.create_range`, `wrap_persisted_spec`, and engine services.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md` and #1232 preflight | Do not restate or widen the ACES migration boundary in model docs. |
| Inventory evidence | `docs/architecture/aces-migration-parity-inventory.yaml` rows `scenario.yaml-defaults`, `scenario.any-template-union`, `scenario.hydration-range-spec`, `polaris.content-packages`, `validation.aces-manifest-conformance` | Cite row ids in tests/docs; do not turn inventory rows into runtime schema. |
| Catalog projection | `cms.scenarios.registry` | Extend the unified projection and existing metadata overlay/filtering. |
| Legacy validation | `cms.scenarios.loader`, `cms.scenarios.schema`, `Scenario.to_template()` | Keep slug validation, path containment, `yaml.safe_load`, and Pydantic validation intact for legacy sources. |
| Metadata overlay | `cms.models.ScenarioMetadata` | Apply the same overlay to ACES entries; do not duplicate access fields. |
| Scenario editor | `cms.scenario_editor.services` and its `_validation`, `_persistence`, `_metadata`, `_yaml` modules | ACES entries are read-only package-source records unless a later issue scopes package authoring/export. |
| Launch path | `cms.scenarios.hydrator`, `cms.services.create_range`, `engine.services`, `shared.schemas.persistence.wrap_persisted_spec` | Do not bypass hydration, CMS request/range persistence, audit, status, or engine dispatch. |
| API permissions | `cms.api.permissions`, `mission_control.api.permissions`, `shared.api_tokens.scopes` | Use existing CMS authoring and Mission Control actor permissions; do not create ACES-only scopes for this slice. |
| Errors | `cms.exceptions.CMSError`, `shared.exceptions`, `shared.api.errors` | Reuse current service exceptions and DRF error envelopes. |
| Logging | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Log sanitized ids, digests, status, and counts only. |
| Import boundaries | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Keep ACES contracts in `shared` or behind CMS seams; do not add direct cross-layer imports. |

## Security Layers

- Auth surface: HTML authoring changes stay behind
  `threat_research_required`; service mutations use
  `validate_cms_authoring_user`; CMS DRF additions use
  `CMS_READ_PERMISSIONS` or `CMS_WRITE_PERMISSIONS`; Mission Control listing
  and launch continue through the existing actor/lifecycle permissions.
- Shape validation surface: legacy YAML keeps its existing loader and
  Pydantic gates. ACES package-source rows need a shared-native validation
  contract for references, digests, contract/profile values, bounded
  provenance, and conformance status before they enter projection code.
- Conformance surface: a stored conformance report/status is evidence, not an
  authorization bypass. Launchability must require the accepted ACES
  parser/profile/conformance gate for the supported Shifter profile.
- Secret-handling surface: provenance and conformance payloads must reject or
  strip flags, credentials, private keys, tokens, presigned URLs, raw package
  bodies, runtime config, generated scripts, and provider diagnostics. Those
  values must not appear in logs, audit JSON, fixtures, API examples, or error
  responses.
- Config/env surface: this slice should not require new runtime environment
  variables. If a later package source introduces bucket/prefix settings, it
  must use the existing config/env-manifest pattern and storage adapters, not
  ad hoc environment reads.
- OS/process surface: catalog registration/projection must not execute package
  tools, shell scripts, Terraform, Docker, or cloud CLIs in request paths. Any
  later validator invocation must use bounded worker/service execution with
  structured argv and no secret-bearing command arguments.
- Error-envelope surface: API responses use `shared.api.errors`; HTML flows use
  scenario-editor error helpers. Do not serialize parser stack traces, package
  snippets, YAML bodies, storage-provider payloads, or internal ownership
  details to clients.
- Persistence surface: the package-source row is source/provenance state only.
  Hydrated runtime specs still live only in the existing persisted-spec
  envelope used by range creation.

## Extensibility Seam

The required seam is a data-driven package-source contract plus a registry /
hydrator adapter boundary:

- `source_kind` or equivalent identifies repo-managed versus object-backed
  package sources without changing CTF, Mission Control, or engine code.
- `contract_kind` and `contract_profile` identify the ACES/Shifter contract
  without Polaris-specific branches.
- conformance status/report fields are profile-agnostic enough for the next
  supported ACES profile.
- source resolution and conformance checking belong behind shared/CMS adapters,
  so adding object storage or a second ACES profile does not require edits in
  CTF event forms, Mission Control templates, experiment flows, or engine
  internals.

## Whole-Repo Scope

Implementation may legitimately touch:

- `shifter/shifter_platform/cms/models/scenarios.py`, a CMS migration, and
  `cms/models/__init__.py` for a DB sidecar model.
- `shifter/shifter_platform/cms/scenarios/registry.py` for unified projection,
  metadata overlay reuse, no-shadow checks, and launchability fields.
- `shifter/shifter_platform/cms/scenarios/hydrator.py` only at an adapter seam,
  not by embedding ACES parsing directly in request workflows.
- `shifter/shifter_platform/shared/**` for package-source validation contracts
  or shared import shims.
- `shifter/shifter_platform/cms/scenario_editor/**` for read-only presentation
  or metadata toggles, not package authoring.
- `shifter/shifter_platform/cms/api/**` and
  `shifter/shifter_platform/mission_control/api/ranges.py` only to expose the
  existing unified projection.
- tests under `shifter/shifter_platform/tests/scenario_editor/`,
  `tests/cms/`, and API/CTF surfaces affected by projection or launchability.

Implementation should not touch protected workflow/ADR guardrails unless the
rule itself changes. If it does, update `docs/adr/index.yaml` or
`docs/adr/exceptions.yaml` in the same change.

## Required Tests

- No-shadowing: an active ACES package-source row with a `scenario_id` matching
  a YAML default or active custom `Scenario` is rejected, hidden as a conflict,
  or otherwise prevented from becoming selectable/launchable. The test must
  cover the actual behavior selected by implementation.
- Metadata overlay reuse: `ScenarioMetadata.enabled` and `staff_only` affect
  ACES entries through the same registry path used by YAML defaults and DB
  customs.
- Provenance-only persistence: model/service tests reject raw ACES SDL, module
  bodies, generated content, hydrated specs, flags, credentials, tokens, and
  runtime config in stored package-source/provenance fields.
- Launchability/access split: disabled/staff-only behavior remains the metadata
  concern, while conformance/profile readiness controls launchability.
- Regression coverage for existing YAML defaults and DB custom scenarios stays
  green; ACES projection must not change legacy defaults.

## Gotchas And Anti-Patterns

- Do not add an ACES-only catalog endpoint, CMS app, scenario editor, access
  table, launch service, audit path, exception hierarchy, or status taxonomy.
- Do not store raw package bodies or hydrated Shifter runtime specs in the
  package-source row.
- Do not duplicate `enabled` or `staff_only` outside `ScenarioMetadata`.
- Do not infer source type by YAML shape or package path.
- Do not let active ACES records reuse `polaris` or another active legacy id
  before a deliberate cutover issue.
- Do not make Polaris the adapter type system; it is the parity proving case.
- Do not call package validators, Terraform, Docker, cloud CLIs, or shell
  scripts from CMS/CTF/Mission Control request paths.
- Do not log or expose package bodies, flags, credentials, presigned URLs,
  tokens, provider payloads, parser traces, or generated runtime config.
- Do not weaken import, ADR, API-auth, serializer, or persisted-spec gates to
  make the first ACES source row fit.

## Non-Goals

- No ACES cutover.
- No replacement of legacy YAML defaults or DB custom scenarios.
- No ACES package authoring, editing, clone, delete, or export workflow.
- No raw ACES SDL persistence in CMS.
- No runtime package execution or ACES launch adapter beyond an explicit
  registry/hydrator seam.
- No new user-facing catalog product separate from the existing projection.
- No new requirement traceability; #1252 is the source of truth for this
  requirement-free run.
