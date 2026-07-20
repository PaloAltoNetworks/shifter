# REV1 Production-Path Quality Ownership Preflight (#1530)

Status: pre-implementation guidance

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1530>

Revalidated against `dev`: 2026-07-17

## Decision

Evolve `.github/quality-path-filters.yaml` into the single versioned,
machine-readable quality-ownership contract. Each production quality unit must
map its source paths to at least one effective lint, security, and
test/validation job
in `.github/workflows/_quality.yml`. The same contract must drive changed-path
classification and the repository conformance check; do not add a second
source-to-job registry or preserve the current inline classifier as a separate
implementation of the schema.

The conformance check has three independent obligations:

1. **Estate completeness:** every git-tracked path is either covered by a
   production quality unit or a narrow, typed exclusion. An unknown path fails
   closed.
2. **Ownership completeness:** every production quality unit declares lint,
   security, and test/validation responsibility. Advisory-only jobs do not
   satisfy a required responsibility.
3. **Routing reachability:** for a representative changed path, the real
   workflow selects the declared quality-unit jobs (including matrix members), while a
   docs-only or other excluded path does not accidentally select production
   jobs. Merely naming an existing job in YAML is not proof of routing.

Changed-path classification is the fail-closed execution boundary. The helper
that reads this contract must validate the changed paths before it emits any
job-selection output from `_quality.yml`'s always-present `paths` job. The
unknown-path check must not live only in the currently path-gated
`adr-conformance` job: an unowned path would otherwise skip the check designed
to reject it. Full-estate reconciliation can additionally run through ADR
conformance when the contract or guard changes, but changed-path rejection may
not depend on already having an owner.

This is repository quality-control architecture. It adds no application model,
DTO, API schema, service, repository, persistence table, runtime exception
hierarchy, or application logging surface.

## Landed Dependency On #1523

Issue #1523 owns the whole-platform classification of first-party Django/Python
packages as domain, presentation, or support packages. It has now landed on
`dev`; the canonical classification is the `classification` section of
`scripts/check_layer_imports/layer_imports.yaml`. It names `engine`, `cms`,
`management`, `ctf`, and `risk_register` as domain packages,
`mission_control` as presentation, `shared` as support/contracts, and `config`
as support/composition. `scripts/adr_guard/adr_guard.py`
`check_installed_apps_classified` and
`scripts/adr_guard/tests/test_installed_apps_classified.py` already reconcile
that policy with tracked local `AppConfig` packages and `INSTALLED_APPS`.
#1530 must consume those identifiers instead of creating a parallel package
taxonomy.

For `shifter/shifter_platform`, package membership comes from #1523 and quality
ownership adds lint/security/test responsibility to those classified packages.
It must not restate `INSTALLED_APPS` or maintain a second hand-written app list.
The cross-check must reject both directions of drift: a #1523 first-party
package without quality ownership and a quality-unit entry that references a missing
or unclassified first-party package. Non-package platform assets such as the
SPA, templates, static assets, and image inputs remain explicit quality-unit
entries rather than being mislabeled as domain packages.

Implementation must begin from a branch containing the landed #1523 changes.
The dependency is no longer blocked on `dev`, but a placeholder schema,
hard-coded eight-package copy, or implementation against this branch's older
pre-#1523 tree is not an acceptable substitute for syncing the dependency.

## Keep These Concepts Separate

- **Architecture classification** answers what a first-party package is and
  which dependency boundary applies. #1523 owns it.
- **Quality ownership** answers which blocking jobs must run when production
  source changes. This issue owns it.
- **Deploy routing** answers which environment plan/build/deploy may run.
  `.github/workflows/deploy.yml` remains authoritative; a quality unit must not
  be placed in a deploy bucket merely to make Quality run.
- **Coverage ownership** answers which production source contributes to a
  package coverage floor. Package configuration and #1529 own it; a path may
  require tests without publishing coverage.
- **Review ownership** answers which humans approve a path. `.github/CODEOWNERS`
  owns it. A quality-unit id or job responsibility is not a team/user owner and
  must not silently become a second review-owner registry.
- **Tool discovery** (for example, finding `pyproject.toml`, `package.json`,
  Terraform directories, charts, Dockerfiles, or Packer templates) is a drift
  signal, not automatic proof that the nearest package owns the right jobs.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Quality path data | `.github/quality-path-filters.yaml` | Evolve this artifact in place with `schema_version`, production quality units, job responsibilities, and typed exclusions. Do not add a sibling ownership matrix that can drift from it. |
| Changed-path execution | `.github/workflows/_quality.yml` `paths` job and its fixed outputs | Replace the current inline classifier with one repository helper that reads and validates the canonical contract before emitting outputs. This job is the always-present rejection point for an unknown changed path. `run_full_matrix`, Sonar selection, and MCP package matrices remain derived outputs, not second policy tables. |
| Outer Quality gate | `.github/workflows/deploy.yml` `quality_relevant`, `quality_only`, guardrail-doc handling, and `pr-gate` | Preserve ordinary docs-only skipping and fail-closed PR Gate behavior. Quality ownership must not widen Terraform/deploy filters. Reuse the same classification semantics or assert exact reconciliation. |
| Workflow-as-data validation | `scripts/adr_guard/adr_guard.py` `_dw_*` safe YAML loader, `_DwShapeError`, constrained condition evaluator, path matcher, `Violation` reporting, and deploy-routing checks | Extend the repo-native semantic model; do not use grep/substrings, execute GitHub Actions, or create a second workflow parser/exception hierarchy. |
| Guardrail tests | `scripts/adr_guard/tests/test_adr_guard.py`, `test_deploy_workflow.py`, and `test_installed_apps_classified.py` from #1523 | Put schema, estate, rename, new-package, exclusion, and semantic-routing mutations beside the existing guardrail tests; reuse the package-classification helpers instead of copying their fixtures into a second parser. |
| Estate-classification precedent | `platform/terraform/validation-inventory.yaml` and `scripts/check_tf_roots/` | Reuse its fail-closed principles: closed keys/enums, contained paths, unique identifiers, tracked-estate reconciliation, missing-path rejection, and negative mutation tests. Do not copy its Terraform-specific model. |
| First-party package taxonomy | `scripts/check_layer_imports/layer_imports.yaml` `classification`, `.importlinter`, `check_installed_apps_classified`, and Django `INSTALLED_APPS` | Reference and reconcile the landed #1523 identifiers. Never infer architectural layer from a quality job name or restate the eight-package set. |
| Stack-native policy | Package `pyproject.toml`/`package.json`, `.importlinter`, `.tflint.hcl`, `.kube-linter.yaml`, `platform/terraform/.checkov.yaml`, `.gitleaks.toml`, Sonar configuration, and Terraform validation inventory | Matrix ownership points at jobs that already consume these policies; it does not duplicate lint, security, warning, coverage, secret-detection, or validation settings. |
| Generated/vendor hygiene | `.gitignore`, ADR-004-R8 `no-tracked-generated-artifacts`, generated-contract drift gates, dependency lockfiles, and existing vendored-browser-asset integrity policy | Reuse provenance-specific controls. A narrow ownership exclusion may classify non-shipped material, but it must not override an incumbent guard or exempt a tracked build/runtime input. |
| ADR enforcement | ADR-003 quality/deploy routing, ADR-004 quality tooling, `docs/adr/index.yaml`, `docs/adr/exceptions.yaml`, and `docs/technical/dev/{adr-enforcement,ci-cd}.md` | When the executable rule lands, add a named ADR-004 rule/check and update enforcement docs in the same change. Do not amend the registry now to claim an unimplemented guard. |

## Ownership And Exclusion Semantics

The schema must be closed and versioned. A quality unit is a stable logical
component id, not a person or CODEOWNERS entry. Quality-unit ids, paths,
optional #1523 package identifiers, and job ids must be unique and
repository-relative where applicable. Job responsibility is a closed
vocabulary of `lint`, `security`, and `test`; an explicit workflow matrix
selector is required where one GitHub job serves multiple packages (currently
the MCP jobs). Referenced jobs and matrix members must exist.

One blocking job may satisfy more than one responsibility only when its command
actually enforces both policies. For example, an ESLint job may own lint and
JavaScript security when the package's canonical ESLint configuration enables
the reviewed security rules. Global gitleaks is additive secret protection; it
does not by itself satisfy stack-specific security ownership. Likewise,
`security-trivy-advisory`, `security-osv-advisory`, and the current soft-fail
Kubernetes Checkov job are evidence surfaces, not blocking owners.

Exclusions require a type and reason and must be narrower than production
owners. At minimum, distinguish ordinary documentation, tests/fixtures,
generated artifacts, vendored third-party material, and repository/agent
metadata. Do not permit a generic catch-all exclusion or an unowned remainder.
Exclusion precedence and overlap must be deterministic; overlapping owner and
exclusion patterns are a schema error unless the contract has one explicit,
tested more-specific rule.

`generated` and `vendor` describe provenance, not safety or deploy impact. A
tracked generated contract consumed by a build (for example the SPA generated
API types) and vendored assets shipped to browsers still require their owning
package's route or a dedicated integrity/regeneration gate. Broad patterns such
as `**/generated/**`, `**/vendor/**`, lockfiles, Dockerfiles, charts, or generated
type declarations must not silently exempt shipped inputs. Ignored build output
and dependency directories should normally be absent from `git ls-files`, not
papered over by ownership exclusions.

Ordinary docs-only paths may skip broad Quality under ADR-003, while guardrail
docs remain quality-relevant. Tests must cover both classes and mixed diffs: a
documentation file plus one production file is production-relevant.

## Existing Gaps The Guard Must Expose

The implementation must baseline real ownership, not declare the current
categories correct by construction. Current notable reconciliation points are:

- `platform/charts/**`, the Identity Platform function package under
  `platform/terraform/gcp/modules/**`, scenario container Dockerfiles, and the
  Guacamole/guacd image inputs are not visible as independent owners in the
  current flat filter file. They need deliberate ownership or a justified,
  tested classification; a parent path coincidentally triggering a job is not
  enough if that job never scans or validates the artifact.
- `cyberscript` currently routes tests and platform type-checking but has no
  explicit blocking lint/SAST job of its own.
- `mcp/shared` routes the MCP lint matrix but is intentionally absent from the
  MCP test matrix; a new shared package or rename must not inherit a false test
  claim.
- several script categories have lint and tests but no category-specific
  blocking security job; `ctfd_workshop` has only a test job.
- Kubernetes Checkov is advisory. Blocking kube-linter/schema validation may
  satisfy reviewed security/test responsibilities where its policy truly does,
  but the matrix must not label advisory Checkov as a hard gate.
- Packer ownership must distinguish Python helper checks from validation of
  Packer HCL and image scripts; pointing the whole tree at Python Ruff/Bandit is
  not evidence that those other source types are checked.

These observations do not require #1530 to redesign every toolchain, but the
three-owner invariant cannot ship by using inaccurate labels. A missing owner
must either gain a real blocking incumbent or remain a visible failing gap;
there is no `not_applicable`, `covered_elsewhere`, advisory, or permanent
grandfather mode for production source. Time-bounded exceptions, if genuinely
needed, use `docs/adr/exceptions.yaml` with an owner and expiry rather than an
untyped matrix escape hatch.

## Cross-Cutting Layers The Intended Design Must Pass

| Layer | Required behavior |
| --- | --- |
| GitHub auth/event surface | Run classification and conformance on GitHub-hosted runners with `contents: read`. The classifier receives no secret, environment, `id-token: write`, write scope, cloud credential, or self-hosted runner. The reusable workflow's existing `SONAR_TOKEN` remains scoped to the Sonar step and is not classifier input. PRs from untrusted code must not reach privileged jobs through this change. |
| Secret-handling surface | Read repository paths, workflow/config structure, and fixed Git metadata only. Never source dotenv/deploy config, print workflow secret values or environment dumps, or upload parsed workflow bodies. Diagnostics may name a path, quality-unit id, responsibility, and job id. |
| Configuration shape | Parse YAML with `yaml.safe_load`; enforce schema version, closed keys/enums, contained relative paths, unique ids, valid classification/job references, nonempty responsibility sets, deterministic overlap, and explicit exclusion reasons. Missing or malformed structure fails, never means “not applicable.” |
| Workflow policy | `actionlint` owns syntax. The `paths` job invokes the canonical helper and fails before outputs on an unknown path or invalid contract. The semantic guard proves that representative changed paths make the declared `_quality.yml` job conditions and matrix selectors reachable and that skipped tests cannot satisfy production test ownership. ADR-003 remains the outer Quality/deploy gate. |
| Git/path boundary | Reconcile against git-tracked files and include staged/untracked non-ignored files for local checks, following `adr_guard` precedent. Use NUL-delimited Git output so whitespace/newlines in a filename cannot corrupt classification. Normalize repository-relative POSIX paths and reject absolute paths, `..`, empty components, control characters, and ambiguous duplicates. |
| OS/process exposure | Invoke Git and helpers with fixed argv; never `eval` a path, interpolate a path into a shell command, or emit untrusted path text as a GitHub output key. Fixed output keys and single-line JSON values are safe; changed paths are data. No secret belongs in argv, logs, cache keys, artifacts, or summaries. |
| Error envelope | This is a CLI/CI guard, not an HTTP endpoint. Reuse `_DwShapeError` for fail-closed workflow-shape parsing and adapt failures to `adr_guard.Violation` plus the ordinary nonzero CLI exit; do not add an application exception family. Errors name the violated rule and safe repository metadata, not file contents, DSNs, tokens, environment values, or swallowed subprocess output. |
| Logging/observability | Existing test assertions, ADR-guard diagnostics, job results, and PR Gate are sufficient. Emit selected quality-unit/job ids when useful; add no runtime logger, audit model, telemetry service, database, or durable result store. |
| Persistence | None. The canonical YAML and workflow are source-controlled policy; temporary diff/matrix data stays in runner memory or `RUNNER_TEMP`. |

## Required Verification Shape

Negative fixtures are the load-bearing evidence. They must prove that:

- an unknown production directory/file makes the always-executed classifier
  fail before it can emit an empty/no-op job matrix;
- adding a first-party package marker or #1523 classification without quality
  ownership fails;
- renaming an owned package/path while leaving the old glob fails both missing
  path and unowned-new-path checks;
- deleting each of lint, security, or test responsibility fails independently;
- a referenced missing job, renamed job, wrong category condition, advisory or
  `continue-on-error` owner, skipped-test-only route, and wrong MCP matrix member
  fail;
- ordinary docs-only, guardrail docs, generated, and vendor examples match only
  their reviewed classifications, and broad exclusion mutations fail;
- a mixed docs/production diff still routes production jobs; and
- changing the ownership contract or classifier routes the guard's own tests
  and architecture conformance, preventing self-bypass.

Use synthetic repositories/workflows and pure path sets for most cases. Do not
depend on network access, GitHub APIs, cloud tools, credentials, or executing an
Actions runner. Keep one integration assertion against the checked-in estate
and checked-in `_quality.yml`.

## Extensibility Seam

The seam is an explicit **quality-unit record** plus optional **workflow matrix
selector** and **#1523 package identifier**. Adding the next Python/Node
package, chart, image input, or infrastructure family should require one
quality-unit record and its real jobs, without editing hard-coded category sets
such as the current `SONAR_CATEGORIES`, `MCP_LINT_PACKAGES`, or
`MCP_TEST_PACKAGES` in multiple places. Derived concerns such as Sonar
participation should be quality-unit metadata or package policy, not another
path list.

Do not make arbitrary commands, shell fragments, or tool arguments part of the
data seam. The workflow owns fixed commands; the matrix selects reviewed jobs
and fixed parameters only.

## Whole-Repository Scope

The implementation's control-plane scope is `.github/quality-path-filters.yaml`,
`.github/workflows/_quality.yml`, the Quality invocation and docs-only routing
in `.github/workflows/deploy.yml`, `scripts/adr_guard/**`, #1523's
`scripts/check_layer_imports/layer_imports.yaml` classification and
`check_installed_apps_classified` guard, `docs/adr/{index,exceptions}.yaml`, and
`docs/technical/dev/{adr-enforcement,ci-cd}.md`. Package manifests,
`.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
`platform/terraform/validation-inventory.yaml`, `.tflint.hcl`,
`.kube-linter.yaml`, `platform/terraform/.checkov.yaml`, Sonar configuration,
Dockerfiles, charts, Packer files, K8s manifests, scripts, MCP packages, the SPA,
and package test configuration are reconciliation inputs; they should change
only when closing a real ownership gap.

## Gotchas And Anti-Patterns

- Do not validate only the ownership YAML. Prove route reachability against the
  parsed workflow and matrix outputs.
- Do not gate unknown-path detection on `paths.outputs.adr_guard`, a declared
  quality-unit category, or any output produced by the policy being checked. That is a
  self-bypass for every new unowned path.
- Do not use substring/regex checks for job `if:` expressions or duplicate the
  current inline Python classifier in a new checker.
- Do not make one broad `shifter/**`, `scripts/**`, or `platform/**` owner; it
  hides new packages exactly as the current routing does.
- Do not infer that a job scans a path because the job happened to run. Its
  command/policy scope must genuinely include the owned artifact.
- Do not count always-running gitleaks, Sonar, advisory scanners, soft-fail jobs,
  or a skipped job as the sole required owner.
- Do not treat test files, coverage ownership, package classification, and
  production source as interchangeable concepts.
- Do not make docs-only detection extension-only without preserving guardrail
  docs and mixed-diff behavior.
- Do not enumerate ignored `node_modules`, virtualenvs, caches, coverage, build
  output, or generated runtime secrets as normal vendor/generated exclusions;
  tracked copies are a separate repository-hygiene failure.
- Do not route support/test files through production deploy filters to make
  Quality visible; keep `quality_only` and deploy boundaries intact.
- Do not weaken `skip_tests: false`, PR Gate, actionlint, ADR conformance,
  stack-native policies, or existing package jobs to make reconciliation pass.

## Non-Goals And Boundaries

- No application behavior, auth/authorization, database migration, API/schema,
  runtime configuration, cloud deployment, or production observability change.
- No replacement workflow engine, generic CI DSL, package manager, test runner,
  coverage system, security scanner, import-boundary system, or exception
  hierarchy.
- No automatic creation of jobs from discovered files and no claim that a
  manifest alone defines production ownership.
- No CODEOWNERS generation or review-owner registry. Human review ownership and
  quality-job responsibility remain distinct contracts.
- No unification of deploy routing and quality ownership; they share changed
  paths but answer different questions and must be reconciled without letting
  quality data authorize a deployment.
- No broad remediation of unrelated test/security debt. Close only gaps needed
  for truthful ownership, and leave unrelated scanner findings to their owning
  work.
- No Ground Control requirement or traceability object; GitHub issue #1530 is
  the authoritative contract.
