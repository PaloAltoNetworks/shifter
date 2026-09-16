# REV1 Contract And Runtime Architecture Exit Preflight (#1538)

Status: pre-implementation architecture guidance

Date: 2026-07-28

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1538>

This is a requirement-free preflight. GitHub issue #1538 is the shipping
contract. This note does not implement or rerun a gate, change a runtime path,
close a blocker, publish an evidence bundle, or change provider support.

## Boundary And Decisions

#1538 is an evidence-integration and verification gate over the smallest
complete production boundary named by the issue. It is not a new verification
framework and not a repository-wide remediation gate.

- The only native blockers are #728, #729, #1562, #1566, #1567, and #1569.
  Their dependency chains may supply evidence for those six claims, but the gate
  must not silently promote parallel refactors, audit-port work, the security
  gate, ADR-039 backlog, or general package cleanup into new native blockers.
- The issue's historical wording says ACES. The current repository completed
  the incompatible RAES naming/contract cut under ADR-024 and #1862. New gate
  code, evidence, commands, and documentation use the current `raes==2.0.0` /
  `raes-env-packs==3.0.0` contracts and `shared.raes` paths. Historical ACES
  preflights remain factual design evidence; they are not names to restore,
  compatibility aliases, or transport readers.
- Reuse the pointer-layer convention from
  `rev1-release-evidence-integration-preflight-1540.md`: the reviewed bundle
  identifies canonical producer-owned evidence, exact source revision, scope,
  immutable locator, observed conclusion, and limitation. It does not copy
  logs, snapshots, provider output, or gate definitions and introduces no
  schema, parser, status enum, service, workflow, or persistence.
- Evidence is claim-specific. Installation bundle conformance, RAES
  manifest/profile conformance, provider/range-substrate conformance, live
  reachability, object-pack launch, and in-guest realization are different
  verdicts. A pass in one cannot stand in for another.
- Unsupported behavior is a first-class gate result. A limitation qualifies
  only when the current capability authority excludes it and a negative test or
  live probe proves the production boundary fails closed. Prose alone is not
  limitation evidence, and a limitation must never be rendered as a pass.
- Native-blocker completion means the reviewed merged/final record is present
  in the exact gate revision and its qualifying evidence is linked. An issue
  state, branch name, source path, test name, or design note alone is not proof.

No ADR change is needed. ADR-011 already owns root-configured backend bundles;
ADR-024 owns the RAES hard cut; ADR-031/032/034 own RAES transport, realization,
and pack trust; ADR-039 owns provider range-substrate conformance; ADR-041 owns
optional scenario-verification plugins. This gate must cite those authorities
rather than restating or replacing their contracts.

## Evidence Claims And Qualifying Producers

| Gate claim | Canonical producer | Qualifying evidence and required boundary |
| --- | --- | --- |
| Fail-closed RAES transport and topology | `shared.raes.runtime_target`, `shared.raes.domain_topology`, `engine/provisioner/raes_plan.py`, `raes_plan_*`, `raes_service.py`, and `test_plan_provisioner_parity.py` | Exact-revision test evidence for the producer/consumer version pair plus negative unknown-version, resource-shape, duplicate-identity/alias, dangling network/ACL/composition/domain ref, unsupported domain profile, and malformed-service cases. Rejection must occur before any cloud, Terraform, SSH, SSM, or guest mutation. |
| Explicit root provider selection | `installation.loader/schema/registry`, backend settings models/renderers, `installation.runtime_inventory`, `config._runtime_env.resolve_cloud_provider`, provisioner `config.resolve_cloud_provider`, and both cloud factories | Both checked examples validate; the selected root backend renders the same explicit `CLOUD_PROVIDER` to portal, worker, and provisioner roles; missing or unknown deployed values and registered-but-unsupported capabilities fail closed. Test/build/debug defaults are not deployed-provider evidence. |
| AWS backend contract/conformance (#728) | AWS `BackendBundle`, closed `AwsSettings`, secret-reference grammar, published contract/snapshot, example, doctor/check front doors, and installation test lane | Successful publication drift, compatibility, registry-conformance, example, loader, closed-settings, secret-reference, generated-output classification, and structured-command evidence at the indexed SHA. This is configuration/bundle conformance, not proof that RAES realizes on AWS. |
| GCP backend contract/conformance (#729) | GCP `BackendBundle`, closed `GcpBackendSettings`, secret-reference grammar, runtime-env renderer/inventory, published contract/snapshot, example, doctor/check front doors, and installation test lane | The same contract evidence as AWS plus GCP renderer/inventory parity and pre-mutation validation front doors. It does not by itself prove GCE/GDC range lifecycle or in-guest realization. |
| Authored service reachability (#1562) | RAES `Node.services`, provisioner `raes_service`, `raes_gcp_firewall`, GCE firewall plan/apply/destroy, and the #1562 reviewed evidence | A live same-range probe must show the declared TCP/UDP path allowed and an undeclared port, another-range/world source, and a matching higher-precedence authored deny blocked. Parser/firewall-plan tests are necessary but not live reachability; a firewall object does not prove a listener is ready. |
| Tenant-manageable image mappings (#1566) | `engine.services._raes_image`, `RaesImageMapping`, CMS API/SPA, `raes_image_registry` command, provisioner read resolver | Authorized register/list/soft-disable behavior through the service seam, exact-version/any-version read behavior, and missing/disabled mapping rejection before realization. Do not expose a concrete provider image id in the reviewed public summary. |
| Digest-verified object-backed launch (#1567) | `shared.raes.object_source.stage_object_pack`, provider-neutral `ObjectStorage`, `cms.scenarios.pack_validation`, `shared.raes.package_loader`, and `_raes_range_create` | Evidence must cover immutable object identity/precondition, archive and extraction bounds, traversal/link/special-file rejection, upstream environment-pack validation, registered scenario identity, canonical associated-artifact digest, single direct SDL selection, cleanup, and a normal product-path launch. A successful download or extraction alone is not a package launch. |
| Real composition and sanitized outcome (#1569) | canonical `scenario-dev/shifter-raes-validation` pack, `run_raes_backend_validation`, `cms.raes.validation`, Engine operation-result apply, `shared.schemas.raes_operation`, `shared.raes.operations/projections`, and provisioner realization/probes | A deployed normal-path run reaches `READY`, records an accepted receipt and succeeded status, and returns a non-vacuous allowlisted runtime snapshot with verified content, account, and feature entries only after every applicable guest/authority probe succeeds. Unit/cross-boundary tests, VM creation, command exit, markers, direct provider calls, seeded rows, or raw logs do not substitute. |
| Deliberate limitations | `shared.raes.manifest`, transport supported-version sets, `_assert_raes_adapter_supports`, provider/range-backend admission, object/pack validators, and the relevant negative tests | Record each limitation material to the gate's claim with its exact scope and observed fail-closed result. At minimum distinguish the `provisioning-only` RAES profile, IPv4-only network constraint, exact RAES version, supported resource/composition shapes, and the currently implemented GCE RAES realization adapter from AWS and GDC. Do not infer provider coverage from an installation bundle or manifest claim. |
| Native blockers complete | Canonical merged/final records for #728, #729, #1562, #1566, #1567, and #1569 | Each locator names the merged revision/final conclusion and is included in the gate SHA. A dependency-chain issue may support a row but cannot replace one of these six native closure records. |

One live run may support more than one row (for example an object-backed
validation pack may also produce #1569 evidence), but the rows and conclusions
stay separate so one missing assertion cannot be hidden by a generally
successful launch.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent and guardrail |
| --- | --- |
| Root config and backend contract | `shifter/installation/{schema,loader,contract,registry,publication,runtime_inventory}.py`, `settings_gcp.py`, checked examples, and published contract snapshots. Parse once with `load_root_config`; do not add a gate-local backend list, YAML reader, provider schema, or secret grammar. |
| Runtime provider binding | Backend renderers, `CLOUD_PROVIDER`, Django `config._runtime_env.resolve_cloud_provider`, provisioner `config.resolve_cloud_provider`, and process-local cloud factories. Backend selection is composition-root configuration, never a request/DTO/database/event selector. |
| RAES contract/profile | `shared.raes.{contracts,manifest,runtime_target,domain_topology,sdl_validation}` and checked `shared/raes/backend-manifest.json`. RAES-owned tooling remains the conformance oracle; do not duplicate profile inference or capability logic. |
| Separate provisioner trust boundary | `engine/provisioner/raes_plan.py` plus `raes_plan_*`, `raes_acl`, `raes_service`, and domain/composition validators. Its frozen dataclasses are bounded process-local realization projections, not an authored schema, API DTO, or persisted model. |
| Reachability | `raes_gcp_firewall`, the existing GCE firewall plan/resource/apply/destroy path, node tags, and authored ACL precedence. Do not create a test-only firewall or widen source CIDRs. |
| Image realization | `engine.services._raes_image`, `RaesImageMapping`, provisioner DB candidates, `raes_image_policy`/resolver, and GCE image realization. Package registration, image supply, and provider existence are separate concerns. |
| Object-pack trust | `shared.raes.object_source`, provider-neutral storage adapters, `cms.scenarios.pack_validation`, `verify_pack_digest`, `resolve_pack_scenario_path`, and the uniform ingestion contract. Do not add an evidence-only downloader, archive parser, digest, or object store. |
| Guest verification | Existing execution factory, strict guest executors, setup orchestrator/plans, content/feature/account/AD realization, `raes_composition_verification`, and snapshot reducer. Do not add callbacks, agents, marker-only proofs, or pack-supplied commands. |
| Persistence and delivery | `OperationInput`, `OperationResultInbox`, `ProvisionerLaunchIntent`, Engine transactional apply/audit, ADR-025 `RangeEventOutbox`, `RaesOperationRecord`, and idempotent `shared.raes.operations`. Do not revive the retired direct event-consumer path or add evidence tables/repositories. |
| Evidence validation/read | `shared.schemas.raes_operation`, `shared.raes.projections`, `cms.raes.validation`, and the live management command. Read through the response allowlist; never query raw sidecar rows, plans, provider state, or guest output for the bundle. |
| Auth and audit | CMS authoring permissions for image management; ordinary range ownership/admission/workspace policy; shared audit policy; management-command operator context. Conformance status, image mapping presence, and evidence availability are not authorization. |
| Errors and observability | `InstallationConfigError`/`ConfigIssue`, Django `ImproperlyConfigured`, existing cloud exceptions, `CMSError`, `RaesPlanError` and bounded provisioner errors, `shared.api.errors`, `CommandError`, `shared.log_sanitize`, provisioner `log_redact`, request/run correlation. Do not create a gate exception hierarchy or paste `str(exc)` into durable evidence. |
| Optional functional verification | ADR-041 `shared.scenario_verification` only when a separately installed scenario adapter is explicitly selected. It must not replace RAES demand/supply/admission, #1569 guest realization, provider topology, lifecycle, or the native blocker evidence. |
| Workflow/evidence convention | Existing routed Quality jobs, installation/platform/provisioner lanes, producer-owned reports, issue final records, and the pointer-only REV1 evidence convention. Do not add a second path router, aggregate workflow, evidence store, or local waiver mechanism. |

## Cross-Cutting Layers The Intended Design Must Pass

| Layer | Required behavior |
| --- | --- |
| Root YAML/parser | `load_root_config` rejects unreadable/malformed/non-mapping YAML, duplicate and merge keys, unknown root fields, unsupported backend/profile combinations, and raw-looking secret material. Gate code consumes the normalized `RootConfig`; it never reparses `shifter.yaml` or echoes rejected values. |
| Backend settings and secret references | The selected bundle's one closed settings model and `RequiredSecret` grammars validate backend-owned intent; `range_egress` stays in its cross-backend validator. Config contains references, never secret values. Contract/publication validation uses `validate_published_bundle`, not a looser AWS/GCP-specific checker. |
| Renderer and env shape | Backend renderers, `GeneratedOutput` classifications, `runtime_inventory`, `config/env-manifest.json`, Terraform/Helm values, and process-role forwarding remain in parity. Public values and secret references may be projected; secret payloads may not. `CLOUD_PROVIDER` must reach every consuming deployed role explicitly. |
| Runtime composition roots | Django and the standalone provisioner normalize and registry-check `CLOUD_PROVIDER`; factories then check declared capabilities before adapter creation. Missing/unknown production values and registered providers without the requested capability fail closed. No request-controlled `--provider`, ambient branch inference, or persisted live selector is allowed. |
| Identity/auth | `AUTH_PROVIDER`, OIDC/Identity Platform token verification, issuer/subject binding, verified email, MFA/bootstrap rules, CMS authoring permissions, workspace/range ownership, and API-token scopes remain independent of cloud backend selection. #1538 adds no endpoint or privilege. |
| Package/object admission | Storage identity binding, bounded download/extraction, path/link/type guards, upstream pack validation, associated-artifact digest verification, scenario identity, and single-entry selection all complete before parsing, planning, dispatch, or mutation. Bucket/key/ref bodies and provider failures do not enter the evidence bundle. |
| RAES compile/admission | RAES parsing, manifest/profile/capability checks, realizability ledger, domain-topology diagnostics, and the versioned RuntimeTarget producer run in `shared.raes`. Shifter does not infer support from field presence or recreate upstream validation in CMS/Engine. |
| Provisioner admission | The separate plain-data consumer validates envelope kind, exact contract/producer version, resource types/shapes, identities, aliases, references, domain policy, services, image supply, and firewall representability before mutation. Unknown or unsupported input is rejected, never skipped/defaulted/coerced. |
| Cloud/network/IAM | Provider access remains behind existing storage/task/secret/range adapters and workload identity. Service ingress is same-range and node-tag scoped with management and authored-ACL precedence. Object buckets remain read-only to the portal path; credentials and provider payloads never become plan/evidence fields. |
| Guest/OS | Existing authenticated guest execution, host-key validation, private temporary-key handling, OS-specific quoting/stdin, retries/timeouts, and synchronous readback remain authoritative. Success means exact state readback on every applicable instance or declared directory authority, not VM/command/marker success. |
| Persistence/transaction | Operation input/result discriminators, digests, generation/ownership checks, sidecar validation, lifecycle transition, strict audit, and ADR-025 outbox enqueue stay in the existing transaction. Evidence persistence remains idempotent and retention-bounded; no partial snapshot or second source of truth is allowed. |
| Evidence/read envelope | `shared.schemas.raes_operation` enforces exact keys, sizes, versions, profile, timestamps, canonical digest, and value-free resource entries. `shared.raes.projections` applies a second response allowlist. The reviewed bundle stores only bounded counts/verdicts and immutable references, never raw payloads. |
| Error/log envelope | Internal config/cloud/RAES/guest errors retain their incumbent families and translate to fixed/bounded public reasons. `safe_log_value` prevents injection but is not confidentiality redaction. In particular, `run_raes_backend_validation` currently writes an exception traceback to process logs; those raw logs are not qualifying reviewed evidence. |
| OS/process/workflow exposure | Runtime dispatch stays fixed structured argv carrying the operation and request identifier; plans, config, env maps, credentials, provider output, guest values, and evidence bodies stay out of argv, shell strings, process titles, workflow summaries, and `set -x`. The validation user email remains environment/operator context and must not be copied into evidence. |
| Evidence provenance/retention | Every row pins the exact commit and immutable producer-owned run/report/final record; live rows also name backend/range-backend, environment/tenant class, profile, and time without exposing identifiers. Missing, stale, inaccessible, wrong-revision, or contradictory evidence is not demonstrated, never guessed. |
| Repo enforcement | ADR guard, import-linter/layer checks, routed SAST/secrets checks, package tests, and every stack-native validator selected by touched paths stay enabled. #1538 must not weaken a producer to obtain a green conclusion or add an exception outside `docs/adr/exceptions.yaml`. |

## Concept Boundaries And Current Limitations

The word "provider" names several different concepts in this repository. The
gate must keep all of them explicit:

- root installation backend: `shifter.yaml backend` (`aws` or `gcp`);
- derived runtime cloud adapter family: `CLOUD_PROVIDER`;
- GCP range substrate: `GCP_RANGE_BACKEND` (`gce` or `gdc`);
- RAES concrete image mapping provider: currently `gce`;
- identity provider: `AUTH_PROVIDER`;
- persisted resource ownership metadata: historical cleanup/routing evidence;
- RAES backend profile: `provisioning-only`.

None may be inferred from another. In particular, successful AWS/GCP bundle
conformance does not prove a RAES realization adapter exists for both. The
current RAES launch service explicitly admits only the GCE VM range-cell
adapter; AWS and GDC must be recorded as tested fail-closed limitations for the
live RAES claim unless separate implementation evidence changes that fact.
Likewise, `Node.services` is L4 exposure intent, not service installation,
listener readiness, participant authorization, or public publication.

At this baseline the validation command, catalog router, and image-management
surfaces still consult `SHIFTER_RAES_NATIVE_PROVISIONING`, while current
ADR-024/#1862 describe a no-selector hard cut. #1538 must not resolve that
contradiction by restoring an old path or adding another compatibility switch.
If the selector remains at evidence capture, record its exact posture and bound
the verdict to this runtime verification gate; do not claim that the repository
has independently demonstrated ADR-024's complete no-selector cutover.

## Extensibility Seam

The gate's extension seam is one evidence row parameterized by:

- stable claim id and canonical producer;
- exact source revision;
- installation backend, range backend, RAES profile, and environment scope
  where applicable;
- immutable producer-owned locator and observed conclusion; and
- explicit limitation/freshness statement.

The next provider, RAES version/profile, validation pack, or tenant class adds a
row and producer-native evidence. It does not add provider branches to domain
services, a gate-local schema, a workflow switch, a report database, or a
second conformance runner. Runtime extensibility remains at the existing
`BackendBundle` registry, RAES manifest/transport version policy, provider
adapter factories, and parameterized validation scenario—not in the evidence
document.

## Whole-Repository Scope

Implementation must evaluate these surfaces together while normally changing
only the bounded reviewed evidence pointer:

- ADRs and guidance: `docs/adr/index.yaml` ADR-011/024/031/032/034/039/041,
  `docs/adr/exceptions.yaml`, `raes-hard-cutover-preflight-1862.md`,
  `root-configured-backend-bundles.md`,
  `rev1-release-evidence-integration-preflight-1540.md`, and the historical
  #728/#729/#1522/#1562/#1566/#1569 preflights;
- backend config: `shifter/installation/**`, checked AWS/GCP examples, published
  contract/snapshots, backend renderers, and installation tests/CI lane;
- runtime config/security: `config/_runtime_env.py`, `_cloud.py`,
  `_raes_settings.py`, `env-manifest.json`, `entrypoint*.sh`, task env
  forwarding/admission, Helm/Terraform runtime projections, and both cloud
  factory families;
- RAES shared boundary: `shared/raes/**`, `shared/schemas/raes_*.py`,
  backend manifest artifact, package validation, object source, content
  delivery, operation persistence/projections, and shared RAES tests;
- product boundary: CMS registry/launch/validation services and permissions,
  image-management service/API/command/SPA, Engine range/operation input and
  result apply, launch intent, audit/outbox, Mission Control redacted reads, and
  their tests;
- provisioner boundary: `raes_plan*`, domain/composition/service/ACL/image
  validators, GCE plan/firewall/apply/destroy, guest executors/orchestrators,
  composition/content/account/feature/AD verification, snapshot reduction,
  result reporting, cleanup, and tests;
- validation content: `scenario-dev/shifter-raes-validation/**`, including the
  environment-pack manifest, associated-artifact digest, delivery projection,
  authored service, image source, content, account, and feature;
- enforcement/evidence: root `Makefile`, `.github/workflows/_quality.yml`,
  `.github/quality-path-filters.yaml`, `.pre-commit-config.yaml`,
  `.importlinter`, `scripts/check_layer_imports/**`, `scripts/adr_guard/**`, and
  canonical issue/run/final-report records.

The runtime layers that may see the verified artifacts are the operator shell,
GitHub-hosted CI, deployment renderer, portal/worker processes, provisioner
task/job, provider APIs, object storage, database, guest SSH/PowerShell
processes, and the reviewed evidence consumer. The pointer bundle must not
become a transport between any of them.

## Gotchas And Anti-Patterns

- Do not restore ACES imports, identifiers, env keys, routes, models, transport
  readers, aliases, or dual-read compatibility to make historical issue prose
  match current code.
- Do not collapse backend-bundle conformance, RAES manifest conformance,
  ADR-039 lifecycle conformance, and live realization into one "provider
  conformance" result.
- Do not claim AWS RAES support from an AWS `BackendBundle`, or GDC RAES support
  from `CLOUD_PROVIDER=gcp`. The current live adapter is GCE-specific.
- Do not treat a closed issue, merged dependency, source file, test name,
  generated manifest, configured image mapping, or successful deployment as
  execution evidence for a different claim.
- Do not treat package validity, package conformance, catalog launchability,
  image realizability, dispatch acceptance, provider readiness, service
  reachability, and guest outcome as synonyms.
- Do not treat an image mapping as provider image existence, a service firewall
  as a listening service, an object download as a digest-verified package
  launch, or VM/command/marker success as guest realization.
- Do not duplicate RAES/package/image/operation schemas, validation, exception
  hierarchies, lifecycle enums, workflow routing, provider registries, evidence
  stores, repositories, sanitizers, or guest executors for the gate.
- Do not scrape or persist raw process logs. The live command's traceback,
  provider responses, Terraform/SSM/SSH output, guest stdout/stderr, and
  environment dumps are not sanitized evidence.
- Do not publish user email, scenario/range/request identifiers, internal
  addresses, concrete image refs, object bucket/key, digests that reveal
  sensitive content identity, secret refs/values, credentials, signed URLs,
  provider ids/payloads, or raw snapshot entries. Use bounded counts, closed
  reason/status classes, timestamps, commit ids, and immutable locators.
- Do not truncate, sample, or omit a failed composition item to obtain a
  successful snapshot; do not let one fan-out instance stand for its siblings.
- Do not make an unsupported capability pass by silently skipping it, defaulting
  to AWS/TCP/current version, widening a firewall, inferring an image, or
  approximating a guest effect. Narrow the claim and prove fail-closed behavior.
- Do not change workflow permissions, trigger credentialed runs, deploy, mutate
  cloud state, alter the runtime selector, or close blocker issues merely to
  assemble the pointer bundle without separate authorization.

## Non-Goals And Implementation Boundaries

- No runtime, provider, Terraform, Kubernetes, workflow, API, model, migration,
  schema, serializer, repository, exception, logger, or feature-flag change in
  this preflight.
- No implementation or remediation of #728, #729, #1562, #1566, #1567, #1569,
  their dependency chains, ADR-039 gaps, the hard-cut selector contradiction,
  or parallel security/refactor work.
- No new cloud provider, RAES profile/version/capability, range-substrate
  operation, image resolver, package source, service audience, participant
  access path, guest transport, or scenario-verification adapter.
- No repository-wide architecture-compliance, security, cutover, rollback,
  performance, or release-readiness claim. #1538 verifies only its stated
  contract/runtime exit boundary and discloses adjacent limitations.
- No evidence capture or external issue/run lookup in this preflight. The
  implementation must link producer-owned reviewed records at the exact gate
  revision rather than copying their contents.

## Validation For This Architecture Change

```bash
python3 scripts/adr_guard/adr_guard.py --files \
  docs/architecture/rev1-contract-runtime-exit-preflight-1538.md \
  docs/architecture/rev1/roadmap.md \
  --level fast
```
