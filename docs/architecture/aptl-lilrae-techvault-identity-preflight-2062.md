# APTL/LilRAE identity and TechVault boundary preflight

Status: pre-implementation guidance

Date: 2026-08-19

Issue: GitHub #2062, "docs: audit APTL/LilRAE identity and TechVault boundary"

This is a requirement-free documentation correction. The issue is the shipping
contract. This note records the repository-wide terminology and integration
boundary; it does not perform the correction.

## Authority and decision boundary

APTL and LilRAE are one continuous identity across a rename. Current
explanatory prose uses **LilRAE (formerly APTL)** when the old name matters and
LilRAE otherwise. It must not describe APTL and LilRAE as separate products,
layers, plugins, experiences, runtimes, or integration targets.

TechVault is a **scenario pack**. It is not APTL, a retained APTL experience, a
LilRAE-hosted product, or an architectural layer on LilRAE. A Shifter delivery
of that scenario pack may use the ordinary RAES environment-pack contract, but
the transport/package representation does not change TechVault's conceptual
identity or create a TechVault product boundary.

No superseding ADR is appropriate. An erroneous conceptual statement was not a
valid former architecture decision. Correct affected current ADR prose in
place, while keeping factual historical names and immutable technical
identifiers where changing them would falsify evidence or break a locator.

## Repository audit result

The baseline case-insensitive repository scan, before this note was added,
found 173 matches across 25 files. It found no `LilRAE` occurrence and no live
APTL or TechVault code surface. Every match was in documentation,
`CHANGELOG.md`, or a release fragment. File-name and content scans found none
of the former scenario templates, Packer definitions, bake scripts, workflow
branches, bootstrap plans, configuration keys, runtime schemas, controllers,
services, repositories, or tests.

The implementation audit must classify matches by meaning, not apply a blind
rename:

| Class | Repository surfaces | Required treatment |
| --- | --- | --- |
| Current architecture authority | `docs/architecture/raes-migration-adr.md` and `docs/architecture/raes-hard-cutover-preflight-1862.md` | Correct the `TechVault/APTL` pairing in place. State identity continuity for LilRAE/APTL and identify TechVault only as a scenario pack. Preserve ADR-024's RAES hard-cut and no-bespoke-runtime decision. |
| Current requirement rationale and traceability | `docs/requirements/PLAT-211` through `PLAT-216`, plus the APTL reference in `PLAT-2010` | Use the current LilRAE name in explanatory prose. Keep an `aptl:*` spec identifier only when it remains the exact external traceability locator; label it as the former-name identifier rather than inventing a replacement id. The Shifter requirement remains the owner of Shifter behavior. |
| Dated conceptual prior art | The ACES/Polaris preflights with conceptual APTL references: `aces-runtime-target-backend-manifest-preflight-1233.md`, `aces-polaris-acceptance-parity-gate-preflight-1237.md`, `polaris-support-decomposition-preflight-691.md`, and `polaris-aws-agent-credentials-preflight-1377.md` | Clarify LilRAE/APTL rename continuity where the text discusses a conceptual model. Do not turn prior art into a LilRAE dependency or a second Shifter integration boundary. |
| Retired TechVault implementation guidance | `gcp-techvault-gce-image-preflight-1760.md`, `packer-scenario-bake-standardization-preflight-1469.md`, `techvault-encrypted-ami-preflight-1455.md`, the image-resolution/migration/provenance preflights, and their exact former paths/symbols | Make the historical/retired status unambiguous where the document could still be read as current guidance, and clarify that the implementation served a scenario pack. Preserve exact historical symbols such as `TechVaultRangeBootstrapPlan`, `aptl lab start`, `aptl-*`, `techvault` image keys, paths, and workflow names. They are evidence, not present-day abstractions. |
| Immutable release and external-name evidence | `CHANGELOG.md`, `changelog.d/*`, and the sibling repository name `aptl` in `release-please-preflight-1776.md` | Do not edit merely to modernize names. Changelog entries, command names, package/container names, repository names, and identifiers must remain factual. Correct only a sentence that actually asserts the false split. Release Please owns `CHANGELOG.md`. |
| TechVault-only scenario references | The GCE image-resolution and normal-range migration notes that already call TechVault a scenario | Retain when factually historical. A scenario-specific artifact or acceptance example is not by itself a claim that TechVault is a product, but it must not remain normative authority for restoring bespoke runtime branches. |

This classification is the audit allowlist. A final residual-name scan is not a
zero-match gate: expected old-name identifiers need contextual review. A raw
count cannot distinguish a false concept from `aptl lab start`, an `aptl:*`
traceability id, or a historical changelog entry.

## Dependent Shifter integration decision

The current integration decision remains the ADR-024 hard cut:

- Shifter has no APTL, LilRAE, or TechVault-specific runtime surface.
- LilRAE prior art does not authorize another parser, schema, catalog,
  controller, service, exception family, persistence model, workflow, image
  resolver, or lifecycle branch.
- If TechVault is introduced again, it is authored as a scenario pack and
  enters Shifter through the same RAES environment-pack ingestion,
  registration, realizability, launch, and lifecycle boundaries as another
  scenario. It is an acceptance case, not a type discriminator.
- The `raes-env-packs` representation is a Shifter integration contract, not a
  reclassification of TechVault as a product and not evidence that LilRAE
  hosts it.
- Shifter-owned authorization, lifecycle, cloud realization, CTF, Mission
  Control, audit, redaction, status, persistence, and operator behavior remain
  Shifter responsibilities. Requirements that cite former-name LilRAE specs
  are traceability evidence, not ownership delegation.

Correcting terminology must not reopen the RAES hard cut, rewrite opaque
historical payloads, relabel old producer versions, or restore any removed
scenario-specific path.

## Canonical incumbents to reuse

No new application abstraction is needed for this documentation issue. If a
dependent integration statement is re-evaluated, it must point to these
incumbents rather than the removed TechVault implementation:

| Concern | Canonical incumbent and guardrail |
| --- | --- |
| Durable architecture authority | ADR-024 in `docs/adr/index.yaml` and `docs/architecture/raes-migration-adr.md`. Correct its wording in place; do not create an identity-rename ADR or weaken the RAES-only rules. |
| Pack contract and validation | `cms.scenarios.pack_validation`, `shared.raes.package_loader`, and the released `raes-env-packs` validator own pack shape, content digest, containment, and conformance. Do not add a TechVault or LilRAE validator. |
| Source and catalog schema | `shared.schemas.raes_package_source`, `RaesPackageSource`, `ScenarioMetadata`, `cms.scenarios.inbox`, `registry`, and `realizability` own source kind, contract kind/profile, version/digest/provenance, registration, publication, and launchability. Do not add a product/experience field for this rename. |
| Launch and lifecycle | The RAES dispatch port, CMS/engine services, generation-fenced `OperationInput`, persisted `range_config.kind`, and provisioner RAES service remain the only current scenario launch path. |
| Persistence | Existing CMS/engine range records, `RaesPackageSource`, RAES operation/participant sidecars, launch intents, results, and range-event outbox preserve current and historical truth. A terminology correction needs no migration or data rewrite. |
| Authorization | `shared.auth`, CMS permission services, exact API-token scopes, CTF ownership services, and Mission Control participant/actor policy remain authoritative. A scenario pack creates no new auth realm. |
| Errors | `cms.exceptions.CMSError`, `shared.api.errors`, `shared.errors.UserFacingError`, existing RAES boundary errors, and provisioner typed errors remain the vocabulary. Do not create identity-, rename-, LilRAE-, or TechVault-specific exceptions. |
| Logs and audit | `shared.log_sanitize`, provisioner `log_redact`, request/range correlation, and `shared.audit` remain authoritative. Log bounded ids, digests, versions, and outcomes; do not introduce product-name-derived telemetry dimensions. |
| Configuration and workflows | `config/_raes_settings.py`, `config/env-manifest.json`, deployed renderers/allowlists, `.importlinter`, `scripts/check_layer_imports`, and `scripts/adr_guard` remain canonical. This docs-only correction adds no env key, feature flag, workflow choice, or compatibility alias. |

## Cross-cutting layers

The intended change is documentation-only, so it must not pass through or
modify runtime auth, secret, environment, process, persistence, or API-error
surfaces. Repository text still passes the ADR and secret-hygiene gates, and
any statement about a future TechVault integration must accurately name the
following existing layers:

1. **Authorization:** session/API-token authentication, CMS service ownership,
   CTF organizer/participant rules, and Mission Control actor policy execute
   before pack registration or launch. The rename adds no principal, scope,
   permission, or trust relationship.
2. **Pack and shape validation:** inbox slug/manifest checks,
   `validate_package_source`, upstream environment-pack validation, canonical
   digest/inventory and containment checks, contract/profile allowlists,
   realizability/publication, SDL compilation, and the provisioner's closed
   plan/operation-input parsers remain fail-closed. TechVault must not receive
   a duplicate schema or validation bypass.
3. **Secret and content handling:** package bodies, credentials, private keys,
   presigned URLs, participant data, and provider output remain in their
   existing secret/content-delivery channels. Documentation and traceability
   records contain names and reference ids only, never copied payloads.
4. **Environment/config shape:** RAES settings remain typed in
   `config/_raes_settings.py`, the environment manifest, Terraform/Helm/
   Kustomize renderers, and runtime allowlists. There is no `APTL_*`,
   `LILRAE_*`, or `TECHVAULT_*` compatibility setting or precedence rule.
5. **OS/process exposure:** runtime dispatch continues through structured ids,
   argv arrays, and the versioned operation envelope. A scenario pack must not
   supply executable shell fragments, and no secret or package body belongs in
   process argv. This docs correction invokes no external process with
   repository content.
6. **Errors and observability:** API failures keep the bounded DRF/shared error
   envelope; CLI/provisioner failures keep typed, sanitized diagnostics and
   existing correlation ids. Raw parser, filesystem, cloud, package, or secret
   material must not be logged to explain a naming mismatch.
7. **Persistence:** current schema and opaque historical records remain
   unchanged. The rename is corrected in prose and traceability labels, not by
   rewriting persisted contract kinds, payload keys, digests, migrations, or
   producer versions.
8. **Repository policy:** any edit to `docs/adr/**` or another guardrail must
   remain synchronized with its binding ADR evidence. All completed changes
   pass `scripts/adr_guard`; `CHANGELOG.md` is not hand-edited.

## Extensibility seam

The existing pack/catalog identity is the only runtime seam:
`(scenario_id, source_kind, contract_kind, contract_profile, package version,
digest, conformance status)`. TechVault varies those ordinary data values; it
does not add a product type, host relationship, parser, controller, workflow,
or provider branch. This permits the next scenario pack to use the same
contract without editing a TechVault registry.

The documentation seam is the distinction between a conceptual name and an
immutable technical locator. Future renames update current prose once while
literal historical commands, paths, repository names, package/container names,
and trace ids remain stable and are contextually labelled. Do not create a
second terminology registry, alias map, or runtime compatibility layer.

## Whole-repository surfaces in scope

- Current authority: ADR-024's registry entry and narrative, the RAES hard-cut
  preflight, and DRAFT requirement rationale/traceability under
  `docs/requirements/PLAT-{2010,211,212,213,214,215,216}`.
- Dated design evidence: ACES/Polaris prior-art notes and TechVault image,
  bootstrap, credential, migration, and bake preflights.
- Historical evidence: `CHANGELOG.md`, the three TechVault release fragments,
  exact old command/container/package/repository names, and referenced deleted
  paths or symbols.
- Current runtime boundaries rechecked for absence of a bespoke surface:
  `shared.raes`, `shared.schemas`, `cms.scenarios`, CMS/engine models and
  services, provisioner plans, scenario templates, Packer and image tooling,
  `.github/workflows`, runtime configuration/renderers, Terraform/Kubernetes,
  operator MCP tooling, and tests.
- Host/cloud layers are not mutated or live-validated by this issue. The audit
  must not create a workflow dispatch, image bake, tenant deployment, pack
  registration, range launch, database migration, or provider operation.

## Gotchas and anti-patterns

- Do not globally replace `APTL` with `LilRAE`. That would corrupt historical
  commands, spec ids, package/container names, repository names, changelog
  evidence, and paths.
- Do not preserve `TechVault/APTL` or replace it with `TechVault/LilRAE`; both
  slash forms imply the same false identity or architectural pairing.
- Do not describe TechVault as an experience, plugin, product, platform,
  LilRAE layer, or retained APTL component. "Scenario pack" is the boundary.
- Do not confuse TechVault's conceptual kind (scenario pack) with its delivery
  representation (a RAES environment pack) or with a historical image/profile
  artifact used to realize it.
- Do not infer a new Shifter integration from LilRAE requirements cited as
  prior art. Shifter requirements and service boundaries own Shifter behavior.
- Do not restore `TechVaultRangeBootstrapPlan`, scenario-specific image keys,
  workflow choices, validators, or config simply because dated documents name
  them. They are historical after the hard cut.
- Do not add a glossary model, alias table, feature flag, redirect, schema,
  exception hierarchy, telemetry taxonomy, or automated global replacement
  framework for a bounded documentation correction.
- Do not use a zero-result grep as acceptance evidence. Every remaining old
  name must be either corrected conceptual prose or a reviewed factual
  identifier/history occurrence.
- Do not hand-edit `CHANGELOG.md` or add a changelog fragment for this preflight
  or the later documentation-only correction.

## Non-goals and implementation boundary

- No implementation of issue #2062 in this preflight note.
- No superseding ADR, new requirement, or change to the substance of existing
  Shifter requirements.
- No redesign or reintroduction of LilRAE/APTL integration, TechVault runtime
  support, scenario authoring, RAES, environment packs, image pipelines,
  credentials, or cloud/provider behavior.
- No rename of literal historical identifiers when their old spelling is part
  of the fact, protocol, locator, command, package, container, path, or release
  record.
- No runtime code, schema, DTO, model, migration, controller, service,
  repository, parser, validator, error, log, config, workflow, test, or
  deployment change.
- No live GitHub issue rewrite, external repository edit, package publication,
  tenant mutation, or cloud operation.

## Validation expectation

For the later documentation correction, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
rg -n --hidden --glob '!.git/**' -i '\b(APTL|LilRAE|TechVault)\b' .
```

Review every residual match against the classification above. The second
command is an audit inventory, not a requirement for zero output.
