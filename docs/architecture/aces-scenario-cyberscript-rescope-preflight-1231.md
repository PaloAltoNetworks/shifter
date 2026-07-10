# ACES Scenario And CyberScript Rescope Preflight

Issue: GitHub #1231, "02 - ACES migration: re-scope scenario and
CyberScript requirements."

This note records the architecture guardrails for the rescope. It is
intentionally not an implementation plan and does not change current runtime
behavior.

ADR-027 note: legacy `cms.experiments` references in this preflight describe the
pre-removal state. Future experiment capability must use a new ACES-backed
design and must not restore the deleted app as the compatibility surface.

## Boundary

ADR-024 is the controlling architecture decision:
`docs/architecture/aces-migration-adr.md` makes ACES the target contract family,
but current Shifter behavior remains authoritative until a parallel ACES path
passes the parity gates in
`docs/architecture/aces-migration-parity-inventory.yaml`.

The rescope should make requirement text and GitHub issue disposition reflect
that boundary:

- ACES owns authored scenario and experiment meaning, published schemas,
  profiles, backend manifests, and conformance vocabulary.
- Shifter owns portal behavior, CMS/CTF services, Mission Control, user
  authorization, range lifecycle, cloud provisioning, artifacts, logs, audit,
  status, and operator runbooks.
- CyberScript compatibility is migration/archive work unless a later ADR
  explicitly grants it new canonical scope.
- No current production behavior is removed as part of this issue. Archive or
  delete language is valid only as a post-cutover disposition.

Ground Control requirement reads and GitHub issue reads were unavailable in
this sandbox during preflight. The implementation must review the live
PLAT-007, PLAT-209, PLAT-210, #620, #676, and related issue text before making
edits or dispositions. Do not infer their current wording from this note.

## Disposition Buckets

Every existing scenario, ACES, Polaris, and CyberScript issue considered by
#1231 should land in exactly one bucket:

| Bucket | Use When | Guardrail |
| --- | --- | --- |
| maintain | It protects current production Shifter behavior before ACES parity. | Keep it scoped to compatibility, bug fixes, validation, or documentation; do not extend CyberScript semantics as the long-term model. |
| migrate | It is still needed but should move to the ACES target path. | Tie it to an inventory row or ACES profile/schema gap; keep Shifter backend responsibilities separate from authored ACES semantics. |
| supersede | ADR-024 or the parity inventory already replaces the issue's direction. | Point to the controlling ADR/inventory row and create a narrower follow-up only when a concrete implementation need remains. |
| close | It is no longer aligned, duplicates current guidance, or asks for post-cutover removal before parity. | Close without removing runtime behavior; if evidence is uncertain, leave it maintain/migrate until the live issue text is reviewed. |

#620 is referenced locally as the long-term scenario-expressiveness path for
declarative composition. Treat that as migration-oriented unless the live issue
body proves it is obsolete or already superseded. #676 was not available
locally; its bucket must come from the live issue text.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| ACES migration decision | `docs/architecture/aces-migration-adr.md` / ADR-024 in `docs/adr/index.yaml` | Do not create a second migration doctrine in requirement prose or issue comments. |
| Legacy surface inventory | `docs/architecture/aces-migration-parity-inventory.yaml` | Use row ids for follow-up issue scope; the inventory is not a runtime schema or parser input. |
| Scenario loading | `cms.scenarios.loader` | Preserve scenario-id slug validation, template path containment, `yaml.safe_load`, and Pydantic `TypeAdapter(AnyScenarioTemplate)` validation. |
| Scenario registry | `cms.scenarios.registry` | Keep YAML defaults, DB customs, metadata overlays, access filtering, and collision handling in the registry boundary. |
| Scenario authoring | `cms.scenario_editor.services` facade plus `_validation`, `_persistence`, `_metadata`, `_yaml` | Do not add a second YAML parser, custom-scenario table workflow, or metadata overlay path. |
| Scenario models | `cms.models.scenarios.Scenario` and `ScenarioMetadata` | DB custom scenarios remain validated by `Scenario.to_template()` on save and use soft-delete semantics. |
| Hydration | `cms.scenarios.hydrator` | New ACES input must adapt into Shifter `RangeSpec`/`CTFRangeSpec` semantics here or at an adjacent registry/hydrator adapter boundary. |
| CMS launch | `cms.services.create_range` and scenario service facade | Keep user/agent validation, active-range checks, persisted CMS request state, audit logging, failure status, and engine dispatch. |
| Shared contracts | `shifter/shifter_platform/shared/schemas/**`, `shared.script_context`, `shared.template_vars` | Only `shared` may import CyberScript directly today. New non-DSL contracts belong in `shared` natively. |
| Persistence envelope | `shared.schemas.persistence.wrap_persisted_spec` / `unwrap_persisted_spec` and `engine.interpreter` | Do not persist raw ACES payloads or unwrapped runtime specs in CMS/engine rows. |
| Engine boundary | `engine.services` and `engine.interpreter` | ACES backend work adapts to engine services; CMS/CTF/Mission Control must not invoke cloud, Terraform, Docker, or shell provisioning directly. |
| CTF integration | `ctf.bridges` and `ctf.services.*` | CTF continues to cross into CMS through bridge/service calls, not direct scenario or engine internals. |
| Experiment execution | `cms.experiments.schemas`, `cms.experiments.orchestrator.execution_plan`, `shared.script_context.ScriptExecutionContext` | Prompt, command, S3 key, provider, and instance-id handling stays behind the existing execution-context gate. |
| API auth and scopes | `shared.api_tokens.authentication`, `shared.api_tokens.permissions.require_scope`, `shared.api_tokens.scopes` | If any DRF surface changes, use exact registered scopes; no wildcard or locally invented scope checks. |
| User auth | `shared.auth.validate_cms_authoring_user`, `threat_research_required`, CTF role helpers | Keep service-layer authorization canonical; template hiding or view-only checks are not sufficient. |
| Errors | `shared.errors`, `shared.api.errors`, `shared.exceptions.CMSError`, experiment exceptions, CTF exceptions | Translate at domain boundaries; do not add a parallel scenario/ACES exception hierarchy. |
| Logging | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | User-controlled ids use `safe_log_value`; sensitive identifiers use fingerprints or masks, not raw logs. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Future ACES imports need the same discipline as current CyberScript imports. |
| Polaris evidence | `scenario-dev/polaris/sdl/README.md`, `design/aces-sdl-validation-path.md`, `containers/images.yaml`, smoke tests | SDL is authoring evidence; image realization is backend evidence; `cms/scenarios/templates/polaris.yaml` is still the live portal template. |

## Cross-Cutting Layers

Security layers the future design must satisfy:

- Auth surface: requirement/issue rescope is documentation and tracker work.
  Any later browser authoring change must stay behind
  `threat_research_required` and `validate_cms_authoring_user`. Any later DRF
  endpoint must use `IsAuthenticatedSessionOrApiToken` plus exact
  `require_scope` gates from `shared.api_tokens.scopes`.
- Scenario input shape: scenario ids must pass the loader/editor slug
  validators; file-backed YAML must stay contained under
  `cms/scenarios/templates/`; YAML parsing uses `yaml.safe_load`; parsed
  payloads validate through the existing Pydantic scenario adapters or a
  future ACES adapter at the registry/hydrator boundary.
- ACES conformance shape: ACES SDL/profile/backend-manifest claims must pass
  ACES conformance before becoming cutover evidence. Requirement prose must
  not serve as a substitute for a parser, manifest, or conformance gate.
- Persistence shape: CMS custom scenarios use `Scenario.definition` plus
  `Scenario.to_template()` validation; range runtime specs use
  `wrap_persisted_spec`; engine rows are created by `engine.interpreter` in a
  transaction. Do not introduce unwrapped JSON blobs or duplicate spec
  discriminators.
- Command and OS exposure: experiment commands, prompts, S3 keys, provider
  assumptions, and instance ids remain mediated by `ScriptExecutionContext`.
  Tokens, credentials, flags, prompt bodies, shell text, private keys, or
  backend secrets must not be placed in process argv, issue bodies, ADR
  examples, logs, or generated reports.
- Secret and artifact handling: uploaded assets, experiment artifacts, CTF
  flags, NGFW credentials, cloud ids, and runtime config remain Shifter-owned
  storage/audit concerns. ACES rows may reference evidence classes but must
  not copy secret-bearing material.
- Error envelopes: DRF responses use `shared.api.errors`; function views and
  JSON helpers should classify/sanitize user-facing messages rather than
  returning raw `str(exc)`. Logs may include sanitized ids and row names, not
  full exception payloads that carry generated scripts, credentials, prompts,
  or flags.
- Repository validators: doc/architecture changes must pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`. Runtime Python in
  `shifter/shifter_platform` also needs Ruff and import-linter; workflow,
  Terraform, and Kubernetes paths need the stack-native checks listed in
  `.gc/plan-rules.md`.

Maintainability incumbents the implementation must build on are the table
above. The highest-risk mistake is creating parallel schemas, parser flows,
status taxonomies, or exception/logging policies around ACES instead of adding
a deliberate adapter at the existing registry/hydrator/shared-contract seams.

Extensibility seam: the one required parameter is an explicit scenario contract
or profile discriminator at the registry/hydrator boundary, for example legacy demo,
legacy CTF, and ACES Shifter profile. That discriminator must be explicit
metadata, not implicit YAML shape detection and not a Polaris-specific branch
inside Shifter core. Future variations should add profile/adapter entries
behind that seam rather than editing CMS, CTF, Mission Control, and engine
surfaces separately.

Whole-repo surfaces in scope for the future implementation:

- Ground Control requirement text for PLAT-007, PLAT-209, PLAT-210, and
  related requirement records.
- GitHub issues #620, #676, and related open scenario/CyberScript issues.
- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `docs/adr/index.yaml` and `docs/adr/exceptions.yaml` if guardrails change.
- `.ground-control.yaml`, `.gc/plan-rules.md`, `.importlinter`, and
  `scripts/check_layer_imports/layer_imports.yaml` if workflow or import
  policy changes.
- `shifter/shifter_platform/cms/scenarios/**`
- `shifter/shifter_platform/cms/scenario_editor/**`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/shared/**`
- `shifter/shifter_platform/engine/**`
- `shifter/shifter_platform/ctf/**`
- `shifter/shifter_platform/cms/experiments/**`
- `shifter/shifter_platform/mission_control/**`
- `shifter/engine/provisioner/**`
- `scenario-dev/polaris/**`
- `scripts/adr_guard/**`

## Gotchas And Anti-Patterns

- Do not remove CyberScript, current CMS scenario templates, Polaris runtime
  material, CTF behavior, experiment execution, Mission Control behavior,
  provisioner paths, artifacts, status models, or validation gates in #1231.
- Do not describe CyberScript as the future canonical extension surface.
  Compatibility is maintain/migrate/archive work unless a later ADR says
  otherwise.
- Do not encode ACES-owned semantics as private Shifter YAML fields just to
  close a requirement quickly. If ACES lacks a vocabulary, classify it as an
  ACES schema/profile gap.
- Do not make Polaris the public adapter contract. Polaris is the primary
  parity proving case, not the type system.
- Do not replace registry/hydrator validation with ad hoc shape checks,
  filename conventions, or raw dict handling.
- Do not create duplicate DTOs for range specs, scenario specs, artifacts,
  statuses, CTF scoring, or experiment lifecycle. Use `shared` contracts or
  add shared-native contracts with explicit migration notes.
- Do not add cross-layer imports around service facades. CTF and Mission
  Control must not reach into engine internals; CMS must not import CTF or
  Mission Control; engine must not import CMS.
- Do not use issue labels or milestones as the only disposition evidence.
  The issue body/comment disposition should state maintain, migrate,
  supersede, or close and cite the ADR/inventory row when applicable.
- Do not create follow-up implementation issues from broad migration anxiety.
  Create them only when the rescope identifies a concrete ACES profile gap,
  adapter, validation gate, or Shifter backend responsibility.

## Non-Goals

- Implementing ACES parsing, registry support, hydration adapters,
  conformance CLIs, backend manifests, data migrations, or runtime selectors.
- Editing live production behavior, deleting legacy code, rebaking images,
  changing CTF scoring/flags/hints, or mutating ranges.
- Replacing CyberScript during this issue.
- Creating new requirement UIDs for this requirement-free run.
- Creating or closing GitHub issues without first reviewing their live content
  and recording the bucket rationale.
- Writing a file-local implementation plan; the next implementation should use
  this note and ADR-024 as repo-wide design constraints.
