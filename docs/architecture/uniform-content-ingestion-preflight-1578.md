# Uniform Content Ingestion Preflight

Issue: GitHub #1578, "Uniform, entitlement-blind content ingestion (pack =
universal unit)."

Status: implementation guidance, reconciled with the released upstream digest
and validation contracts on 2026-07-13. Governed by ADR-034.

## Boundary

One registration operation accepts a pack that is already in the operator's
possession. Its input must not vary with whether the pack shipped in-box, came
from a public or private source, or was authored locally. Acquisition,
licensing, purchase, subscription, operator identity at acquisition, and
private-source credentials are outside this operation.

This is deliberately different from *trust* and from *resolution*. Signature
or digest verification, ACES conformance, backend realizability, and an
artifact reference are content-safety/capability facts. `source_kind` (`repo`
or `object`) is a resolver/storage fact. Neither is a provenance or entitlement
field and neither may select a different registration workflow.

## Decisions And Required Reuse

- Put registration behind the public `cms.services.register_pack` boundary and
  have every caller use it: the authenticated authoring API, operator tooling,
  and the in-box bootstrap/seed path. Do not put the transaction, validation,
  audit, or duplicate policy in views, management commands, fixtures, signals,
  migrations, or startup code.
- Define retry behavior at that service boundary. A repeat with the same
  immutable package/lock identity may be an explicit no-op; the same catalog id
  with different identity is a conflict. A bootstrap-side query-and-skip is not
  sufficient: it is racy and can silently hide drift between the shipped
  manifest and the persisted row. Package replacement/version update remains a
  separately authorized operation, never an implicit overwrite.
- Build the catalog projection on `cms.scenarios.registry`; preserve
  `ScenarioMetadata` as the sole `enabled` / `staff_only` overlay and preserve
  the registry as the sole launchability authority. Registration is not
  launchability, and a registered pack may remain review-only or
  non-realizable.
- Reuse `shared.schemas.aces_package_source.PackageSourceRecord` and
  `validate_package_source()` for the current ACES/Shifter package-source
  record, including bounded reference-only provenance. Do not store package
  bodies, imports, generated content, flags, credentials, presigned URLs, or
  runtime configuration in `AcesPackageSource`, `Scenario.definition`, audit
  JSON, or a new registration table.
- The in-box catalog must be declared as registration inputs and passed to the
  same service. `cms.scenarios.loader` remains the legacy YAML parser only; it
  must not remain a privileged catalog-registration route. Preserve its slug
  validation, path containment, `yaml.safe_load`, and
  `TypeAdapter(AnyScenarioTemplate)` while legacy YAML is supported.
- Keep legacy YAML defaults and DB custom scenarios compatible until their
  pack adaptation is deliberately scoped. Do not make `Scenario.definition`
  polymorphic, infer pack type from YAML shape/path/name, or reuse a legacy
  editor YAML import as a package importer.
- Reuse the neutral `shared.audit` boundary for a successful registration
  summary and `shared.log_sanitize` for operational logs. Record
  sanitized catalog id, contract/profile, resolver kind, digest, result, and
  request correlation only; provenance is evidence, not a raw audit payload.
  Registration changes the executable-content catalog, so its audit write is a
  safety control: use the incumbent `strict=True` mode in the same atomic unit
  as persistence so an audit failure rolls back rather than leaving an
  unaudited catalog mutation. Propagate the server-owned request id from
  `RequestIDMiddleware`; never accept audit correlation from the request body.

## Security And Runtime Gates

- **Authoring/authentication:** browser entrypoints use
  `threat_research_required`; service entrypoints use
  `validate_cms_authoring_user`; DRF uses `CMS_WRITE_PERMISSIONS` (including
  exact `cms:authoring:write` scope). No entitlement or identity check may be
  added after those authorization gates.
- **Registration shape:** validate the common registration request once at the
  service boundary. The HTTP adapter may enforce transport types and model
  length limits with `PackRegistrationSerializer`, but domain allowlists,
  reference/digest shape, and bounded provenance remain authoritative in
  `PackageSourceRecord` / `validate_package_source()` for every caller. Repo
  content uses the public `aces_scenario_packs.validate_pack` consumer API;
  persisted rows are revalidated by `cms.scenarios.registry` before
  launchability. Do not restate upstream schemas, SDL parsing, or those source
  contracts in a second DTO, model validator, or caller-specific schema.
- **Validation resource bounds:** a pack is foreign input even when its path is
  local. Bound manifest/ledger/SDL bytes, SDL file count, YAML/JSON nesting, and
  total validation work before parsing. Keep the static, subprocess-free fast
  path in the request only while it is predictably bounded; heavier
  conformance or signature work belongs in a bounded worker and must leave the
  row pending. `yaml.safe_load` prevents object construction but is not by
  itself a size, alias-expansion, or CPU budget.
- **Reference/storage:** repository references retain containment checks in
  `shared.aces.package_loader.resolve_pack_root` (and equivalent pack-root
  containment before ingestion), including symlink resolution. `package_ref`
  is always a pack root; the current Shifter profile resolves exactly one direct
  `sdl/*.sdl.yaml` entry and rejects ambiguity. The only
  filesystem root is the server-controlled `ACES_PACKAGE_ROOT` setting from
  `config/_aces_settings.py`; if its environment binding changes, keep
  `config/env-manifest.json` and runtime renderers in parity. Object-backed
  material, when #1567 supplies it, must use
  `shared.cloud.get_object_storage()` and its `ObjectStorage` protocol,
  normalized server-controlled keys, and immutable identity/digest checks. Do
  not accept arbitrary request URLs, filesystem roots, bucket names, storage
  credentials, or a client-controlled resolved path.
- **Secrets and processes:** no acquisition token, registry credential,
  presigned URL, private key, package body, rendered configuration, or provider
  diagnostic reaches logs, audit, API responses, docs, CI output, environment
  files, or process argv. Registration and request-time validation must not
  execute package scripts, shell commands, Docker, Terraform, or cloud CLIs.
  CLI provenance flags are non-secret reference metadata only; a future source
  credential must use the platform's workload-identity/secret-binding surfaces,
  never a registration DTO, manifest, command-line flag, or child-process
  environment.
- **Errors:** translate service failures through `cms.exceptions.CMSError` and
  `shared.errors`; DRF responses use `shared.api.errors`. Return stable,
  non-sensitive error classes, never parser traces, package fragments, storage
  payloads, or path/ownership internals.

## Extensibility And Current Constraint

The required seam is the registration input's explicit contract/profile and
resolver kind, plus its immutable package/lock identity. A future resolver or
ACES profile extends its resolver/contract adapter and the central allowlists;
it does not add branches to bootstrap, editor, CTF, Mission Control, engine, or
provisioner call sites.

Current code lists `object` as a valid source kind, but the native package
loader resolves only under `ACES_PACKAGE_ROOT`. Until #1567 provides an
object-storage resolver with the same containment and immutable-identity
properties, an object-backed row must not be registered as runnable or marked
launchable. Such a row is only a pending unresolved reference; API, logs, audit,
and docs must not describe its content, identity, conformance, or digest as
verified. This issue does not move #1567.

`aces-scenario-packs` 1.2.0 exposes the canonical ACES associated-artifact set
digest over an exact pack inventory. Repo registration must validate that
manifest and bind `package_digest` to current payload bytes before persistence.
Native launch must verify the persisted digest again before SDL resolution,
parse, planning, or dispatch. Either an invalid declaration or changed/resealed
content fails closed. The two operations require immutable staging; repeated
verification narrows the time-of-check/time-of-use boundary but does not make a
mutable working tree an acceptable deployment surface.

## Gotchas, Anti-Patterns, And Non-Goals

- Do not create separate "built-in", "marketplace", "licensed", "private",
  or "author-created" import endpoints, schemas, tables, permissions, audit
  events, exceptions, or bootstrap code paths.
- Do not conflate operator authorization to register content with entitlement
  to acquire it, or conflate a producer trust signal with an operator access
  decision.
- Do not let a new pack shadow an active legacy `scenario_id`; retain the
  registry's fail-closed collision behavior and ADR-024 cutover posture. The
  namespace invariant is bidirectional: legacy scenario creation must not later
  shadow a registered pack. Because YAML, `Scenario`, and `AcesPackageSource`
  are separate stores, there is no cross-table database constraint; centralize
  the collision check and retain registry fail-closed behavior for races and
  historical bad rows.
- Do not turn staff-review visibility, `conformance_status == "passed"`, or a
  valid digest into launchability; keep access, conformance/realizability, and
  launchability as separate axes.
- Do not claim the in-box acceptance criterion merely because a manifest and a
  command exist. Once any in-box pack ships, the canonical post-migration deploy
  bootstrap must invoke the same service and fail visibly on invalid or drifted
  entries. Do not hide this in a data migration, app-ready hook, fixture, or
  import-time side effect, and do not grant in-box content an authorization or
  validation bypass.
- No marketplace/acquisition client, licensing or subscription service,
  hosted registry, credential store, package-source migration (#1567), image
  distribution redesign, ACES cutover, or replacement of legacy YAML/DB
  scenarios is in scope.

## Whole-Repository Surfaces

Implementation must evaluate `docs/architecture/uniform-content-ingestion-contract.md`,
`docs/architecture/product-development-surfaces.md`, ADR-024 and ADR-034 in
`docs/adr/index.yaml`, the ACES catalog preflights (#1232, #1252, #1253,
#1254), `cms/models/scenarios.py`,
`cms/scenarios/{loader,registry,pack_validation,inbox}.py`, `cms/services`,
`cms/scenario_editor`, `cms/api/{permissions,serializers,views}.py`,
`shared/schemas/aces_package_source.py`,
`shared/aces/{package_loader,manifest,realization_ledger}.py`,
`shared/{auth,api/errors,cloud,log_sanitize}.py`,
`shared/audit/**`, `risk_register/audit_adapter.py`,
`config/{_aces_settings.py,env-manifest.json,middleware.py}`,
the canonical deploy/post-migration bootstrap, the CTF/Mission Control service
bridges, `docs/ops/content-ingestion.md`, and `.importlinter`,
`scripts/check_layer_imports/layer_imports.yaml`, and
`scripts/adr_guard/adr_guard.py`.

The documentation gate is:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
