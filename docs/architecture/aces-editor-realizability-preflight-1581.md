# Scenario Editor Backend Realizability Preflight

Issue: GitHub #1581, "Surface backend realizability in the Scenario Editor."

Status: pre-implementation architecture guidance. This note does not implement
the assessment, API, editor UI, persistence, or publication gate. The GitHub
issue is the shipping contract for this requirement-free run. ADR-034 is the
governing decision; no new ADR is needed.

The source-name/version image-supply guidance in this note predates the portable
RAES artifact-requirement contract. For portable artifact requirements,
`raes-artifact-requirement-resolution-preflight-1580.md` supersedes that narrow
guidance; the authorization, API, catalog, and publication-boundary guidance
here still applies.

## Boundary

Realizability answers one question: can the selected Shifter backend realize the
requirements of this ACES scenario with the tenant's current backend-owned
supply (notably image mappings)? It is not validity, conformance, editability,
availability, audience, launchability, or proof that a range has been realized.

The current editor authors legacy `ScenarioTemplate` definitions. Registered
ACES packs are read-only catalog entries. Do not translate a legacy definition
into ACES, make ACES content editable, or claim that a legacy scenario was
checked by the ACES ledger in this issue. Legacy entries must report the
assessment as not applicable. For the current product, the ACES "save" boundary
is uniform pack registration and the editor's publication boundary is the
explicit `ScenarioMetadata.enabled` desired state. A non-realizable pack may be
saved for staff review, but must be assessed and visibly flagged before it can
be enabled. ACES authoring is a separate contract decision.

## Architecture Decisions And Guardrails

- Add one server-owned, read-only assessment contract. Its closed outcome is
  `realizable`, `not_realizable`, `indeterminate`, or `not_applicable`, with a
  stable target id and an ordered, deduplicated list of bounded gaps. Each gap
  has a stable code, category, resource address/location, and safe authored
  message. `indeterminate` must never be rendered or admitted as realizable.
- Keep expected negative results in a successful typed response. A
  non-realizable scenario is not an HTTP exception. Authentication, malformed
  requests, missing scenarios, and internal failures still use the shared API
  error envelope.
- Use the real ACES compile/plan/validate path without applying it:
  `load_scenario`, `RuntimeManager.plan`, the execution-plan diagnostics, and
  `ShifterProvisioner.validate`. Never call `RuntimeManager.apply`, the CMS
  dispatch port, Engine range creation, a provisioner command, or a cloud API
  merely to answer realizability.
- The existing manifest declaration and independent ledger remain the only
  capability authorities. Do not copy their sets into CMS, serializers,
  TypeScript, a database row, or a new policy table. Preserve the independent
  over-claim check in `shared.aces.realization_ledger`.
- Evaluate backend-owned supply after the compiled-plan capability check.
  Reuse the tenant-managed `AcesImageMapping` registry and the provisioner's
  exact pinned/unpinned/concrete-reference/base-OS resolution rules. Today there
  is no implemented bake-recipe contract. A missing mapping may not be excused
  by README text, a filename, a pack path, or an assumed future bake; report a
  specific image-supply gap.
- Do not duplicate the pure image-matching rules in the portal. Move the
  dependency-light incumbent in
  `shifter/engine/provisioner/aces_image_resolver.py` to a shared runtime-safe
  module consumed by both the portal assessment and the provisioner, or expose
  an equivalently single canonical helper that both deployables execute. Keep
  provider-specific concrete-reference and base-image policy parameterized;
  current ACES realization is GCE and must not imply an AWS adapter exists.
- Resolve the target from server-owned deployment configuration. Reuse
  `config._runtime_env.resolve_cloud_provider` and, for GCP,
  `shared.range_instantiation_policy.evaluate_gcp_backend_admission`; never
  accept raw provider, project, bucket, backend selector, or manifest content
  from the browser. `SHIFTER_ACES_NATIVE_PROVISIONING`, conformance, access, and
  `launchable` remain separately displayed readiness/admission facts rather than
  being relabelled as capability gaps.
- Reuse the exact package trust path before compiling: source-record validation,
  containment, pack contract validation, canonical digest verification, and
  single direct SDL selection. Object-backed assessment must use the existing
  bounded immutable download/safe-extraction path. Resolution or verification
  failure is `indeterminate` or a source-integrity gap, never realizable.
- Do not put filesystem/object retrieval on the unbounded catalog-list hot path.
  The service seam must accept a bounded set of scenario ids (or one detail id)
  and avoid N+1 database queries. Any cache is derived data keyed at least by
  package digest, target/backend capability identity, parameter binding identity,
  and image-registry revision; stale cache data cannot authorize publication.
- Recompute at the authoritative mutation boundary before enabling an ACES
  entry. UI checks are advisory. A `not_realizable` or `indeterminate` result
  blocks `enabled=true` with the same typed gaps; disabling and staff-review
  persistence remain allowed. Do not overload `ScenarioMetadata`, `launchable`,
  or conformance status to store the result.
- Default parameter values may be assessed through ACES. A parameterized pack
  without a complete selected binding is `indeterminate`, not universally
  realizable. Do not enumerate a run matrix or expose defaults/allowed values;
  future run selection passes a validated binding identity through the same
  assessment seam.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Pack identity and trust | `cms.scenarios.pack_validation`; `shared.aces.package_loader.resolve_pack_root` / `resolve_pack_scenario_path`; `shared.aces.object_source.stage_object_pack` | Use the same containment, size, immutable-object, upstream-contract, digest, and SDL-selection gates as launch. |
| ACES planning | `shared.aces.package_loader`; ACES `load_scenario` and `RuntimeManager.plan` | Factor a no-dispatch assessment seam beside launch; do not add a CMS parser/compiler. |
| Capability and evidence | `shared.aces.manifest`, `runtime_target`, `composition_envelope`, `realization_ledger`, `domain_topology`, `network_family` | Use execution-plan diagnostics plus `ShifterProvisioner.validate`; never infer support from catalog fields or manifest membership alone. |
| Backend/image supply | `engine.services._aces_image`, `engine.models.AcesImageMapping`, provisioner `aces_image_resolver` and `aces_gce_image` | Query enabled mappings in bulk and execute one shared pure matching policy; do not reproduce exact/fallback/concrete/base-OS rules. |
| Target selection | `config._runtime_env`, `shared.range_instantiation_policy`, `settings.CLOUD_PROVIDER` | Derive the current target server-side and fail closed on an unsupported/denied adapter. |
| Catalog concepts | `cms.scenarios.registry`, `catalog_presentation`, `run_capability`, `ScenarioMetadata` | Add a bounded read projection without changing source policy, access overlays, conformance, or launchability. Do not copy `run_capability`'s fail-soft result into a positive assessment. |
| Editor services | `cms.scenario_editor.services`, `_metadata`, and the uniform `cms.services.register_pack` boundary | Keep publication and save checks in authoritative services; views/React only orchestrate and render. |
| API and frontend | `cms.api` serializers/views/permissions; generated OpenAPI; `frontend/src/api/client.ts`, `scenarios.ts`, query client, alerts/badges/status components | One `/api/v1/cms/` contract, generated types, shared transport, and accessible non-colour status/gap presentation. |
| Errors and diagnostics | ACES `Diagnostic`; `ScenarioEditorError`/`CMSError`; `shared.api.errors`; `shared.errors`; `frontend/src/api/errors.ts` | Project bounded diagnostics into the result. Do not add an exception hierarchy or make React parse diagnostic prose. |
| Logging and audit | `RequestIDMiddleware`, `shared.log_sanitize`, `audit_scenario_change`, registration audit | Log codes/counts/sanitized ids and request correlation only. Reads need no audit event; the existing mutation emits the one audit event after admission. |
| Persistence | `AcesPackageSource`, `ScenarioMetadata`, `Scenario`, soft-delete managers and atomic service mutations | Add no realizability truth column, JSON blob, migration, or parallel scenario store. |

## Cross-Cutting Layers The Design Must Pass

- **Authentication and authorization:** keep
  `IsAuthenticatedSessionOrApiToken`, `HasCMSAuthoringActor`, exact
  `cms:authoring:read` for assessment and `cms:authoring:write` for publication,
  `cms_actor_user`, `can_edit_cms_authoring`, service-level
  `validate_cms_authoring_user`, and `CTFAccountBoundaryMiddleware`. A status
  badge or bootstrap permission is never authorization.
- **Browser/session policy:** same-origin session cookies, DRF
  `SessionAuthentication`, `CsrfViewMiddleware`, and `X-CSRFToken` through the
  shared SPA client remain authoritative for unsafe requests. Add no browser
  bearer-token storage, `csrf_exempt`, CORS relaxation, inline script, raw HTML,
  or second origin.
- **HTTP and domain shapes:** DRF serializers validate bounded ids and any
  assessment input. Generated OpenAPI types are client types, not a runtime
  trust boundary. Package-source validation, upstream pack/SDL validation, ACES
  parameter instantiation, execution-plan diagnostics, the independent ledger,
  and image-mapping validation all still run at their owning boundaries.
- **Source/filesystem/object storage:** repo refs remain under
  `ACES_PACKAGE_ROOT`; object refs use the configured package bucket/prefix,
  object preconditions, archive/download/uncompressed/entry bounds, safe
  extraction, private temporary staging, cleanup, pack identity, and digest
  checks. The request cannot provide a root, bucket, URL, credentials, or local
  path.
- **Config/env:** reuse validated `CLOUD_PROVIDER`, `GCP_RANGE_BACKEND` /
  compatibility plane parsing, `ACES_PACKAGE_ROOT`, package bucket/prefix and
  bounds, and the existing image registry. If any binding changes, keep
  `config/_env_manifest.py`, `config/env-manifest.json`, deploy renderers,
  Terraform/Helm/Kubernetes projections, and runtime inventory in parity. This
  issue needs no new setting or secret.
- **Secrets/content:** cookies, CSRF/bearer tokens, acquisition or registry
  credentials, signed URLs, SDL/package bodies, parameter values, content,
  account values, private image refs, provider responses, and generated plans
  stay out of API gaps, logs, audit JSON, URLs, static bundles, screenshots,
  schema examples, metrics, and CI output. An authorized gap may name a bounded
  authored capability/source term and resource address, not its payload.
- **OS/process exposure:** repo assessment is in-process and subprocess-free.
  Object assessment may use only the existing private bounded temp staging.
  No package code, shell, Docker, Packer, Terraform, cloud CLI, SSH, or SSM is
  executed; no SDL, plan, credential, env map, or image ref enters argv or a
  child-process environment.
- **Errors:** assessment gaps are a typed 2xx domain result.
  `shared.api.errors` remains the only non-2xx envelope, with stable safe
  messages and request ids. Never expose raw parser/Pydantic/ACES/storage/SQL/
  provider exceptions, local paths, stack traces, or arbitrary `str(exc)`.
- **Observability and audit:** correlate by request id and record target id,
  outcome, stable gap codes, counts, duration, and cache hit/miss if applicable.
  Sanitize scenario ids and never log definitions or authored values. Read-only
  checks do not invent an audit vocabulary; successful registration/metadata
  mutations retain their existing single strict audit path.
- **Import/runtime boundaries:** ACES tooling remains confined to
  `shared.aces`; CMS calls public CMS/Engine/shared services; the separately
  deployed provisioner consumes dependency-light shared policy only. Preserve
  `.importlinter`, layer-import checks, ADR guard, OpenAPI drift checks, and
  frontend quality gates.

## Extensibility Seam

The seam is an assessment of `(scenario package identity, run-binding identity,
server-selected target identity, backend supply revision)`. Target capability
checking and backend supply checking are separate contributors to one ordered
gap result. The next backend or a future bake-recipe resolver supplies another
server-registered target/supply adapter; it does not add provider conditionals
to React, CMS views, catalog models, or ACES SDL parsing. The browser may request
only an allowlisted stable target id if multi-target preview is later added; it
never supplies provider configuration.

## Whole-Repo Scope

The later implementation must evaluate together:

- ADR-024, ADR-031, ADR-032, ADR-034 and the #1563, #1578, #1579, and #1371
  preflights;
- `shared/aces/{manifest,runtime_target,composition_envelope,
  realization_ledger,domain_topology,network_family,package_loader,
  object_source,runs}.py`;
- `cms/scenarios/{pack_validation,registry,catalog_presentation,
  run_capability}.py`, `cms/services/_content_ingestion.py`,
  `cms/scenario_editor/**`, and `cms/models/scenarios.py`;
- `engine/services/_aces_image.py`, `engine/models/_aces.py`, and provisioner
  `aces_plan.py`, `aces_image_resolver.py`, `aces_gce_image.py`,
  `aces_range_ops.py`, plus their parity and resolver tests;
- `cms/api/{serializers,views,permissions,urls}.py`, the committed OpenAPI
  artifact/generated TypeScript, `frontend/src/api/{client,errors,scenarios}.ts`,
  and `frontend/src/features/scenario-editor/**`;
- `config/_runtime_env.py`, `_aces_settings.py`, `_env_manifest.py`,
  `env-manifest.json`, `shared/range_instantiation_policy.py`, middleware,
  browser policy, deployment runtime renderers, and package/object-storage
  configuration;
- `.importlinter`, `scripts/check_layer_imports/**`, `scripts/adr_guard/**`, and
  existing backend/API/frontend/Playwright quality workflows.

## Gotchas And Anti-Patterns

- Do not equate `launchable`, `enabled`, conformance `passed`, pack validity, or
  a declared manifest term with realizability.
- Do not report legacy YAML/DB scenarios as ACES-realizable, and do not add an
  implicit legacy-to-ACES translator to make the badge green.
- Do not call `apply`, dispatch, persist a range, or probe a live guest/cloud to
  perform an authoring check.
- Do not use the manifest as its own evidence ledger or derive the independent
  ledger from it.
- Do not duplicate the ACES schema, diagnostics, image registry, image matching,
  target selector, source/profile allowlists, API envelope, exceptions, audit
  path, or frontend transport.
- Do not treat zero images as failure or success. Source-less nodes still need a
  backend base image; authored sources require an exact permitted resolution.
- Do not infer a bake recipe from prose or files. Recipe support does not exist
  until a versioned pack contract and a trusted data-only bake path land.
- Do not let `run_capability`'s fail-soft `resolvable=False` become a positive or
  final answer; realizability must distinguish a proven gap from inability to
  assess.
- Do not persist mutable realization truth in `AcesPackageSource.provenance`,
  `Scenario.definition`, `ScenarioMetadata`, audit JSON, or range config.
- Do not fan out unbounded object downloads, SDL parses, or per-node mapping
  queries from catalog list rendering.
- Do not return raw diagnostic strings and ask React to parse them. Project
  stable codes/locations/messages once at the server boundary and render them as
  text with keyboard/screen-reader-accessible, non-colour-only status.

## Non-Goals And Implementation Boundaries

- No ACES authoring/edit/clone/delete/export, legacy-to-ACES conversion, or
  replacement of the current legacy scenario schema.
- No entitlement, marketplace, acquisition, signing, package-upload, or
  conformance workflow.
- No image bake recipe schema, bake worker, image promotion/distribution,
  provider image existence probe, or registry credential flow.
- No new backend manifest/profile, AWS ACES realization adapter, GDC live-fire
  approval, substrate redesign, or runtime realization evidence.
- No new scenario/workflow status, draft table, realizability persistence model,
  migration, feature flag, environment variable, secret, task queue, event, or
  audit vocabulary.
- No weakening of launch-time digest, plan, image, provisioner, or product
  admission checks. Editor assessment is early feedback, not a replacement for
  any runtime gate.
