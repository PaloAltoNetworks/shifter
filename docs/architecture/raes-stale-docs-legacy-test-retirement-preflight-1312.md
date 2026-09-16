# RAES stale-document and legacy-test retirement preflight

Issue: GitHub #1312, "ACES migration: retire stale migration docs and legacy
scenario/runtime tests after cutover."

Status: pre-implementation architecture guidance. This note does not retire a
document, test, route, runtime entry point, requirement, or traceability link.

## Authority and boundary

The issue title and older references use the historical ACES name. Current
authority is RAES under ADR-024, ADR-031, ADR-032, ADR-034, and ADR-043. The
repository hard cut and #1311 activation satisfy this issue's repository-level
ordering gate; they do not prove live AWS/GCP deployment parity, which remains
separate evidence under #2043.

Cleanup must preserve facts while removing false authority. A historical name
in a migration, dated preflight, frozen payload, changelog, retirement record,
or migration test is not a compatibility surface. Conversely, a current
technical page, requirement mirror, generated API contract, test description,
callable function, route, workflow, or operator instruction is not made
historical merely by calling it legacy.

Repository inspection found both kinds. In particular:

- `docs/architecture/aces-migration-parity-inventory.yaml` and several ACES
  preflights still point to removed paths and the superseded parallel-cutover
  doctrine. They are historical audit evidence, not a current backlog or
  runtime schema.
- `docs/architecture/aces-cyberscript-issue-triage.md` is still written in the
  pre-cutover tense and its maintain/migrate dispositions are no longer a
  current decision surface.
- active-looking requirement mirrors such as PLAT-204, PLAT-205, and PLAT-209
  describe removed implementations or the superseded ACES transition. Their
  status and traceability must be reconciled through Ground Control rather than
  made apparently current by hand-editing generated prose.
- `docs/technical/architecture.md`, the Mission Control scenario serializer
  description, generated OpenAPI/types, and some current source/test comments
  still describe experiment, CyberScript, or dual catalog/runtime behavior.
- negative-authority tests (`test_experiments_removed.py`, API retirement
  assertions), hard-cut migration tests, and opaque historical-payload tests
  intentionally mention retired names and remain current safety controls.
- range-id provision/teardown entry points and direct-persistence compatibility
  seams are still callable and tested. Their tests cannot be deleted as stale
  documentation. Retiring those runtime seams is a separate code and migration
  decision constrained by ADR-043 and the persisted-lifecycle boundary.

## Documentation disposition contract

| Class | Required disposition |
| --- | --- |
| Current authority | Use RAES terminology and the shipping package/catalog, API, lifecycle, persistence, and provisioning behavior. Update or remove claims about a parallel selector, legacy YAML/DB authoring, `cms.experiments`, or CyberScript authority. |
| Historical evidence | Preserve factual names and payloads. Add a concise historical/superseded banner when the document otherwise reads as actionable current guidance; point to `raes-migration-adr.md` and the accepted ADR registry. Do not mechanically rename history. |
| Ground Control requirement mirror | Reconcile status and links through the Ground Control requirement surfaces, then refresh the repository mirror. Do not hand-edit an ACTIVE requirement into an untracked archive and do not leave links to deleted code/tests as current `IMPLEMENTS`/`TESTS` evidence. |
| Generated projection | Change the canonical producer, then regenerate. OpenAPI and `frontend/src/api/schema.d.ts` use `npm run gen:api`; gettext source comments must reflect live template/Python sources and compiled catalogs remain build artifacts. Do not patch generated output alone or restore a deleted msgid to retain a comment. |
| Deleted product documentation | Remove from user/technical indexes and documentation-coverage declarations when the whole feature is gone. Historical architecture evidence may remain outside the current feature-documentation surface. |

ADR-027 remains the experiment guardrail. Generic future words such as
"experiment" or RAES parameterized runs are not automatically stale. Claims
that `cms.experiments`, its statuses, routes, scripts, queue, event bridge, or
storage workflow currently exist are stale. A future experiment capability
requires a new accepted product/security/data-retention design; cleanup must
not revive deleted strings or infer that RAES parameterization supplies that
workflow.

## Test-retirement contract

Test disposition follows the safety property, not the retired name in a path,
fixture, or comment:

| Test class | Decision | Replacement evidence required before removal |
| --- | --- | --- |
| Current RAES behavior under a stale directory/name | Move or rename without weakening assertions. | Current `cms.scenarios.registry`, package registration, realizability/publication, dispatch, and service tests. |
| Negative-authority/retirement test | Retain as an executable guardrail. | None unless an equal repository-level absence check owns the exact route, setting, import, scope, schema field, or app-registration prohibition. |
| Forward/reverse migration or opaque historical-row test | Retain and label as historical compatibility evidence. | A superseding migration proof that preserves factual bytes, drain refusal, and reverse/restore behavior. |
| Test of a callable compatibility runtime | Retain while any producer, consumer, persisted row, grant, command, or teardown path can reach it. | First retire the runtime boundary under its governing ADR; then prove current RAES lifecycle and safe handling of terminal historical state. |
| Legacy scenario authoring/loading/hydration behavior | Remove only with the last live loader/model/route/template and after negative-authority scans prove it unreachable. | RAES pack validation, digest-bound registry, realizability/publication, direct dispatch, exact plan transport, and cutover/API-retirement tests. |
| Standalone Polaris or guest smoke | Treat as realization evidence, not authoring authority. Keep any unique guest/network/content safety property even if the harness changes. | Digest-bound Polaris pack registration plus RAES-path portal/engine/provisioner evidence and an equivalent guest-visible smoke/readback for every removed assertion. |

The acceptance phrase "demonstrably covered" requires an explicit
property-to-test mapping in review. File counts, broad suite names, green CI,
or a new RAES test with similar nouns are not equivalence. The minimum evidence
families are:

- RAES contract/profile parsing and conformance in `tests/shared/raes`;
- package trust, digest, registry, launchability, and publication gates in
  `tests/cms` and the current registry test;
- layer/import confinement through `.importlinter`,
  `scripts/check_layer_imports`, and ADR guard;
- CMS-to-Engine direct dispatch, generation-fenced operation input, durable
  launch intent, result application, outbox, and reconciliation tests;
- CTF range ownership/status/content tests through `ctf.services`, not a copied
  RAES lifecycle;
- Mission Control authorization, redacted RAES projection, terminal/access,
  and absent-sidecar behavior;
- provisioner exact-version plan parsing, topology admission, provider apply,
  content/account/feature realization, guest readback, failure cleanup, and
  sanitized terminal evidence; and
- Polaris guest/network/content smoke properties that are not represented by
  unit or conformance tests.

## Canonical incumbents and cross-cutting layers

| Concern | Canonical incumbent and required reuse |
| --- | --- |
| Contract and schema | Released RAES contracts behind `shared.raes`; `RaesPackageSource`, `ScenarioMetadata`, serialized RAES `ProvisioningPlan`, generation-fenced `OperationInput`, and existing result/event schemas. Do not create an archive DTO or a test-only replacement schema. |
| Package/catalog validation | `cms.scenarios.pack_validation`, package loader/inbox registration, `cms.scenarios.registry`, realizability and publication gates. A doc or test fixture does not become a second catalog. |
| Service boundaries | `cms.services`, RAES dispatch port, `engine.services`, `ctf.services`, and Mission Control presentation APIs. Preserve `.importlinter` and `scripts/check_layer_imports` ownership. |
| Persistence/workflow | CMS/Engine range/request records, persisted plan kind, `ProvisionerLaunchIntent`, versioned operation input/result inbox, Engine result applier, `RangeEventOutbox`, and reconciler. Historical bytes remain inert and factual. |
| Authorization | `shared.auth`, `CMS_READ_PERMISSIONS` / `CMS_WRITE_PERMISSIONS`, exact API-token scopes, CTF ownership, and Mission Control actor/participant permissions. Removing UI/docs/tests never retires authorization by itself. |
| Errors | `cms.exceptions.CMSError`, existing RAES boundary errors, provisioner typed errors, `shared.errors`, and `shared.api.errors`. Do not add a cleanup exception hierarchy or expose raw parser/provider text. |
| Logging/audit | `shared.log_sanitize`, provisioner `log_redact`, stable request/range/operation ids, and `shared.audit`. Cleanup reports contain paths, test ids, counts, and outcomes only. |
| Config and generated artifacts | `config/_raes_settings.py`, `config/env-manifest.json`, installation runtime inventory/renderers, OpenAPI producer plus `npm run gen:api`, and Django gettext/`compilemessages`. Remove a retired key or projection at its canonical producer and every renderer. |
| Repository workflow | ADR-024/027/031/032/034/043, ADR-040 API retirement metadata, ADR-022 documentation coverage, quality-path routing, secret hygiene, ADR guard, and stack-native checks for touched surfaces. |

## Security and host-boundary requirements

- **Input and shape gates:** retained RAES fixtures must pass upstream pack and
  SDL validation, containment and bounded extraction, canonical digest and
  inventory verification, contract/profile allowlists, realizability,
  compiled-plan validation, and the provisioner's independent plain-data
  topology/admission parser. Cleanup must not replace these with filename,
  prose, grep, or fixture-shape inference.
- **Authorization:** API and product tests must continue to exercise session or
  exact-scope authentication, CMS authoring actors, CTF ownership, and Mission
  Control range/participant ownership. A removed navigation item or archived
  document is not a policy gate.
- **Secret handling:** archives, migration fixtures, parity mappings, logs, and
  CI summaries must not acquire package bodies, flags, credential values,
  private keys, bearer/admin tokens, signed URLs, terminal/Guacamole URLs,
  environment dumps, generated commands, provider output, or Terraform state.
  Preserve the existing secret-hygiene and cloud-identifier checks.
- **Configuration shape:** this cleanup needs no runtime setting. If a surviving
  setting is removed with its runtime consumer, remove it consistently from the
  typed settings module, env manifest, installation/runtime inventory, every
  Helm/Terraform/bootstrap renderer, and their parity tests. Do not add a
  cleanup flag or old-key fallback.
- **OS/process exposure:** tests and evidence tooling may pass bounded ids,
  digests, paths, profiles, request ids, and operation ids in structured argv.
  They must not pass payloads, credentials, environment maps, package content,
  or provider output in argv, nor execute commands sourced from old YAML/SDL or
  archived docs.
- **Errors and observability:** public APIs retain the shared bounded error
  envelope; CLI/provisioner failures retain typed, sanitized diagnostics. Log
  stable ids, digests/fingerprints, counts, duration, and disposition, never raw
  exception text or retired fixture bodies.

## Extensibility seam

The forward seam remains the RAES environment-pack identity and current
scenario catalog record: scenario id, source kind, contract kind/profile,
package version/digest, conformance and realizability state, and
`ScenarioMetadata`. Test evidence varies by those identities plus provider,
release SHA, and verification profile. A future scenario, provider, contract
profile, or verification plugin extends those existing parameters; it does not
restore a legacy loader, add a scenario-specific branch, or introduce an
"archive source" runtime mode.

For cleanup itself, the required seam is a review-only safety-property mapping
from retired test id to incumbent test id(s) and coverage class. It is not a
runtime manifest, database model, YAML schema, marker taxonomy, or permanent
second test registry.

## Gotchas and anti-patterns

- Do not bulk-replace `ACES` with `RAES`; that falsifies migrations and dated
  evidence and can relabel opaque contract bytes.
- Do not call a live runtime path historical to justify deleting its tests.
- Do not delete negative-authority, API-retirement, drain-refusal, migration,
  restore, historical-row, teardown, or grant-revocation tests because they
  contain retired vocabulary.
- Do not treat broad RAES conformance as proof of CTF authorization, Mission
  Control projection, durable result/outbox behavior, provider cleanup, or
  guest-visible Polaris content.
- Do not preserve stale current guidance by moving it under another active
  docs directory without a historical banner and current-authority pointer.
- Do not hand-edit generated OpenAPI/types/gettext comments, requirement
  mirrors, or parity evidence independently of their canonical producer.
- Do not add duplicate schemas, validators, status enums, exceptions, event
  flows, repositories, archive stores, feature flags, test registries, or
  cleanup workflows.
- Do not weaken ADR guard, import boundaries, secret scanning, quality-path
  routing, provider checks, or smoke gates to make deletion green.

## Non-goals and implementation boundary

- No runtime, route, model, migration, grant, configuration, workflow, test, or
  documentation retirement is performed by this preflight.
- No live AWS/GCP range, CTFd mutation, image bake, tenant deployment, or parity
  claim.
- No rewrite of historical migrations, immutable payloads, changelog entries,
  issue numbers, or dated ACES evidence.
- No resurrection or redesign of experiments, legacy YAML authoring,
  CyberScript, or a compatibility selector.
- No retirement of callable range-id/direct-persistence compatibility seams
  under a documentation-and-test-only change. Their code, data, grants, drain,
  teardown, and rollback consequences require the governing runtime scope.
- No new Ground Control requirement for this requirement-free issue; existing
  stale requirements still require authoritative Ground Control reconciliation.

## Validation expectation

The implementation must keep the full architecture gate green:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Runtime Python changes additionally require Ruff, import-linter, and the layer
check. Workflow, Terraform, Kubernetes, Packer, provisioner, locale, OpenAPI,
and frontend changes inherit their existing path-native generators and checks.
