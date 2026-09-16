# ADR Enforcement

Architecture rules in this repo are enforced by tooling, not just prose.

## What Exists

The [model-access design for #681](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/index.md)
adds proposed ADR-059 through ADR-061 and documentation coverage for the
planned feature. Registry/import validation applies now. Runtime enforcement
of broker authorization, atomic budgets, revocation and provider isolation
must land with the owning implementation issues and their behavioral/cloud
tests; a passing documentation check is not evidence of those guarantees.
ADR-060-R3 also requires independently configurable sharing, explicit overlap
and membership rules, deduplicated pool accounting and separately revocable
range grants. The [sharing contract](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/sharing.md)
is consumed by #2139/#2140 and the downstream implementation/evidence issues;
it adds no waiver or claim of existing runtime enforcement.

The current enforcement stack has six parts:

1. `docs/adr/index.yaml`
   Machine-readable ADR registry. Each accepted ADR lists the rules and the checks that enforce them.

2. `docs/adr/exceptions.yaml`
   Explicit exceptions. If a rule needs a temporary waiver, record it here with an owner and expiry instead of leaving the exception implicit.

3. `scripts/adr_guard/` (the `adr_guard` tool)
   Repo-native policy runner and the entrypoint for ADR conformance checks.
   `adr_guard.py` is the executable CLI entry point and compatibility facade; it
   bootstraps `sys.path` once and re-exports the internal `_guard` package. The
   check logic lives in one module per concern family under `_guard/checks/` (for
   example `_guard/checks/k8s_security.py`, `_guard/checks/secret_hygiene.py`,
   `_guard/checks/deploy_workflow.py`) on top of the shared kernels
   `_guard/_common.py` (the `Violation` model, repo/git helpers, exception
   filtering) and `_guard/_workflow_model.py` (the `_dw_*` workflow-as-data
   model), with `_guard/_registry.py` holding the deterministic `CHECKS` /
   `CHECK_LEVELS` registry and `_guard/_cli.py` the argument parsing. The
   `_guard` package uses package-relative imports internally, so it is importable
   on its own; the facade re-exports its full public surface, so
   `python3 scripts/adr_guard/adr_guard.py` and tests that load it by path keep
   working unchanged. The package is in the SonarCloud analysis scope
   (`sonar.sources` in `sonar-project.properties`); the `adr-guard-tests` CI job
   runs the suite under `coverage` and uploads `scripts/adr_guard/coverage.xml`
   for the SonarCloud new-code coverage gate.

4. `.pre-commit-config.yaml`
   Fast local enforcement. The ADR guard runs before commit so architectural drift is caught locally.

5. `.github/workflows/_quality.yml`
   CI enforcement. ADR conformance runs as its own architecture gate.

6. Existing ecosystem tooling
   - `import-linter` for Python package contracts
   - `actionlint` for GitHub Actions workflows
   - `TFLint` for Terraform linting (including the `tflint-ruleset-google` plugin for GCP resources)
     The CI initialization step supplies the job-scoped `github.token` as
     `GITHUB_TOKEN`, so provider-plugin release lookups use the authenticated
     GitHub API allowance instead of the shared runner IP's unauthenticated
     rate limit.
   - `gitleaks` for new secret leakage detection
   - `helm lint` for Helm chart validation where files are templates rather than plain YAML
   - `kubeconform` for Kubernetes manifest schema validation
   - `kube-linter` for Kubernetes security and best-practice enforcement
   - `Checkov` for IaC security scanning (Terraform and Kubernetes)

There is also agent-specific wiring:

- `.claude/hooks/adr_guard_hook.py` runs the ADR guard after Claude edits files.
- `.claude/skills/adr-check/SKILL.md` provides a default workflow for ADR conformance work.
- `.claude/skills/architecture-review/SKILL.md` provides a repo-specific architecture review checklist.
- `AGENTS.md` gives Codex a repo-local policy file, including Ground Control project context for the `/implement` workflow. The GC project pointer (and matching `.ground-control.yaml` `project:` field) names the `shifter` project (id `df4e718f-1f67-46f8-a375-3ba53fabc9c4`) with `CTF-*`, `PLAT-*`, `GEN-*` UID prefixes by subsystem; an earlier draft incorrectly pointed both at `aphelion` (a separate, unrelated project).
- `.ground-control.yaml` is validated as a whole by the Ground Control context reader, so an unrecognized key fails the entire file closed rather than being ignored: the reader returns `invalid_ground_control_yaml`, and `/implement` loses the project, SonarCloud, and plan-rules context along with the offending block. The `routing:` block accepts only `enabled`, `default_provider`, and `stages`. Routing is advisory under ADR-036, annotating a stage's capability tier for telemetry without selecting an executor, so a stale routing key is worth deleting rather than reinterpreting.

Review controls:

- `.github/CODEOWNERS` requires review on guardrail files and shared/public architecture seams.
- `.github/pull_request_template.md` requires an ADR impact section on PRs.
- `.github/copilot-instructions.md` now points GitHub Copilot toward the same ADR enforcement model.
- `.ground-control.yaml` binds synchronized `/implement` runs to the root
  `make test` completion boundary. The companion `make policy` target runs the
  full ADR guard, import-linter contracts, diff whitespace validation, and Vale
  against Markdown changed from `origin/dev`; `tools/install-vale.sh` supplies
  the pinned local Vale binary when it is not already installed.
- `.ground-control.yaml` `workflow.precommit_command` is set to `pre-commit run`
  (staged-files scope) rather than the reader's `pre-commit run --all-files`
  default. Every hook in `.pre-commit-config.yaml` is already `files:`-scoped, so
  the staged run fires only the hooks whose module a `/implement` change actually
  touches (a `shifter/shifter_platform/**`-only change skips the
  packer/provisioner/bootstrap/installation/terraform/mcp test+lint hooks
  entirely, which dominate a full-repo `--all-files` run). This is not a gate
  weakening: CI's quality-path-ownership contract
  (`.github/quality-path-filters.yaml`, enforced by the `quality-path-ownership`
  adr_guard check) is the authoritative full-matrix gate and guarantees a
  blocking lint **and** security **and** test job for every production path, so
  the local publish pre-commit is scoped to the changed files to avoid
  re-running suites CI already owns. Developers may still run
  `pre-commit run --all-files` by hand.
- The `shifter_platform` pytest worker cap (`--maxprocesses` in
  `shifter/shifter_platform/pyproject.toml` `addopts`) is 8. Because `-n auto`
  already limits workers to the host core count, this cap only takes effect on
  hosts with more cores than the cap: CI runners (`ubuntu-latest`, ≤4 cores) are
  unaffected and keep running at core-count workers, while multi-core dev/CI
  machines get the added parallelism (which shortens the `pytest (shifter_platform)`
  pre-commit hook, the slowest step of an `/implement` publish). The cap also
  bounds peak memory (each worker loads the Django app), so it is raised only
  with headroom in mind given the suite's documented OOM history at high worker
  counts.
- `.github/workflows/_gcp-dev.yml` now pins `platform/k8s/gcp/overlays/gcp-dev/kustomization.yaml` image `newTag` values to `${SHORT_SHA}` before `kubectl apply -k`, preventing mutable `:latest` restarts from drifting to a different image than the commit being deployed.

Deploy-time enforcement (ADR-035):

- `scripts/bootstrap/preflight.py` is a shared, fail-safe deploy preflight. It is
  the single source of truth for deployment prerequisites (tools, secrets, config)
  and runs the same checks locally (the deploy CLI runs it at the start of
  `bootstrap`/`terraform`/`full`, and `deploy.py preflight` runs it on demand) and
  in CI (each reusable deploy workflow runs `python -m preflight` before any
  Terraform apply). It reports every missing prerequisite up front instead of
  failing lazily mid-run, and skips are always explicit and logged
  (`SHIFTER_SKIP_OPERATOR_BOOTSTRAP`), never a silent conditional step skip. This
  is a runtime gate rather than an `adr_guard` static check; `docs/dev/deploy-secrets.md`
  and the spec are kept in step by the parity test in
  `scripts/bootstrap/tests/test_preflight.py`.

Documentation site (ADR-038):

- Documentation is authored as Markdown under top-level `docs/` and published as a
  single public mkdocs (Material) site on GitHub Pages by
  `.github/workflows/docs.yml` (`mkdocs build --strict` gates PRs; pushes to the
  default branch publish). Internal design notes, machine registries, and scratch
  dirs stay in-repo but are excluded from the published site via `mkdocs.yml`
  `exclude_docs`. The in-app Django documentation app is retired. This is a
  runtime/build gate, not an `adr_guard` static check.

Migration state (CI gate):

- Django models and their committed migrations must stay in parity. The
  `shifter-platform-lint` job in `.github/workflows/_quality.yml` runs
  `manage.py makemigrations --check --dry-run` (with `TESTING=1`,
  `TEST_DB_BACKEND=sqlite`, `DJANGO_DEBUG=true`, and a synthetic CI-only
  `DJANGO_SECRET_KEY`) as a blocking step. The command runs globally with no
  app-name arguments, so `INSTALLED_APPS` is the coverage seam and new Django
  apps are gated automatically. `--dry-run` writes nothing and needs no
  database, so a model change that is not captured by a committed migration
  (including database-neutral drift such as `help_text` or model manager
  changes) fails the job. This is a CI gate, not an `adr_guard` static check,
  and it mirrors the `api_contract --check` drift gate in the same workflow.
  Added by issue #1061.

## Current Checks

The first slice intentionally stays small:

- `adr-registry`
  Validates the ADR registry and exception files. It also validates the closed
  typed interface contracts required by ADR-032, ADR-039, ADR-051, ADR-054, and
  ADR-055. The `raes-plan-accessor-boundary/v1` contract pins the RAES-free
  standalone consumer, ownership and validation boundaries, reject-before-
  mutation posture, full canonical address fallback, exact-pin compatibility
  evidence, and decision-only scope of #1937. The
  `dedicated-customer-authority/v1` contract makes removal or weakening of
  ADR-054's customer boundary, authority separation, event-migration gate,
  infrastructure ownership, outage behavior, or evidence classes fail locally
  and in CI. The `accessibility-enforcement/v1` contract likewise pins the
  WCAG target, one axe/Playwright toolchain, every-PR/nightly/deployed cadence,
  fail-closed surface inventory, exact finding ratchet, manual-audit evidence,
  central waiver policy, and security boundary. This is structural enforcement
  of accepted decisions, not a substitute for their runtime, migration, IAM,
  network, browser, or manual-audit tests.

  ADR-055's exact section values live in `ACCESSIBILITY_FIXED_SECTIONS`, with
  closed string collections in `ACCESSIBILITY_STRING_SET_SECTIONS`. Extend the
  contract table, registry entry, and mutation test together; do not add a new
  branch of repeated per-section validation.

  The registry check keeps contract support, specialized ADR contracts, and
  dispatch in separate modules. This preserves the closed contract surface
  while keeping each validator independently reviewable and within the static
  analysis limits enforced for guardrail code. Validator helpers carry concise
  docstrings, and the documentation check remains below the enforced file-size
  limit so SonarCloud can keep analyzing guardrail changes on every pull request.

- `layer-imports`
  Enforces the existing cross-layer import policy from `scripts/check_layer_imports/layer_imports.yaml`.
  Every first-party Django app is classified there (ADR-001-R3, #1523) as a
  domain (`engine`, `cms`, `management`, `ctf`, `workspaces`), presentation
  (`mission_control`), support/contracts (`shared`), or support/composition
  (`config`) layer. `workspaces` is the organization/workspace tenancy domain
  added by ADR-046 (#1325); other layers reach it only through
  `workspaces.services` and carry a scalar `workspace_id` rather than a
  cross-layer ForeignKey. Service-package imports may use only the public facade (for
  example `cms.services`); private split-package submodules such as
  `cms.services._range_pause` are not cross-layer seams. This covers both the
  dotted form (`import cms.services._range_pause`) and the
  `from cms.services import _range_pause` form, the latter detected via an AST
  pass since the regex scan only sees the facade module path. The rule is
  mirrored in `scripts/adr_guard/adr_guard.py`, the standalone
  `scripts/check_layer_imports/check_layer_imports.py`, and
  `management check_model_fks`; the hard-coded package lists are held to
  set-equality with the canonical classification by tests, and `.importlinter`
  adds a coarser package-level net. `shared` remains the freely importable
  contracts layer.

- `installed-apps-classified`
  Fails closed when a first-party Django app is added to `INSTALLED_APPS`
  without a classification in `layer_imports.yaml`, when a classification entry
  is stale (no local `AppConfig`), or when an `INSTALLED_APPS` entry is a
  dynamic expression the checker cannot statically resolve (ADR-001-R3, #1523).
  The retired `documentation` package (ADR-038) has no `AppConfig` and is not
  classified.

- `guardrail-docs`
  Requires guardrail changes to update ADR or developer docs in the same change.
  This is a changeset-level check (needs to see multiple files) so it runs in
  pre-commit and `--level fast`, but NOT in the per-edit Claude hook.

- `no-agent-attribution`
  Rejects AI/agent attribution markers in tracked text (agent `Co-authored-by`
  trailers, Cursor marketing footers, Claude Code branding strings, etc.).
  A `commit-msg` pre-commit hook blocks the same markers in commit messages.
  When a commit is rejected for attribution markers, disable Cursor commit/PR
  attribution in `~/.cursor/cli-config.json` only; project `.cursor/cli.json`
  cannot set attribution (permissions-only per Cursor CLI docs).

- `cross-layer-model-imports`
  Fails on direct cross-layer model imports inside service layers. The current tree already satisfies this rule, so it is part of the default guard.

- `python-complexity-gate`
  Enforces ADR-012-R1: every canonical Python package `pyproject.toml`
  must enable Ruff's `C901` rule in `[tool.ruff.lint].select`, set
  `[tool.ruff.lint.mccabe].max-complexity` to the repo-wide threshold
  (`PYTHON_COMPLEXITY_THRESHOLD` in `scripts/adr_guard/_guard/checks/complexity.py`,
  currently `15`, matching SonarCloud's default cognitive-complexity
  threshold), AND must not silently disable the rule by listing it in
  `ignore`, `extend-ignore`, or `per-file-ignores`. The check also
  cross-verifies that `PYTHON_COMPLEXITY_GATE_PYPROJECTS` matches the
  `id: ruff` hook working directories in `.pre-commit-config.yaml`, so
  a new lint surface cannot be added in one place without the other.
  Standalone verifier scripts under `scripts/` that ship their own
  `pyproject.toml` (for example the post-apply deploy checks such as
  `scripts/assert_portal_inspection`, added for issue #932) are gated
  surfaces too: registering one means adding its directory to both
  `.pre-commit-config.yaml` and `PYTHON_COMPLEXITY_GATE_PYPROJECTS` in
  the same change.
  The complexity computation itself is Ruff's job; this check is the
  config-shape backstop against silent gate removal. Existing
  high-complexity functions carry per-function `# noqa: C901`
  exemptions; the function-level backlog (one row per exemption with
  current complexity) lives at `docs/adr/complexity-backlog.md`. The
  threshold ratchets down as that backlog shrinks; a ratchet edit
  updates `PYTHON_COMPLEXITY_THRESHOLD`, every canonical
  `pyproject.toml`, and the backlog rows in a single PR. Runs in both
  `fast` and `ci` levels.
  Test coverage in `scripts/adr_guard/tests/test_adr_guard.py` drives
  the silent-bypass and prefix-selector cases through `subTest()` loops
  so adding a new bypass shape (for example, `extend-select`-side variants) is
  one row in the cases tuple, not a new test method.
  The `uat/event-load-harness` UAT load harness (#926) is a registered
  package under this gate, with matching `Lint`/`SAST`/`Tests
  (event-load-harness)` jobs in `.github/workflows/_quality.yml`.

- `boundary-mock-policy`
  Enforces ADR-019-R1: new Python tests may patch real process, network,
  cloud, and framework transport boundaries, but must not add new
  first-party internal callable patch targets. The check statically parses
  tracked test files for `patch()` / mock `.patch()` string targets and
  statically resolvable `patch.object(imported_module_or_class, ...)`
  calls, then compares `(test file, target)` counts against
  `scripts/adr_guard/boundary_mock_baseline.json`. The baseline records
  current legacy topology-coupled tests so adoption does not require
  rewriting the whole suite in one PR; the allowed counts may shrink but
  must not grow. The check also compares the baseline file against the
  branch reference so raising an allowance is a policy violation unless it
  has a dated ADR exception. Prefer behavioral assertions, in-memory fakes
  at service boundaries, or real framework test clients over patching
  first-party service functions, views, render/logging/transaction aliases,
  or model helpers.

- `documentation-coverage`
  Enforces ADR-022-R1 (GEN-001): every major platform feature listed in
  `docs/adr/documentation-coverage.yaml` must declare at least one user doc and
  at least one technical doc. The check validates the whole manifest on every
  run (it ignores the changed-file list, like `adr-registry`): each referenced
  doc must exist under the in-app docs tree (`docs_root`), must not live under a
  `_deprecated`/hidden path, and must be reachable from an `index.md`. This
  keeps the GEN-001 contract from silently regressing (for example, when a
  feature's doc is removed but its index link is left dangling). Adding a major
  feature means adding a manifest entry pointing at its user and technical docs.

- `published-contract-snapshots-immutable`
  Enforces ADR-011-R8: the published backend-bundle contract's per-version
  snapshots (`shifter/installation/published_contract/backend-bundle-contract.v<N>.json`)
  are append-only. Each snapshot records the frozen shape of a published contract
  version; a contract change ships a *new* version snapshot instead of editing an
  existing one. The check compares every snapshot present at the base-branch merge
  base against the working tree and fails when one was modified or deleted, so the
  breaking-change gate's compatibility oracle cannot be silently rebased. Like
  `boundary-mock-policy` it resolves the base ref from `GITHUB_BASE_REF` /
  `ADR_GUARD_BASE_REF` (falling back to `origin/dev`/`origin/main`). It fails **open**
  locally (a shallow clone with no base history cannot compare, so dev is not blocked)
  and fails **closed** when `ADR_GUARD_SNAPSHOT_ENFORCE` is set: the `adr-conformance`
  CI job checks out with `fetch-depth: 0` and sets that variable, so an inability to
  resolve or read the base becomes an enforcement failure rather than a silent pass. A
  genuinely absent directory at the base (a real first publication) is distinguished
  from an unreadable tree and still passes.

- `accessibility-baseline`
  Enforces ADR-055-R4/R6: the browser-accessibility exact-finding baseline
  (`shifter/shifter_platform/frontend/e2e/a11y/baseline.json`) may only shrink.
  The committed fingerprint set must be a subset of the trusted base-branch
  baseline; new fingerprints (baseline growth) fail unless covered by an
  exact-fingerprint waiver in `docs/adr/exceptions.yaml` naming ADR-055 (an
  optional `fingerprints:` list on the exception, validated by the central
  exception schema, never overloading `paths`/`checks`). Each fingerprint is the
  pipe-joined `surface|project|rule|wcag|target` key emitted by the a11y spec
  (project is `chromium:<viewport>:<theme>`), so a waiver must quote that exact
  string. Resolved findings (removed entries) always pass. Like `published-contract-snapshots-immutable` it
  resolves the base ref from `GITHUB_BASE_REF` / `ADR_GUARD_BASE_REF` (falling
  back to `origin/dev`/`origin/main`), fails **open** locally and **closed** under
  `ADR_GUARD_SNAPSHOT_ENFORCE`, and treats an absent base baseline as a valid
  first enrollment. A committed baseline that is not a JSON array of fingerprint
  strings is rejected outright, and a base baseline that cannot be parsed is
  treated as unverifiable (failing open or closed as above). The per-surface
  exact-set comparison against the live scan and
  the fail-closed surface reconciliation are enforced in the Playwright a11y specs
  (`frontend/e2e/a11y/`), not this check.

- `import-linter`
  Adds package-level forbidden-import contracts across the main Django app layers.

- `makemigrations --check --dry-run`
  Fails when a model or field-choices change ships without its migration. Runs
  as the `missing-migrations-shifter-platform` pre-commit hook as well as in the
  Quality workflow. Adding a `TextChoices` member alters the field, so enum
  additions need a migration too. The hook exists because the CI check sits
  behind the test gate, which is skipped when an earlier job fails -- so a
  missing migration could reach review unnoticed (#680).

- `actionlint`
  Lints GitHub Actions workflows beyond plain YAML validation.
  This includes the GCP deploy workflow's Terraform state-backend hardening
  (`_gcp-dev.yml`) so retention and IAM policy bootstrap logic remains valid.

- Django i18n/static artifact tests
  Enforce ADR-016-R3 in
  `shifter/shifter_platform/tests/config/test_i18n_configuration.py` and
  `shifter/shifter_platform/tests/platform/test_portal_dockerfile.py` by
  requiring portal image builds to run `compilemessages` before
  `collectstatic`, and requiring `entrypoint.sh` to stay free of runtime
  static-artifact rebuilds.

- `deploy-workflow-plan-scope`
  Enforces ADR-003-R2 for the AWS deploy workflows. The `shifter_platform`
  change filter in `.github/workflows/deploy.yml` must stay scoped to
  Terraform-consumed platform files. Quality routing is separate and runs by
  exclusion: `.github/workflows/deploy.yml` must expose a `quality_relevant`
  output that runs Quality unless the diff is ordinary docs-only. That output
  also fails closed on an empty or undetermined changed-file set: an
  `any_changed` classifier is false when the GitHub PR-files API returns zero
  files (its eventual consistency can do this for a freshly created PR), and
  `quality_relevant` ORs in `any_changed != 'true'` so an unclassifiable diff
  runs Quality instead of silently bypassing it (#2024). Guardrail
  docs, including `.github/pull_request_template.md`,
  `.github/copilot-instructions.md`, `docs/adr/**`, and this ADR enforcement
  page, are explicitly quality-relevant so ADR guard validates them. PR Gate
  must reject a skipped Quality job unless `quality_relevant` is false.
  Commit-message or label-based test skips are not accepted. Portal application
  changes must also keep
  reaching the portal image build/deploy path (#913): the check requires a
  `portal_image` filter covering `shifter/shifter_platform/**`, exposed as a
  `changes`-job output, included in the `shifter_platform` job's trigger
  condition, and consumed by the platform `build` job through the
  `portal_image_changes` input so an app-only deploy dispatch builds and
  converges the portal image without running Terraform. The check
  also requires `.github/workflows/deploy.yml` to pass `skip_tests: false`
  literally into `_quality.yml` (no commit-message parsing or dynamic outputs)
  and requires lint, architecture, and security jobs in `_quality.yml` to stay
  independent of `inputs.skip_tests` so the flag can only skip unit-test jobs
  when a caller opts in; the deploy router never opts in (#760). Negative
  fixtures in `scripts/adr_guard/tests/test_adr_guard.py` include a minimal
  `_quality.yml` stub so plan-scope tests isolate one violation at a time. The check
  requires deploy concurrency to queue dispatch deploys (keyed per environment)
  rather than cancel in-flight applies; PR cancellation may remain enabled. It also requires every
  core, range, and platform `terraform plan` / saved-plan `terraform apply`
  command to include `-lock-timeout=5m`, and requires each apply job to create
  and execute a local saved `tfplan` instead of uploading raw binary plans as
  artifacts or running a fresh unplanned apply. The platform Service Discovery
  replacement check must inspect that same saved plan. Non-deploy support/test
  surfaces that are not under `shifter/**` or `mcp/**` must use the
  `quality_only` filter/output rather than being hidden in a deploy bucket:
  `scripts/polaris-aws-range/**` and `scenario-dev/polaris/tests/**` are
  required entries so the orphaned support suites run Quality without launching
  Terraform plans, image builds, or environment deploys. On apply workflows,
  `_shifter-platform.yml` still pushes the Guacamole ECR images before the
  platform Terraform plan because the Guacamole module resolves current image
  digests with `aws_ecr_image` data sources during plan. This ordering is
  required for fresh AWS accounts where the repositories exist but the tags have
  not been published yet.

  The deploy workflow model tests in
  `scripts/adr_guard/tests/test_deploy_workflow.py` also assert the engine
  reusable workflow carries its own hosted provisioner pytest gate and that
  `_shifter-engine.yml` image validation, image build, and deploy jobs all need
  that gate. This keeps a deploy dispatch's Quality skip from bypassing
  provisioner tests on the image that is pushed and deployed. The same suite pins the engine
  `validate` image-shape job's runner placement (#1474): it runs on the trusted
  self-hosted deploy runner class rather than `ubuntu-latest`, so a
  GitHub-hosted runner-acquisition stall can no longer cancel it before steps
  start and skip the whole Platform stage. Because it is self-hosted it is
  fail-closed on `pull_request` under the `deploy-workflow-runner-exposure`
  (ADR-003-R5) invariant, keeps `contents: read` only, and carries a
  `timeout-minutes` backstop (#1220).

  `TestGcpPrivateControlPlaneAccess` keeps both GCP deploy credential setup
  points on fleet Connect Gateway and rejects the direct
  `get-gke-credentials` action. The self-hosted runner has no route to the
  private RFC1918 GKE control-plane endpoint, so replacing either gateway
  refresh with direct credentials would make the workload apply time out
  after otherwise successful Terraform and image-build stages (#1850).

  The manual-deploy invariant (`TestManualDeployDispatch`, #730) asserts that
  environment deploys are a `workflow_dispatch` naming the `environment` input
  (a closed `choice` of `aws-dev` / `aws-proof` / `gcp-dev`), that the `Set
  environment` step keys on that input rather than a branch-name `case` router,
  and that `push` / `pull_request` run validation only (no run/apply flags).

- `portal-deploy-mode-source-of-truth`
  Enforces ADR-003-R4 for the AWS portal deploy path. `_shifter-platform.yml`
  must call `scripts/portal_deploy/portal_deploy.py resolve-topology` instead
  of reading `AWS_PORTAL_ENABLE_AUTOSCALING`; both AWS portal roots must export
  `enable_autoscaling`; the helper must reject single-instance deploys unless
  exactly one running tagged instance matches Terraform state; and the ASG path
  must call `verify-asg-image` after instance refresh so every in-service
  instance is checked for the new portal image tag.

- `deploy-verification-fail-loud`
  Enforces ADR-003-R3: deploy-verification steps must fail the run when the
  thing they verify did not happen, instead of warning and exiting 0. The
  `Wait for Guacamole ECS services to stabilize` step in
  `_shifter-platform.yml` must `exit 1` on stabilization timeout (the FAILED
  circuit-breaker branch already does); raise the poll timeout if first boot
  legitimately needs longer rather than downgrading the timeout to a warning.
  The `Verify` job after portal deploy must fail when portal target-group
  health, the public `/health/` probe, Guacamole ECS rollouts, Guacamole
  target-group health, or the `/guacamole/` smoke probe are not satisfied;
  `scripts/portal_deploy/portal_deploy.py verify-post-deploy` must treat a
  non-`ACTIVE` Guacamole cluster as failure when Guacamole Terraform outputs
  are present. The `Update ECS task definition` step in `_shifter-engine.yml`
  must `exit 1` when the ECS task-definition family cannot be described, so a
  missing or typo'd family fails the deploy instead of silently skipping it
  forever; the only permitted skip is gated on the explicit `first_deploy`
  bootstrap input, surfaced as the `aws_first_deploy` `workflow_dispatch` input
  in `deploy.yml` (strict by default, settable to `true` only on a manual
  dispatch for the first-ever deploy to a fresh AWS environment).

  Enforces ADR-003-R6: after successful AWS dev portal deploy verification,
  `_shifter-platform.yml` may run an advisory `post-deploy-smoke` job that
  executes `scripts/smoke-test.sh` via `portal_deploy.py run-manage-on-portal`.
  The job must stay dev-only (`inputs.is_dev`), use `continue-on-error: true`,
  request `issues: write` only for failure issue creation, declare `SMOKE_*`
  secrets on the reusable workflow, and poll SSM command status until the
  requested manage timeout rather than using the fixed-limit
  `aws ssm wait command-executed` waiter.

- `workflow-action-sha-pinning`
  Enforces ADR-037-R1: every non-local `uses:` action in a cloud-credentialed
  workflow must pin a full 40-hex commit SHA. A workflow is classified
  credentialed when it requests `id-token: write`, runs on a self-hosted runner,
  invokes a cloud-auth action (`aws-actions/configure-aws-credentials`,
  `google-github-actions/auth`), or passes a `workload_identity_provider`. The
  check parses workflows as data via the `_dw_*` model and fails closed: an
  unparseable workflow, an unclassifiable ref, or a mutable ref (tag or branch)
  is a violation. `actions/*` is in scope. Keep the `# <version>` comment next to
  each SHA for Dependabot. Refresh guidance:
  `docs/architecture/rev1-build-deployment-provenance.md`.

- `TFLint`
  Adds Terraform linting on top of `terraform fmt` and `terraform validate`.
  The initial profile is intentionally narrow: it leaves existing repo-wide
  debt rules disabled so the new gate enforces signal instead of legacy noise.

- `gitleaks`
  Scans newly introduced commits for likely secrets, with a small repo config for approved false positives.

- `cloud-factory-seam`
  Enforces ADR-005-R1: every cloud adapter module in `cloud/aws/` must have a
  counterpart in `cloud/gcp/` and vice versa. Catches provider parity drift
  when one side adds a new adapter without the other. Runs in both fast and ci
  levels.

- `kubeconform`
  Validates Kubernetes manifests against official schemas. Catches misspelled
  fields, invalid resource types, and schema violations before they reach a
  cluster. Pinned to the target GKE Kubernetes version.

- `helm lint`
  Validates the Helm-packaged GCP control plane. This is the correct validation
  boundary for raw chart templates, which are not parseable by generic YAML
  tooling before render time.

- `kube-linter`
  Enforces Kubernetes security and best practices: non-root containers,
  read-only root filesystems, resource limits, privilege escalation prevention,
  and more. Configured via `.kube-linter.yaml`.

- `checkov-k8s`
  CIS Kubernetes benchmark and container security checks on manifests in
  `platform/k8s/`. Currently soft-fail while existing manifests are being
  hardened. This posture is separate from Terraform Checkov policy and must not
  be used to justify Terraform soft-fail.

- `checkov-terraform`
  IaC security scan over first-party Terraform in `platform/terraform/`. A
  **blocking gate** under ADR-004-R11. Pre-commit (`.pre-commit-config.yaml`
  `checkov`) and the GitHub Actions `security-iac` job both consume the same
  config at `platform/terraform/.checkov.yaml`; `--soft-fail` is not set on
  either surface. Accepted-risk waivers (Checkov `skip-check` entries in
  `.checkov.yaml` or inline `# checkov:skip=CKV_X:…` comments on individual
  resources) MUST have a matching entry in `docs/adr/exceptions.yaml` with
  `rule_id: ADR-004-R11`, owner, reason (containing the Checkov policy ID),
  `expires_on`, and affected `paths`. `adr_guard.py` rejects expired
  exceptions, forcing owner re-review. Do not create a separate Checkov
  waiver registry; the ADR exceptions registry is the audit trail.

- `k8s-image-registry`
  Verifies that the staged GCP Kubernetes deployment assets still point at
  Artifact Registry (`pkg.dev`), preventing accidental use of public or
  untrusted registries while the GCP workflow and generated assets are being
  reconciled around the Helm cutover.

- `k8s-pss-labels`
  Architecture check ensuring namespace manifests carry Pod Security Standards
  `pod-security.kubernetes.io/enforce` labels. Enforces ADR-006-R1.

- `k8s-deployment-security-context`
  Enforces ADR-006-R2 against two enforcement sources: (1) every YAML
  document under `platform/k8s/gcp/base/` (recursive) whose `kind` is
  `Deployment`, and (2) the rendered output of
  `helm template platform/charts/shifter -f <values>` for each entry
  in `HELM_VALUES_FILES` (`values-gcp-dev.yaml`, `values-gcp-prod.yaml`).
  Per ADR-007 the chart is the authoritative deployment contract;
  base manifests are supporting snapshots. Validating both sources
  catches regressions where a chart template or values file removes
  a required securityContext field even when the base snapshots
  remain compliant. Kind-based filtering, not filename-based, means a
  Deployment shipped under any filename or extension is scanned.
  Multi-document files (`---` separator) and indentless YAML
  sequences are supported.
  Per pod template: `securityContext.seccompProfile.type` must be
  `RuntimeDefault`. Per container AND init container: the *effective*
  context (after pod-level inheritance for `runAsNonRoot`,
  `runAsUser`, `runAsGroup`) must satisfy
  `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]` with
  no `capabilities.add`, `readOnlyRootFilesystem: true`,
  `runAsNonRoot: true`, `securityContext.privileged` not `true`, an
  optional container-level `seccompProfile.type` (when set) equal to
  `RuntimeDefault`, and `runAsUser`/`runAsGroup` set to positive
  integers (booleans are rejected since Python treats `bool` as a
  subclass of `int`). Runs in the `ci` level (`--all --level ci`,
  including CI) and in a dedicated pre-commit hook `adr-guard-k8s`
  (separate from `adr-guard-fast`) that triggers on
  `platform/k8s/gcp/base/*.{yaml,yml}` and
  `platform/charts/shifter/` changes. Not in the `fast` level, so
  unrelated `--level fast` invocations and the system-Python
  `adr-guard-fast` hook do not pull in the YAML or helm dependencies.
  **Runtime dependencies:** PyYAML (`pyyaml>=6.0`) and Helm
  (`v3.15.4`). The `adr-conformance` job in
  `.github/workflows/_quality.yml` bootstraps pip via the stdlib
  `ensurepip` module (the self-hosted Amazon Linux runner's system
  Python ships without pip; `actions/setup-python` cannot fetch
  Python 3.12 for the runner's architecture), then installs PyYAML
  via `python3 -m pip install --no-deps --target
  ${RUNNER_TEMP}/py-deps` with `PYTHONPATH=${RUNNER_TEMP}/py-deps`
  on the run step, and Helm via the official `get.helm.sh` release
  tarball extracted to `${RUNNER_TEMP}/helm-bin/` and added to
  `$GITHUB_PATH`. The `--user` site PyPI install of pip itself is
  job-scoped on the self-hosted runner; PyYAML lands under
  `${RUNNER_TEMP}/py-deps` which is ephemeral. The `adr-guard-tests`
  job uses the same ensurepip + PyYAML pattern; the chart-rendering
  test uses a fake helm shim, so CI tests don't need real helm. The `adr-guard-k8s` pre-commit hook
  uses `language: python` with `additional_dependencies:
  pyyaml>=6.0` so PyYAML is provisioned in an isolated pre-commit
  virtualenv; helm is a developer prerequisite shared with the
  existing `helm-lint-shifter-chart` hook. Complements existing
  kube-linter checks (`run-as-non-root`, `no-read-only-root-fs`,
  `privilege-escalation-container`) which cover the subset
  PSS-restricted enforces directly; this check fills the gaps for
  `seccompProfile`, `capabilities.drop`/`add`, container-level
  seccomp overrides, `privileged: true`, pod-level inheritance, and
  initContainer coverage. Implementation note: the validator is
  decomposed into focused helpers (`_check_container_basic_fields`,
  `_check_container_capabilities`, `_check_container_seccomp`,
  `_check_container_identity`, `_resolve_pod_spec`,
  `_resolve_pod_sc`, `_validate_containers_list`, `_scan_targets`,
  `_validate_base_files`, `_validate_chart_renders`) so each piece
  stays under SonarCloud's cognitive-complexity threshold and tests
  can target each clause independently.

- `k8s-network-policy-coverage`
  Enforces ADR-006-R3 against the base manifest snapshots under
  `platform/k8s/gcp/base/` and the rendered Helm chart output for
  each supported values file. Every Shifter namespace discovered in
  those manifests must have a default-deny `NetworkPolicy` with an
  empty pod selector and both `Ingress` and `Egress` policy types.
  The check also rejects broad egress `ipBlock` CIDRs (`0.0.0.0/0`
  and `::/0`) in Shifter NetworkPolicies, forcing policies to use
  explicit GCLB, Google API, private service, and in-cluster service
  ranges. Runs in the `ci` level and shares the Helm-rendered
  validation boundary with `k8s-deployment-security-context`.

- `eks-cross-stack-sourcing`
  Enforces ADR-044-R6 against the AWS EKS Terraform roots under
  `platform/terraform/environments/*/eks/`. The EKS control plane
  composes over the existing portal and range data plane and must
  source cross-stack values (control-plane database, secrets KMS key,
  agent bucket, range VPC/subnets/AMIs/instance roles) through native
  AWS data sources and SSM Parameter Store. The check fails closed on
  any `terraform_remote_state` data source in those roots, which would
  couple the consumer to another stack's whole state file. Runs in both
  the `fast` and `ci` levels. The AWS/GCP provisioner-env contract
  parity that R6 also requires is proven by the platform test suite
  (`tests/shared/cloud/test_aws_runtime_role_parity.py`), not this
  structural guard.

- `no-plaintext-secrets-in-tfvars`
  Architecture check that scans `*.tfvars` files committed under
  `platform/terraform/environments/` and `platform/terraform/global/`
  and flags any line that assigns a quoted string literal to a variable
  whose name ends in a secret-bearing term: `password`, `passwords`,
  `secret`, `secrets`, `token`, `tokens`, `key`, `keys`, `credential`,
  `credentials`, `authcode`, `authcodes`, `pin_value`, or `pin_values`.
  Bare `authcode` and `pin_value` names are also blocked. Heredoc string literals
  (`name = <<EOF` / `<<-EOF`) are flagged equivalently. Object/array
  assignments to a secret-bearing variable are walked forward to the
  matching brace/bracket and flagged when any string literal appears
  inside (so `db_credentials = { password = "..." }` is caught while
  `db_credentials = { password = var.x }` is allowed). Function-wrapped
  string literals (`db_password = trimspace("...")`,
  `api_token = sensitive("...")`,
  `db_credentials = jsonencode({ password = "..." })`) are caught via
  a same-line RHS scan; multi-line wrapper expressions (jsonencode
  spanning lines, nested function calls across lines) are walked via
  balanced-delimiter matching of `()`/`[]`/`{}` until the expression
  closes, and any inner string literal flags the assignment.
  Var/local/data references and empty strings
  are allowed. Variables whose name ENDS WITH a public-material suffix
  (`public_key`, `public_keys`, `public_cert`, `pub_key`, `pubkey`,
  `authorized_keys`, etc.) are exempted because that material is
  share-only by design; the match is suffix-based so a name like
  `public_key_password` (which has the public-key fragment AND a
  secret suffix) stays flagged. `*.tfvars.example` files are skipped. Both `#` and `//` line comments and `/* ... */`
  block comments are stripped before matching, matching Terraform's
  HCL grammar. Enforces ADR-004-R7. Complements gitleaks, which
  matches high-entropy random strings; this catches low-entropy
  committed credentials gitleaks ignores. Implementation note: the
  check is decomposed into focused helpers (`_collect_tfvars_candidates`,
  `_scan_tfvars_file`, `_flagged_secret_var`, `_block_assignment_has_literal`,
  `_wrapped_rhs_has_literal`, `_lines_have_string_literal`,
  `_find_balanced_close_index`, `_find_block_close_index`, `_balance_scan`,
  `_block_depth_scan`, `_scrub_line`) so each piece stays under SonarCloud's
  cognitive-complexity threshold and tests can target each clause
  independently.

- `mcp-ops-tls-strict`
  Architecture check that fails the build when any file under
  `mcp/ops/` (`.js`, `.mjs`, `.cjs`, excluding `node_modules/`)
  re-introduces `rejectUnauthorized: false` (or `0` / `null`) on a
  TLS configuration. `mcp/ops` connects to RDS Postgres through an
  SSM port forward; `mcp/ops/lib.js::buildPoolConfig` is the single
  call site that builds the pool's TLS config and now preserves
  verification by setting `ssl.servername` to the captured RDS
  endpoint. Comments and string literals are flattened to whitespace
  before matching (mirroring `mcp-no-shell-exec`'s approach) so a
  descriptive doc-string about the prior `rejectUnauthorized: false`
  workaround does not trip the check. Backstops the `buildPoolConfig`
  unit-test invariant on every other JS file in the package. Enforces
  ADR-014-R7.

- `no-tracked-generated-artifacts`
  Architecture check that fails the build when generated or pre-staging
  sensitive artifacts are tracked in source under narrow roots. Three
  artifact families are blocked, each scoped to its own root:
  Terraform plan outputs (`tfplan`, `tfplan.binary`, `plan.out`,
  `*.tfplan`, `*.tfplan.binary`) under
  `platform/terraform/environments/` and
  `platform/terraform/gcp/environments/`; Polaris range build output
  under `scenario-dev/polaris/build/`; and license / authcode bootstrap
  material (`authcodes`, `*.authcodes`) under `temp/bootstrap/`.
  Enumeration uses `git ls-files` (tracked +
  staged + untracked-but-not-ignored) so ignored ephemeral
  workspace artifacts are intentionally allowed; a synthetic-tree
  test-mode fallback walks the filesystem. The blocked path/name
  set is centralized in `scripts/adr_guard/adr_guard.py` so adding
  another generated filename or environment root is one edit. The
  guardrail fails closed: violations name only the repo-relative
  path and a remediation hint, never echoing plan content, license
  material, or binary payloads. Backstops `.gitignore`, which does
  not retroactively un-track files that were already added (for example,
  through `git add -f`), and complements
  `no-plaintext-secrets-in-tfvars`. Enforces ADR-004-R8.

- `no-populated-secret-env-files`
  Architecture check that fails the build when a tracked
  `*-secrets.env` file under `platform/k8s/` carries a real value on
  any assignment. Comments (lines whose first non-whitespace
  character is `#`), blank lines, empty assignments (`KEY=`), and a
  small **fixed** synthetic-placeholder allowlist
  (`REPLACE_AT_DEPLOY`, `CHANGE_ME`, `PLACEHOLDER`, `EXAMPLE`, plus
  the matching bracketed forms `<replace-at-deploy>`, `<change-me>`,
  `<placeholder>`, `<example>`) are allowed; anything else is
  flagged. The bracket allowlist is an explicit fixed set rather
  than a `<...>` pattern so a committer cannot hide a real credential
  inside angle brackets (for example, `DB_PASSWORD=<attacker-known-password>`).
  The parser splits on the first `=` so non-identifier key shapes
  (`db.password=...`, `api-token=...`, `export DB_PASSWORD=...`) are
  still subject to the value check; inline `# ...` is **not**
  honored as a comment (Kustomize / Docker env_file treats `#` as a
  comment only when it is the first non-whitespace character on a
  line); non-comment, non-blank lines without `=` are flagged as
  malformed. Containment uses `git ls-files` so gitignored local-dev
  files (for example, `platform-runtime-secrets.local.env`) are intentionally
  not scanned; a synthetic-tree test-mode fallback walks the
  filesystem for unit tests. The roots and the synthetic-placeholder
  allowlist are centralized in `scripts/adr_guard/adr_guard.py` so
  adding a future overlay (for example, `gcp-prod`) is automatic and adding
  a new cluster tree is one entry. Failure reporting names the
  repo-relative path and the variable name only; the rejected value
  is never echoed. Real runtime secrets must flow in at deploy time
  from GCP Secret Manager, a gitignored local env file, or a
  deploy-time Kubernetes Secret. Backstops gitleaks for low-entropy
  committed credentials it ignores and prevents reintroduction of
  the failure mode resolved by PR #1207 (issue #1195). Enforces
  ADR-004-R9.

- `no-mission-control-flag-literals`
  Architecture check that fails the build when Mission Control
  runtime code carries a hardcoded CTF challenge flag. It scans the
  `shifter/shifter_platform/mission_control/` package (all runtime;
  its tests live under `shifter/shifter_platform/tests/mission_control/`,
  outside scope) and the `shifter/shifter_platform/templates/mission_control/`
  template tree (including inline `<script>` JavaScript) for
  answer-shaped `FLAG{...}` literals (case-insensitive). Detection is
  by pattern, never by a denylist of real values. Format-hint
  placeholders that describe the answer shape rather than carry one
  are intentionally **not** flagged: an empty body (`FLAG{}`), the
  ellipsis form (`FLAG{...}`), and angle-bracket templates
  (`FLAG{<16-hex>}`). The path scope deliberately excludes tests,
  docs, the native `ctf` app (where `FLAG{...}` is a documented
  format hint), and Polaris scenario content under
  `scenario-dev/polaris/`, where flags are legitimate challenge
  content. Failure reporting names the repo-relative path and line
  only; the matched value is never echoed. CTF flags are low-entropy
  and are not caught by gitleaks; this is the complementary
  repo-specific backstop. Challenge answers belong to the CTF/CTFd
  content domain, not the Mission Control application path. Closes
  the #560 regression gap (the `box_info` literal-flag map removed
  during the mission_control views package split) and blocks
  reintroduction. Enforces ADR-004-R16.

- `rds-pending-modifications`
  Post-`terraform apply` gate in `_shifter-platform.yml`. Reads the portal
  Terraform outputs, then calls `aws rds describe-db-instances` for each
  `*_db_instance_id` output and fails the deploy job if any RDS instance
  still has non-empty `PendingModifiedValues` or non-`in-sync`/`applying`
  `DBParameterGroups[].ParameterApplyStatus`. Catches the failure mode
  documented in `dev/terraform.md` ("RDS Change Application") where a
  successful apply silently queues class/parameter changes for the
  maintenance window. Implementation: `scripts/check_rds_pending_modifications/`,
  with its own uv-managed dev environment, dedicated CI lint+test jobs
  (`check-rds-pending-modifications-lint` / `-tests` in `_quality.yml`),
  and matching pre-commit hooks (ruff + pytest). Same pattern as
  `scripts/check_layer_imports/`.

- `check-tf-kms-secrets-grant`
  Pre-commit hook AND CI step (`.github/workflows/_quality.yml`'s
  `terraform-lint` job) that fails when an IAM role whose attached
  `aws_iam_role_policy` grants `secretsmanager:GetSecretValue` (or
  any wildcard covering it, such as `secretsmanager:*`,
  `secretsmanager:Get*`, or `*`) lacks an attached IAM Statement
  granting `kms:Decrypt` on the portal Secrets Manager CMK. The grant
  must satisfy all three predicates in the SAME Statement: Action
  covers `kms:Decrypt` (action wildcard matching is done with
  `fnmatch`, so `kms:*` and `kms:De*` also satisfy); Resource is
  `var.secrets_manager_kms_key_arn` or `var.secrets_kms_key_arn`
  (both module-input names refer to the same physical portal CMK in
  the environment modules: engine-provisioner and portal/ec2 use
  the first, guacamole uses the second) or `"*"` / `["*"]` (accepted
  when the same statement carries the service condition); Condition
  `StringEquals` or `StringLike` with
  `"kms:ViaService" = "secretsmanager.<region>.amazonaws.com"`. The
  per-statement coexistence check matters because IAM evaluates each
  Statement in isolation; spreading the predicates across separate
  statements does not satisfy a single Decrypt call. Independently,
  any IAM Statement granting `kms:Decrypt` on `Resource="*"` (or
  `["*"]`) must carry a `kms:ViaService` condition pinning to some
  service; unconditioned wildcard `kms:Decrypt` is too broad.
  Existence is gated on `secretsmanager:GetSecretValue` (not file
  layout) so unrelated roles that happen to live in the same file
  are not forced to acquire unnecessary KMS grants. Scoped via the
  pre-commit `files:` regex (and the matching CI invocation list) to
  every `.tf` in `platform/terraform/modules/engine-provisioner/`,
  `platform/terraform/modules/portal/ec2/`, and
  `platform/terraform/modules/guacamole/`; expand both when a new
  module starts reading portal Secrets Manager secrets. These are
  module-directory globs rather than three individual filenames
  (#1846): the previous list scanned only `iam.tf` / `main.tf`, so a
  role defined elsewhere in those modules was never checked -
  `guacamole/rds_kms.tf` defines one.

  Because the role/grant pairing is evaluated **within a single
  file** (cross-file aggregation is deliberately out of scope; see
  the checker's module docstring), each role must stay in the same
  file as its `secretsmanager` and `kms:Decrypt` policies. Splitting
  them across siblings leaves the check passing while verifying
  nothing. The
  check is implemented in
  `scripts/check_tf_kms_secrets_grant/check_tf_kms_secrets_grant.py`
  and tested in
  `scripts/check_tf_kms_secrets_grant/test_check_tf_kms_secrets_grant.py`
  with stdlib `unittest` (mirrors `check_tf_iam_ec2_scope`). The
  test suite itself is run by the `check-tf-checker-tests` pre-commit
  hook and a matching CI step so a parser regression cannot land
  merely because the current live `.tf` files remain in the
  happy-path shape. Enforces ADR-004-R10. Backstops the failure mode
  resolved by #52 where a fresh Secrets Manager CMK rotation left
  several roles without `kms:Decrypt` and ECS task secrets injection
  aborted at startup with `AccessDeniedException: Access to KMS is
  not allowed` (which in turn was silently masked at the portal
  entrypoint by an `export VAR=$(fetch_runtime_secret …)` pattern
  that swallowed the fetch failure; see
  `shifter/shifter_platform/entrypoint-lib.sh` and
  `shifter/shifter_platform/tests/test_entrypoint_lib.sh`).

- `check-portal-target-sg-sources`
  Pre-commit hook AND CI step enforcing that portal target-service SG
  ingress (Django:8000, Guacamole client:8080) sources only from a
  security-group reference or `module.vpc.alb_ingress_subnet_cidrs`,
  never the whole public tier where standalone public workloads live.
  Scoped to the `dev`, `proof` and `prod` portal roots. `proof` was
  absent from the original `dev|prod` regex and CI list despite
  deploying the same portal composition, so the #911 NET-2 / #933
  invariant went unenforced there (#1846). Enforces ADR-004-R11.

- `check-tf-iam-ec2-scope`
  Pre-commit hook AND CI step rejecting mutable EC2 instance lifecycle
  actions (`TerminateInstances`, `StopInstances`, `StartInstances`,
  `ModifyInstanceAttribute`, `ModifyInstanceMetadataOptions`) on a
  wildcard resource, and requiring the Shifter ownership resource-tag
  conditions. Previously it ran in pre-commit and as a unit test in CI,
  but never against the live Terraform, unlike its `check-tf-iam-elb-scope`
  and `check-tf-iam-ssm-scope` siblings; a commit that bypassed pre-commit
  could land the regression (#1846). The live CI invocation was added to
  close that gap.

- `global-iam-drift-check`
  ADR guard check (fast + CI, registered in `_registry.py`) pinning the
  out-of-band `platform/terraform/global/iam` drift-check workflow
  (`.github/workflows/iam-drift-check.yml`). global/iam owns the GitHub Actions
  OIDC deploy role and is applied out-of-band, so a merged `github-oidc.tf`
  change can go un-applied and the live role drifts behind committed config -
  the recurring "new resource, then next deploy fails with HTTP 403" churn
  (#247). The check
  binds the workflow's contract on one designated plan job: a push-only trigger
  (no `pull_request`/`pull_request_target`, per ADR-003-R5), a `{dev, main}`
  branch allowlist, a `global/iam` path filter, and a real, global/iam-scoped,
  non-swallowed `terraform plan -detailed-exitcode` so a drift plan fails the
  build. The workflow runs `-refresh=false` (comparing committed config to the
  last-applied state) and is read-only, so it needs no IAM introspection the
  deploy role lacks. Enforces ADR-004-R26.

## Local Usage

Run the fast profile on the full repo:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level fast
```

Run the CI profile:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Useful ecosystem checks:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
helm lint platform/charts/shifter -f platform/charts/shifter/values-gcp-dev.yaml
kube-linter lint --config .kube-linter.yaml platform/k8s/
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml
```

Run on specific files:

```bash
python3 scripts/adr_guard/adr_guard.py --files .github/workflows/_quality.yml --level fast
```

Run on staged or modified files:

```bash
python3 scripts/adr_guard/adr_guard.py --changed --level fast
```

## Docs Prose (Vale)

Markdown prose is linted with [Vale](https://vale.sh/) against the Google
developer documentation style. The config lives in `.vale.ini`; the synced
style package under `.vale/styles/` is gitignored and fetched with `vale sync`.

The `.github/workflows/vale.yml` workflow runs on pull requests that touch
Markdown. It lints only the Markdown files the PR changes, at the config's
error level, so new and edited docs must be clean without forcing a one-shot
cleanup of the pre-existing backlog across the repo's Markdown corpus.

Run it locally the same way CI does:

```bash
vale sync                       # once, to fetch the Google style package
vale path/to/changed-doc.md     # lint a specific file
git diff --name-only origin/dev...HEAD -- '*.md' | xargs -r vale
```

## How To Add A Rule

1. Add or update the ADR entry in `docs/adr/index.yaml`.
2. Implement the `check_<name>(repo_root, files) -> list[Violation]` function in
   the appropriate `scripts/adr_guard/_guard/checks/<family>.py` module (add a
   new family module if none fits), reusing the shared kernels in
   `_guard/_common.py` / `_guard/_workflow_model.py` rather than duplicating
   helpers, and register it in `scripts/adr_guard/_guard/_registry.py` (`CHECKS`
   plus the relevant `CHECK_LEVELS`
   profiles).
3. Decide where it belongs:
   - fast local gate
   - CI gate
   - Claude post-edit hook
   - agent policy docs
4. If the rule cannot be enforced immediately, add a dated exception to `docs/adr/exceptions.yaml`.

## Exceptions

Use exceptions sparingly. They are for temporary, explicit waivers only.

Required fields:

- `rule_id`
- `owner`
- `reason`
- `expires_on`

Optional narrowing fields:

- `checks`
- `paths`

Expired exceptions fail `adr_guard`, so they cannot linger unnoticed.

## Production-Path Quality Ownership

`.github/quality-path-filters.yaml` is the single versioned contract that maps
every production path to the blocking lint, security, and test jobs in
`.github/workflows/_quality.yml`. `scripts/quality_ownership/contract.py` is the
one parser for it. The `_quality.yml` path-detection job runs
`scripts/quality_ownership/classify_paths.py`, which validates the contract and
rejects any unclassified changed path before it emits job selection (the
fail-closed boundary). The `quality-path-ownership` check (ADR-004-R24)
reconciles the contract against the whole repository for estate completeness,
per-path ownership completeness across lint, security, and test, and routing
reachability against the real workflow.

To add a production path:

1. Add a quality unit to `quality_units` with its `paths` and the real
   `_quality.yml` jobs under `responsibilities.lint`,
   `responsibilities.security`, and `responsibilities.test`. Use a
   `{job, matrix}` entry where one job serves several packages, and set
   `packages` to the matching first-party package identifiers so they reconcile
   against `scripts/check_layer_imports/layer_imports.yaml`.
2. If the path is not production source, add a typed `exclusions` entry instead
   (`docs`, `test`, `generated`, `vendor`, `metadata`, or `config`) with a
   reason. Exclusions never route jobs.
3. If a unit genuinely has no blocking job for a responsibility, record a
   time-bounded `docs/adr/exceptions.yaml` entry for rule `ADR-004-R24` whose
   `paths` names the
   `.github/quality-path-filters.yaml#<unit>:<responsibility>` anchor. There is
   no in-contract escape hatch for an owned production path.

## Design Constraints

- Keep the default local gate fast.
- Do not rely on external dependencies for the core ADR guard.
- Prefer explicit exceptions over hidden tolerances.
- Do not make CI architecture checks skippable through the normal test-skip path.
- Keep review friction focused on guardrail files, not on ordinary feature code.

## Guardrail maintenance log

- **agent-attribution matcher (`scripts/adr_guard/agent_attribution.py`)**: the
  attribution-detection regexes were simplified from `\s*.*` to `.*` to remove
  super-linear backtracking (SonarCloud `python:S8786`, ReDoS). Match behavior is
  unchanged (`.*` already spans the leading whitespace the redundant `\s*` matched)
  and is pinned by the existing `tests/test_agent_attribution.py` parity tests. No
  change to what the guardrail forbids.
