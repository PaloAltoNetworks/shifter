# REV1 Release-Evidence Integration Preflight (#1540)

Status: pre-implementation architecture guidance

Date: 2026-07-21

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1540>

This is a requirement-free preflight. GitHub issue #1540 is the shipping
contract. This note does not publish the release-evidence index, rerun a gate,
change a workflow, cut over ACES, or implement issue #1539.

## Boundary And Decisions

Issue #1540 is an integration and provenance concern, not a new verification
framework. Its one output is a bounded index that lets #1539 find and interpret
the existing release evidence without copying the evidence or redefining its
verdict.

- Publish one Markdown index at
  `docs/architecture/rev1-release-evidence-index-1540.md`. The consumer is a
  release reviewer, so a new YAML/JSON schema, parser, database model, API DTO,
  evidence service, workflow job, or status enum is not justified.
- The index is a pointer layer. Each row identifies the concern, canonical
  producer/authority, exact revision and environment scope, evidence locator,
  observed producer conclusion, blocking posture, and any limitation. The
  linked producer remains authoritative for the verdict and diagnostics.
- Pin execution evidence to an exact commit SHA and, for live evidence, the
  provider, tenant/environment, execution time, tool/profile, and immutable
  workflow/report reference. A branch name, latest-run link, source file, test
  name, issue number, or prose assertion alone is not execution evidence.
- Keep static PR/CI evidence, built-image smoke, deployed-environment smoke,
  ACES live realization, cutover authorization, and rollback proof as separate
  rows. They have different trust, freshness, credentials, and failure
  semantics and cannot be collapsed into one green "verification" label.
- Resolve contradictions by naming the actual executable posture. A
  `continue-on-error`, soft-fail, advisory scan, design note, mocked test, or
  unexercised rollback selector must never be described as a blocking passed
  gate. The index records the limitation or an unresolved gap; it does not
  manufacture stronger evidence.
- #1528, #1529, and #1530 are the only native blocking dependencies for closing
  #1540. Record their completion from their canonical merged changes/issues,
  not by inferring completion from similar files. Other evidence rows are
  indexed, not re-owned or duplicated by #1540; #1539 decides release
  readiness from the disclosed evidence and limitations.

No ADR change is needed. ADR-003/004 own CI routing and enforcement, ADR-011
owns backend-bundle configuration, ADR-024 owns the ACES parity-gated
migration, ADR-031/032/034 own ACES launch and realization evidence, and ADR-039
owns provider-neutral range-substrate conformance. The index must cite these
authorities rather than restating their contracts.

## Canonical Evidence Map

| Concern | Canonical incumbent | Qualifying evidence | Boundary that must remain visible |
| --- | --- | --- | --- |
| Terraform-root validation (#1528) | `platform/terraform/validation-inventory.yaml`, `scripts/check_tf_roots/`, `.github/workflows/_quality.yml` `terraform-matrix`, `terraform-validate`, and `terraform-module-contracts` | Successful routed Quality/PR run at the indexed SHA, with every inventory-selected root visible; implementation closure points to #1528/its merged change | Backendless locked `init` + `validate` is not TFLint, Checkov, a plan/apply, module conformance, or live-provider evidence. Do not copy the root list into the index. |
| Clean-checkout commands and metrics (#1529) | Root `Makefile`, `docs/dev/testing.md`, package `pyproject.toml`/`package.json`, `uv.lock`/`package-lock.json`, `_quality.yml`, `sonar-project.properties`, and `tests/platform/test_clean_checkout_posture.py` | Exact clean-checkout commands plus successful package jobs and the authoritative package-local coverage floors/Sonar `aces-strict` result at the indexed SHA | Do not paste a second command body or coverage baseline into the index. SQLite coverage does not prove PostgreSQL, Redis, browser, built-image, or live-cloud behavior. |
| Production-path quality ownership (#1530) | `.github/quality-path-filters.yaml`, `scripts/quality_ownership/{contract,classify_paths}.py`, `_quality.yml` `paths`, `scripts/adr_guard/adr_guard.py` `quality-path-ownership`, ADR-004-R24 | Successful classifier/ADR-conformance evidence and the real routed jobs for the indexed diff; closure points to #1530/its merged change | Quality ownership, architecture taxonomy, deploy routing, coverage ownership, CODEOWNERS, and tool discovery are separate concepts. Never reproduce the ownership matrix in the release index. |
| Security gate | `.github/workflows/deploy.yml` `PR Gate`; routed blocking SAST jobs, Terraform `security-iac`, `secrets-gitleaks`, and PR-waiting SonarCloud in `_quality.yml`; branch-protection contexts documented in `docs/adr/README.md` | Exact PR and required-context conclusions for the release SHA, with the selected blocking security jobs named by their workflow ids | Kubernetes Checkov, Trivy, OSV, and the current CodeQL upload are advisory/soft-fail in executable workflow posture. `docs/architecture/rev1/security.md` is a review/finding source, not proof that its findings are remediated. Do not label advisory signal as a passed release gate. |
| AWS/GCP backend configuration conformance | `shifter/installation/{loader,schema,contract,registry,publication}.py`, the published backend-bundle contract, `examples/{aws,gcp}.yaml`, and installation tests | Successful installation lane proving both shipped examples, closed settings models, publication drift/breaking-change checks, and registry conformance at the indexed SHA | This proves bundle/config contract conformance. It does not prove the provider can realize a range or satisfy ADR-039 lifecycle/security obligations. |
| AWS/GCP range-substrate conformance | ADR-039 and `docs/architecture/provider-neutral-range-substrate.md` | The shared black-box suite for each adapter plus disposable real-provider evidence for any adapter claimed stable/eligible | A registry entry, unit test, Terraform validation, deploy success, or one smoke launch is not four-operation provider conformance. GCP GDC's documented pause/resume and losslessness gaps must remain explicit until closed; static bundle conformance cannot hide them. |
| ACES manifest conformance | `shared.aces.manifest`, checked-in `shared/aces/backend-manifest.json`, `tests/shared/aces/test_backend_{manifest_publication,conformance_gate}.py`, and parity row `validation.aces-manifest-conformance` | Successful platform test gate against the `provisioning-only` profile at the indexed SHA | Manifest/profile conformance is not package conformance, launchability, guest realization, participant-runtime support, or live target evidence. |
| ACES realization | `cms.management.commands.run_aces_backend_validation`, `cms.aces.validation`, `shared.aces.projections`, `shared.schemas.aces_operation`, and `docs/architecture/aces-cutover-evidence-1264.md` | A deployed-environment run through normal registry/CMS/engine/task-runner/provisioner dispatch, reaching `READY`, a succeeded status, and a non-vacuous redacted runtime snapshot with verified content/account/feature entries, followed by teardown unless deliberately retained | Unit tests and `test_composition_realization_e2e.py` prove contracts but do not replace the live run. VM creation, command exit, marker files, raw logs, direct Terraform/provider calls, or seeded sidecars are not realization evidence. |
| Live smoke | Built-image `stack-smoke` in `_quality.yml`; deployed AWS `post-deploy-smoke` in `_shifter-platform.yml`; ACES live validation above; Polaris range/operator evidence under its canonical harness | Separate exact run/report references for each claimed layer and provider/environment | Built-image smoke has no cloud credentials and is not deployed smoke. The current AWS post-deploy smoke is `continue-on-error`; it opens an issue and does not block deploy. Do not infer GCP or ACES coverage from it, and do not combine these rows into one passed smoke gate. |
| Cutover authorization | ADR-024, `docs/architecture/aces-migration-parity-inventory.yaml`, `docs/architecture/aces-migration-adr.md`, and `aces-cutover-archive-plan-preflight-1238.md` | A reviewed cutover record that identifies the exact selector/default change, accepted profile/scope, parity evidence bundle, known gaps, rollback window, and release SHA | Design notes and an enabled feature flag are prerequisites, not evidence that a default cutover was authorized or executed. #1540 must index the cutover record, not become it. |
| Rollback | ADR-024 rollback posture, the default-off `SHIFTER_ACES_NATIVE_PROVISIONING` binding in `config/_aces_settings.py`, config/env inventory, preserved legacy reference path, and the cutover record | Evidence that the release's actual selector can restore the named legacy path within the stated window, with the restored path validated; after default cutover, a documented rollback rehearsal/result is required | Toggle existence, `--keep`, cleanup success, or retained legacy files alone is not rollback proof. Do not archive the legacy path while the rollback window depends on it. |

The backend rows intentionally distinguish three meanings often called
"conformance": installation bundle/schema conformance, ADR-039 provider
lifecycle conformance, and ACES backend manifest/profile conformance. A green
result in one is not evidence for either of the others.

## Index Contract Without A New Schema

The Markdown table is bounded to one row per evidence class and provider/profile
variation that changes the conclusion. Each row carries only:

- a stable concern id and short claim;
- the canonical definition/producer path or ADR rule;
- exact commit SHA and, where applicable, provider/environment/profile;
- an exact workflow run, canonical redacted report, or reviewed cutover/rollback
  record reference;
- the producer's conclusion and its actual posture (`blocking`, `advisory`,
  `live-manual`, or `not-yet-demonstrated`); and
- a short freshness/scope limitation or open gap.

These labels describe how existing evidence was produced; they are not a new
lifecycle enum and must not be imported into application or workflow code.
Rows point to existing evidence and may quote only bounded non-secret counts or
verdicts. They must not embed logs, SARIF, coverage files, Terraform output,
runtime snapshots, provider payloads, environment dumps, issue bodies, or
copied gate definitions.

If a referenced artifact will expire before #1539 consumes it, the producer
must publish its own canonical redacted durable report or reviewed record. The
index must not preserve an expiring artifact by copying sensitive/raw content
into the repository. A missing, inaccessible, stale, wrong-SHA, wrong-provider,
or contradictory reference is `not-yet-demonstrated`, not a guessed pass.

## Required Cross-Cutting Reuse

| Concern | Incumbent to reuse | Guardrail |
| --- | --- | --- |
| CI routing and dependency closure | `deploy.yml`, `_quality.yml`, `.github/quality-path-filters.yaml`, quality-ownership classifier, `PR Gate` | Read actual job ids/results. Do not add an evidence workflow, second path router, or parallel dependency graph. |
| Terraform validation/security | Validation inventory/checker, `.tflint.hcl`, `platform/terraform/.checkov.yaml`, `scripts/check_tf_*`, ADR exception registry | Preserve distinct verdicts and waiver semantics. No aggregate "Terraform passed" row. |
| Test/metric policy | Make targets, package-local test/coverage configuration, lockfiles, Sonar config, `docs/dev/testing.md` | Link commands and results; do not restate metrics or test posture. |
| Backend config contracts | `installation` loader/schema/registry/publication and published contract snapshots | Do not invent a release-only backend matrix or validate AWS/GCP names independently. |
| ACES contracts and evidence | `shared.aces` manifest/contracts/operations/projections, `shared.schemas.aces_operation`, CMS validation command, parity inventory | Read through the existing redacted projection and gate. Do not query ORM rows, plans, or provider state directly. |
| Cutover/rollback governance | ADR-024/031/032/034/039, parity inventory, cutover/archive guidance, typed config/env inventory | Keep the index descriptive. Selector changes and rollback execution remain separately reviewed operational actions. |
| Exceptions | `docs/adr/exceptions.yaml` and the producing gate's native waiver mechanism | Link active exception ids/expiry where relevant. Do not create index-local waivers, suppressions, or "accepted" checkboxes. |
| Errors/logging | Ordinary workflow conclusions, `adr_guard.Violation`, installation `ConfigIssue`/`InstallationConfigError`, Django `CommandError`, `shared.log_sanitize`, provisioner `log_redact` | Surface fixed verdict/reason classes and references only. Do not add an evidence exception family or serialize raw exceptions. |
| Persistence/observability | GitHub job/run results, producer-owned reports, ACES bounded operation sidecars and redacted projections | Add no database, artifact store, audit row, log sink, or telemetry stream for the index. The source-controlled Markdown document is discovery metadata only. |

No controller, serializer, DTO, application service, repository, or persistence
model is needed. This work belongs in documentation and existing workflow/run
evidence. The ACES operation sidecar is reused only as the live gate's existing
evidence source; it must not become general release-evidence storage.

## Cross-Cutting Layers The Intended Design Must Pass

| Layer | Required behavior |
| --- | --- |
| GitHub auth and event trust | Read public/repository metadata and existing run conclusions only. Do not trigger deploys, rerun jobs, mutate issues, request `id-token: write`, use a self-hosted runner, or broaden workflow permissions merely to build the index. Preserve the PR hosted-only boundary and identify separately required branch-protection contexts. |
| Security validators | The indexed SHA must retain ADR guard, import boundaries, SAST, blocking Terraform Checkov, gitleaks, package tests, and PR-waiting Sonar as selected by the canonical ownership contract. Advisory K8s Checkov, Trivy, OSV, and CodeQL posture must be labeled accurately. Active ADR exceptions and expiry are part of the evidence scope. |
| Config shapes | Do not parse or duplicate `quality-path-filters`, Terraform inventory, installation bundles, ACES manifests, or env manifests in the index. The producing validators own closed keys, enums, path containment, duplicate rejection, and drift checks. Runtime ACES evidence continues through `shared.schemas.aces_operation` and `shared.aces.projections`. |
| Auth/application read surface | No new endpoint is needed. If live ACES evidence is collected, the existing management command owns operator context and reads the Mission Control-equivalent redacted projection. The index does not bypass CMS/Mission Control ownership, scope, or sidecar access through direct ORM/provider reads. |
| Secret handling | Index only commit/run/report refs, public job/profile ids, bounded counts, timestamps, and conclusions. Never include tokens, user email, secret references/values, env files, credentials, presigned URLs, CTF flags, answers, guest output, raw snapshot payloads, internal addressing, Terraform state/plan/output, or provider ids/payloads. `safe_log_value` is log-injection protection, not confidentiality redaction; do not copy a sanitized raw exception/log into the index. |
| OS/process exposure | The index needs no subprocess or runtime environment. Any separately authorized evidence collection uses incumbent fixed argv/management commands and passes secrets through their existing environment/secret-store bindings, never argv. Do not use `env`, `set -x`, shell evaluation, or command strings assembled from issue/report content. |
| Error envelopes | This is neither HTTP nor a new CLI. Use `missing`, `inaccessible`, `contradictory`, or the producer's bounded reason class in prose and keep raw workflow, ACES, Terraform, cloud, SSH, Docker, and provider exceptions behind their incumbent envelopes. Do not equate an inaccessible result with failure or success. |
| Logging and observability | Existing GitHub conclusions, job names, bounded management-command summary, request/run correlation, and producer-owned reports are sufficient. The index links them and records scope; it does not ingest logs or emit telemetry. |
| Persistence and retention | Git history persists the index. Producer systems retain their own evidence according to existing policy (including ACES operation-record retention and workflow artifact retention). The index contains no copied evidence blob and no retention override. |
| Workflow/architecture enforcement | A documentation-only preflight runs ADR guard. Any eventual workflow/guardrail edits also require ADR registry/enforcement-doc updates and `actionlint`; Terraform, platform Python, import, and Kubernetes edits inherit their stack-native checks. Do not weaken a producer to make its evidence easier to index. |

## Extensibility Seam

The seam is one additional evidence row parameterized by canonical concern id,
producer, revision, provider/environment/profile, reference, actual blocking
posture, and limitation. The next reasonable variation is another cloud
backend, ACES profile, tenant, or release candidate. It should add a row pointing
to that producer's native evidence, not a new index schema, workflow branch,
provider switch, report DTO, or evidence store.

Provider/profile is therefore data at the index edge. It must not be inferred
from branch names or collapsed into a global green state. If automated
consumption becomes a real requirement later, version a separate proposal
against #1539's demonstrated needs; do not prematurely turn this one-release
review table into repository policy.

## Whole-Repository Scope

The implementation must evaluate these existing surfaces together while
normally changing only the bounded index:

- issue foundations: `docs/architecture/terraform-root-pr-validation-preflight-1528.md`,
  `docs/architecture/rev1-testing-quality-preflight-1529.md`, and
  `docs/architecture/rev1-production-path-ownership-preflight-1530.md`;
- CI/security: `.github/workflows/{deploy,_quality,codeql-analysis}.yml`,
  `.github/quality-path-filters.yaml`, `sonar-project.properties`,
  `.gitleaks.toml`, `platform/terraform/.checkov.yaml`, and branch-protection
  documentation;
- Terraform validation: `platform/terraform/validation-inventory.yaml` and
  `scripts/check_tf_roots/`;
- clean testing: `Makefile`, `docs/dev/testing.md`, package-local test/coverage
  configs and locks, and clean-checkout posture tests;
- quality ownership: `scripts/quality_ownership/`, ADR-004-R24,
  `scripts/adr_guard/`, and `docs/adr/exceptions.yaml`;
- backend configuration: `shifter/installation/` registry, closed settings,
  examples, published contract/snapshots, and tests;
- backend runtime conformance: ADR-039 and
  `docs/architecture/provider-neutral-range-substrate.md`;
- ACES conformance/realization: the parity inventory, `shared/aces/`,
  `shared/schemas/aces_operation.py`, CMS ACES validation command, engine and
  provisioner realization path, and their contract/cross-boundary tests;
- live evidence: built-image stack smoke, deployed post-deploy smoke, ACES
  validation, and provider/scenario-specific operator reports;
- cutover/rollback: ADR-024/031/032/034, the cutover/archive guidance,
  `config/_aces_settings.py`, `config/env-manifest.json`, installation runtime
  inventory/renderers, and the preserved legacy selector/reference path.

Runtime hosts that may have produced linked evidence include GitHub-hosted PR
runners, credentialed self-hosted deploy runners, deployed portal/worker/
provisioner processes, cloud provider APIs, guest VMs, and the existing
operation-record store. The index itself executes on none of them and must not
carry their credentials or raw outputs.

## Gotchas And Anti-Patterns

- Do not make the index a checklist whose checked box overrides a failed,
  advisory, stale, or absent producer result.
- Do not duplicate gate commands, metrics, ownership paths, root inventories,
  backend capabilities, ACES manifests, parity rows, or rollback instructions.
- Do not call all security jobs blocking. In current workflow posture K8s
  Checkov, Trivy, OSV, and the CodeQL upload path are advisory/soft-fail; record
  that fact even if branch-protection prose lists a context.
- Do not treat the aggregate `PR Gate` as proof of jobs outside its dependency
  chain. Record separately required contexts and every path-routed security job
  relevant to the release diff.
- Do not call static AWS/GCP bundle publication tests provider runtime
  conformance, or call one successful launch ADR-039 four-operation
  conformance.
- Do not call ACES manifest conformance, package conformance, guest realization,
  live smoke, participant runtime, and cutover readiness the same gate.
- Do not treat the built-image stack smoke as live-cloud smoke. Do not hide the
  current deployed AWS smoke's `continue-on-error` posture or infer GCP
  coverage from it.
- Do not use mocked management-command tests, direct Terraform/provider calls,
  VM creation, startup markers, task submission, or seeded evidence rows as the
  live ACES proof.
- Do not expose logs or artifacts merely because a sanitizer was applied.
  `safe_log_value` prevents log injection but does not make emails, credentials,
  provider details, or raw exception messages publishable.
- Do not put tokens, secret references, user emails, range ids, internal hosts,
  provider ids, Terraform data, CTF flags, guest output, or raw ACES payloads in
  the index, comments, filenames, argv, or workflow summaries.
- Do not create an index-local exception, expiry override, evidence status
  taxonomy, duplicate error hierarchy, database, repository, API, logger,
  artifact store, or workflow.
- Do not interpret the existence of the default-off ACES flag or preserved
  legacy code as a tested rollback. The cutover record must name and evidence
  the actual restoration path for the release posture.
- Do not expand #1540 into the parallel email, SPA/accessibility,
  documentation-security, handbook, or backlog work that the issue explicitly
  excludes from release prerequisites.

## Non-Goals And Implementation Boundaries

- No implementation of #1540's evidence index in this preflight and no
  implementation of #1539.
- No gate execution, workflow dispatch, deploy, live range launch, cutover,
  rollback, issue transition, or external evidence publication.
- No change to CI routing, branch protection, security posture, coverage floors,
  Terraform inventory, backend contracts, ACES contracts, runtime settings, or
  legacy/ACES default selection.
- No remediation of security findings, advisory scanners, GCP substrate gaps,
  smoke blocking posture, or evidence retention. The index must disclose these
  accurately; each remediation remains owned by its native issue/surface.
- No new requirement, ADR, application schema, API/controller/DTO/service,
  repository, persistence model, event, exception family, logging system,
  workflow, or machine-readable evidence format.
- No duplication of the security, AWS/GCP conformance, ACES realization, live
  smoke, cutover, or rollback deliverables. #1540 links them; their canonical
  owners continue to define and produce them.
- No inclusion of email durability, SPA/accessibility,
  documentation-security maintenance, architecture-handbook work, or general
  backlog triage as release prerequisites.

## Validation Expectation

For this architecture note:

```bash
python3 scripts/adr_guard/adr_guard.py --files \
  docs/architecture/rev1-release-evidence-integration-preflight-1540.md \
  --level fast
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
