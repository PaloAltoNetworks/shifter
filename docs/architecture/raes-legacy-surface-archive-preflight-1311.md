# RAES legacy-surface archive preflight

Issue: GitHub #1311, "ACES migration: archive legacy scenario, CyberScript,
and Polaris surfaces after cutover."

Status: implemented hard-cut guidance. The repository cutover archives the
legacy runtime and authoring surfaces. No live or development Shifter
deployment existed when the cut was made, so real AWS/GCP validation is not
claimed here; it is the final #1319 child, #2043.

## Authority and gate

The issue's ACES names and parity-row ids are historical locators. The accepted
current contract authority is RAES, governed by
`docs/architecture/raes-migration-adr.md` (ADR-024) and ADR-031/032/034/043 in
`docs/adr/index.yaml`. The repository hard cut is consistent with that decision;
ADR acceptance and repository tests are still not live deployment evidence. Do
not rename historical migrations, dated
evidence, changelog entries, or inventory row ids merely to make the cleanup
look current.

The repository evidence for the code cut is the canonical digest-bound Polaris
pack, its trusted inbox registration/conformance path, the unconditional RAES
catalog and dispatch seam, negative-authority tests, and the absence of legacy
package, authoring, route, deployment-selector, and workflow paths. Deployment
evidence remains deliberately out of scope for this issue because there is no
tenant against which it can be produced.

The removed `/api/v1/cms/scenario-editor/` namespace and
`Bootstrap.feature_flags` projection are recorded as the exact #1311
whole-feature retirement in `openapi/v1.retirements.json` under ADR-024 and the
ADR-040 process. The SPA now uses the additive canonical
`/api/v1/cms/scenarios/` detail, metadata, and realizability routes. No legacy
route, redirect, response alias, or rollout flag remains as a compatibility
surface.

ADR-031-R6 now records the same hard-cut posture as ADR-024: there is no
in-process selector or same-schema compatibility rollback. A design note,
enabled flag, or generic backend validation run is not deployment proof.

## Archive boundary

"Archived" means unreachable from imports, package initialization, catalog
projection, loaders, authoring APIs, launch/teardown dispatch, provisioner
plans, image pipelines, operator commands, deployment workflows, and live
validation. Moving files to another directory while any of those paths still
consume them is not archival.

The four issue buckets have these boundaries:

| Bucket | Boundary before archive/delete |
| --- | --- |
| `cyberscript.shared-reexports` | `shared/__init__.py` may become inert only after symbol/import tests prove no caller relies on its root exports. Imports of `shared.*` execute the package initializer, so this is a runtime dependency even without `from shared import ResourceStatus`. Keep `.importlinter` and `scripts/check_layer_imports` as the enforcement owners. |
| `cyberscript.schema-shims` | This is not a bulk-delete bucket. RAES-authored semantics belong only in the released RAES contract/profile. Shifter lifecycle, authorization, CTF, Mission Control, status, and operation-input contracts remain Shifter-owned. A legacy `RangeSpec`, scenario template, persistence wrapper, enum, message, or exception may disappear only with its last live producer and consumer; do not copy it into a second "RAES compatibility" schema. |
| `scenario.yaml-defaults` / `polaris.portal-template` | Removing the seven YAML files is insufficient while `cms.scenarios.loader`, `registry`, `legacy_ids`, `hydrator`, `Scenario`, `ScenarioTemplate`/`CTFScenarioTemplate`, the scenario editor, or `create_range` can still produce or launch the same legacy semantics. If #1311 remains limited to files and cannot retire that authority chain, it cannot claim the no-dual-authority acceptance criterion. Historical database rows require an explicit inert-retention or removal decision; they must not be silently relabeled as RAES. |
| Polaris standalone/content/runtime evidence | Separate authored source and provenance (`scenario-dev/polaris/sdl/**`, required design/provenance, and content bytes incorporated by a digest-bound RAES pack) from generated/live material. Standalone Terraform/scripts, legacy package manifests, bake/bootstrap assets, smoke harnesses, operator runbooks, and generated reports are removable only after the current RAES pack and out-of-tree verification evidence replace their safety property. Never delete authored inputs merely because a generated image exists. |

Polaris runtime authority extends beyond the two directories named in the
issue. The dependency inventory must include
`shifter/engine/provisioner/plans/polaris_range_bootstrap.py` and
`_polaris_scripts*.py`, Polaris packer profiles/scripts, AMI/SSM/IAM bindings,
`scripts/ctfd-workshop/sync_polaris_*`, portal and provisioner Docker build
contexts, UAT/operator docs, `.github/quality-path-filters.yaml`,
`.pre-commit-config.yaml`, Dependabot, and Terraform validation inventory.
Deleting `scripts/polaris-aws-range/**` while those consumers still treat its
artifacts or AMIs as current only hides dual authority.

## Canonical incumbents to reuse

| Concern | Canonical incumbent and required reuse |
| --- | --- |
| RAES authored contract | Exact released RAES pair and the single `shared.raes` import boundary from ADR-024/031/032. Do not fork SDL, plan, profile, or conformance models in Shifter. |
| Package/catalog authority | `RaesPackageSource`, `ScenarioMetadata`, `cms.scenarios.pack_validation`, inbox/registration services, `shared.raes.package_loader`, `cms.scenarios.registry`, and realizability/publication gates. Another scenario varies by package identity, `source_kind`, `contract_kind`, and `contract_profile`; it does not add a scenario-specific loader. |
| Launch and lifecycle | `cms.services.create_range_dispatch`, RAES dispatch port, `engine.services`, generation-fenced `OperationInput`, persisted `range_config.kind`, and the provisioner RAES service. Existing ranges select teardown from persisted kind, never from the current catalog/config value. |
| Persistence and events | Existing CMS/Engine range and request records, RAES operation/participant sidecars, `RangeEventOutbox`, operation-result appliers, `apply_range_status`, and `reconcile_range_events`. Preserve terminal historical truth; do not rewrite old nested bytes or versions as RAES. |
| Authorization | `shared.auth`, `CMS_READ_PERMISSIONS` / `CMS_WRITE_PERMISSIONS`, exact API-token scopes, CTF ownership/services, and Mission Control actor/participant permissions. Removing a UI row is not authorization or route retirement. |
| Errors | `cms.exceptions.CMSError`, `shared.api.errors`, `shared.errors`, existing RAES boundary exceptions, and provisioner typed errors. Delete obsolete translations with their boundary; do not create an archive/RAES exception hierarchy. |
| Logs and audit | `shared.log_sanitize`, provisioner `log_redact`, request/range correlation ids, and existing audit services. Log ids, counts, contract/profile versions, digests, and outcomes only. |
| Configuration | `config/_raes_settings.py`, `config/env-manifest.json`, Helm/Kustomize runtime env, Terraform variables/SSM projection, EC2 bootstrap, and `scripts/portal-deploy/deploy_portal.sh`. A selector/gate is removed fleet-wide with its validators and tests; no handler-local env read or old-key fallback remains. |
| Repository workflow | `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard`, quality ownership, secret hygiene, workflow routing, Terraform/Kubernetes validators, and the parity-inventory path-integrity rule. Update canonical path classifiers when a surface disappears; do not weaken or bypass them. |

## Cross-cutting security and host boundaries

- **Auth surface:** catalog reads and authoring mutations continue through the
  existing session/API-token principal, CMS authoring actor, exact read/write
  scopes, and service-layer ownership checks until the route is removed.
  Archived endpoints are removed, not left as unauthorised compatibility
  stubs or hidden UI.
- **Input/shape gates:** legacy ids retain slug validation, enumerated-path
  containment, `yaml.safe_load`, and Pydantic validation for as long as any
  legacy loader remains. Current RAES content must pass upstream environment-
  pack validation, canonical digest/inventory verification, containment,
  exact contract/profile allowlists, realizability/publication, SDL
  compilation, backend conformance, and the provisioner's exact plan and
  operation-input parsers. Cleanup must remove validators with their last
  producer/consumer, never leave two validators for one live shape.
- **Secret/content handling:** repository archives and evidence must not copy
  raw package bodies, challenge flags, credential fixtures, private keys,
  bearer/admin tokens, presigned URLs, terminal/Guacamole URLs, provider
  output, generated scripts, or operator/participant data into a new archive
  bundle. `scenario-dev/polaris/cleanup-plan.md` and legacy content are
  sensitive review surfaces; retention is by ordinary reviewed source history,
  not by generating a second tarball or evidence dump. Existing gitleaks,
  secret-hygiene, live-cloud-identifier, and generated-artifact checks remain
  authoritative.
- **Environment binding:** RAES package roots, buckets, prefixes, size bounds,
  retention, and any remaining capability settings stay typed and represented
  in the env manifest and every deployed renderer. Secret values stay in the
  existing secret/provider channel. Do not put values in docs, process argv,
  Terraform command lines, or cleanup reports.
- **OS/process exposure:** request-time code continues to dispatch by bounded
  ids through structured task argv and the operation envelope. It must never
  execute package-supplied commands or assemble shell fragments from SDL,
  legacy YAML, content packages, CTFd data, or filenames. Archival must remove
  live entry points to standalone Terraform/AWS/SSM/SSH tooling rather than
  wrapping them in another command.
- **Error envelope and observability:** API failures use the existing bounded
  DRF envelope and fixed/sanitized user messages; CLI/provisioner diagnostics
  use their existing typed errors and redaction. Never return or log raw parser,
  filesystem, cloud, Terraform, SSH, SSM, package, or provider exceptions.

## Extensibility seam

The forward seam is the existing RAES environment-pack identity and catalog
record: `scenario_id`, `source_kind`, `contract_kind`, `contract_profile`,
package/version/digest, conformance status, and `ScenarioMetadata`. A future
scenario, provider, or package transport extends the existing allowlists and
backend/profile contracts. It must not require restoring the legacy YAML
loader, adding a per-scenario branch, or introducing a generic runtime
"archive source".

The evidence seam is likewise parameterized by package/scenario id, digest,
profile, provider/environment, release SHA, and verification-plugin version.
Polaris is an acceptance case, not a type or backend mode. Repository cleanup
itself needs no new service, DTO, repository, schema, persistence table,
exception family, workflow, or runtime toggle.

## Gotchas and anti-patterns

- Do not interpret the ACES-to-RAES name cutover as proof that the legacy
  scenario/Polaris cutover occurred.
- Do not remove only YAML defaults while DB-authored `Scenario` rows and the
  editor/hydrator remain a live second scenario language.
- Do not move CyberScript models wholesale into `shared`; retain only proven
  Shifter-owned contracts, natively and without compatibility aliases.
- Do not delete schema/persistence readers needed by queued work, terminal
  historical rows, reversible migrations, or teardown. Drain and database
  evidence must precede reader removal.
- Do not treat unit tests, generic RAES backend validation, a standalone
  Polaris range, a baked AMI, or presence of a selector as default-cutover
  evidence.
- Do not archive authored SDL/provenance with generated runtime material, or
  treat legacy content-package manifests as a current RAES environment pack.
- Do not retain old routes, env aliases, import aliases, redirects, validation
  fallbacks, feature flags, or operator commands "just in case" under the
  hard-cut posture.
- Do not weaken import, ADR, secret, SAST, Terraform, Kubernetes, smoke, or
  quality-ownership gates to accommodate deleted paths; update their canonical
  classifications and tests.

## Deployment-validation boundary

- This change does not claim a live range, image bake, CTFd mutation, tenant
  deployment, or provider parity result. #2043 owns those AWS/GCP checks after
  a deployable tenant exists.
- No rewrite of historical ACES names, migrations, changelog records, or parity
  row ids where retention preserves factual history.
- No redesign of Shifter authorization, CTF, Mission Control, status/event,
  operation-input, cloud realization, artifact, or audit models.
- No new archive framework, schema, validator, exception hierarchy, data store,
  feature flag, workflow, or compatibility layer.
- No legacy catalog, authoring, or launch path remains runtime authority.

## Validation expectation

For the implementation change:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Any later runtime change under `shifter/shifter_platform` must also run the
repository's Ruff, import-linter, and layer-import checks. Workflow, Terraform,
Kubernetes, packer, provisioner, and Polaris-path changes inherit the
path-specific checks in `AGENTS.md`, `.gc/plan-rules.md`, and quality ownership.
