# REV1 Trustworthy Testing And Quality Metrics Preflight (#1529)

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1529>

## Decision

Clean-checkout testing must be one contract with two callers: contributors and
CI. Package-local metadata owns dependency resolution, pytest behavior, warning
policy, production-source coverage, and absolute coverage floors; repository
wrappers and GitHub Actions may select a package or service posture, but must
not restate those policies. CI remains the enforcement authority and local
commands must invoke the same package contract.

No application ADR, schema, DTO, service, repository, controller, persistence
model, or exception hierarchy is needed. This is quality-tooling architecture,
not a new application layer. The existing SonarCloud pull-request analysis is
the preferred incumbent for changed-code coverage, but its configured threshold
must be verified and documented in the repository; the current `aces-strict`
"new violations" description is not by itself evidence of a coverage floor.
Package coverage configuration owns the visible, reproducible non-regression
floor. These are complementary metrics and must not be collapsed into a single
repository-wide percentage.

## Current Gaps To Close Without Changing Boundaries

- `README.md` advertises direct `uv run pytest` commands, while CI first syncs
  the dev dependency group and supplies explicit platform posture variables.
  The platform technical setup guide does not currently close that test gap.
- `_quality.yml`, `.pre-commit-config.yaml`, the platform `Makefile`, and
  contributor prose each carry test command details. They already diverge in
  dependency setup, environment, exclusions, and coverage output.
- Platform coverage uses `source = ["."]` and omits only conftest/migration
  paths, while CI invokes `--cov=.`. Tests therefore participate in the local
  numerator/denominator even though Sonar excludes test paths during analysis.
- No reviewed package-local absolute `fail_under` values are present for the
  Python coverage publishers, and the repository does not state a numeric
  changed-code coverage threshold. The Sonar server association must be checked
  rather than inferred from the workflow's `qualitygate.wait` flag.
- Package pytest configuration has no warning classification policy. The
  unawaited/resource failures and narrow third-party deprecation allowances
  therefore cannot behave identically across every caller today.
- JavaScript CI already uses the correct clean-checkout install primitive,
  `npm ci`; local documentation and hooks must converge on it rather than add a
  second Node setup mechanism.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Python dependency environment | Each package's `pyproject.toml` and `uv.lock`; CI's pinned `astral-sh/setup-uv` action and `uv sync --group dev` convention | A clean run syncs the selected package from its committed lock before testing. Do not create a root virtualenv, requirements aggregate, or unconstrained `uv run --with` substitute for a declared dev dependency. |
| Node dependency environment | Each `package.json` and `package-lock.json`; CI's pinned `actions/setup-node` and `npm ci` convention | Clean runs use `npm ci`, never an implicit existing `node_modules` or a lock-mutating install. Preserve the package's declared Node engine. |
| Django test posture | `shifter/shifter_platform/tests/conftest.py`, `config._runtime_env`, `config._database_settings`, and pytest-django's `DJANGO_SETTINGS_MODULE` | Establish test posture before Django imports settings. Reuse `TESTING`, `ENVIRONMENT`, `TEST_DB_BACKEND`, `DJANGO_DEBUG`, and a synthetic `DJANGO_SECRET_KEY`; do not add another settings module or env parser. |
| Service postures | `_quality.yml` SQLite, PostgreSQL, and Redis lanes; `_database_settings.SUPPORTED_TEST_DB_BACKENDS`; pytest `postgres`/`redis` markers and root-conftest marker guards | Keep fast SQLite, PostgreSQL semantics, and Redis integration distinct. A convenience entrypoint must not imply that SQLite proves PostgreSQL or Redis behavior. |
| Test selection and routing | `.github/quality-path-filters.yaml` and explicit jobs in `.github/workflows/_quality.yml` | This remains the CI path-ownership map. Do not introduce a second source-to-job schema or allow a new wrapper to bypass path-routed required jobs. Workflow/config/wrapper changes must route the affected quality jobs themselves. |
| Python test policy | The selected package's `[tool.pytest.ini_options]` | Warning classification and stable default pytest behavior live here so direct local pytest and CI agree. Do not hide policy only in workflow arguments. |
| Python coverage policy | The selected package's `[tool.coverage.run]` and `[tool.coverage.report]` | Measure named owned production roots, omit all tests/fixtures/generated or migration-only material intentionally, and keep each owned package's absolute floor beside that ownership definition. `--cov=.` must not redefine the source universe. |
| JavaScript coverage policy | `shifter/shifter_platform/package.json` Jest configuration and the SPA's existing Vitest configuration | Preserve explicit production `collectCoverageFrom`/include and test/mock exclusions. Floors belong to the owning runner configuration, not shell parsing of console output. |
| Changed-code floor | `sonar-project.properties`, `_quality.yml` coverage artifacts, full-history checkout, and the server-side `aces-strict` SonarCloud PR quality gate | Keep test exclusions and report paths aligned with package reports. Verify and document the numeric changed-code threshold and make PR analysis wait for it. If the server gate cannot enforce that contract, add one repository-visible enforcement mechanism rather than two competing diff calculations. |
| Local hook behavior | `.pre-commit-config.yaml` | Hooks must call the same deterministic package contract or exactly the same package-owned configuration. Remove command drift; do not create a third policy surface. |
| Guardrail validation | `scripts/adr_guard/adr_guard.py`, `docs/adr/index.yaml`, `docs/adr/exceptions.yaml`, and `actionlint` | Workflow, pre-commit, or quality-policy changes remain architecture work. Update enforcement documentation when guardrail behavior changes; no soft-fail or unrecorded exception. |
| Contributor contract | `README.md`, `CONTRIBUTING.md`, and the platform technical development docs | Document copy/pasteable clean-checkout commands, prerequisites, package/posture scope, dependency sync, and environment values. Documentation must not claim that a partial lane is the aggregate gate. |

The owned Python coverage estate currently published to Sonar is
`shifter_platform`, provisioner, packer, installation, bootstrap, and
`check_layer_imports`; platform JavaScript publishes LCOV separately. Other
test jobs remain required behavior evidence even when they do not yet publish a
coverage baseline. Do not manufacture a misleading percentage for packages
whose production-source ownership is not defined.

## Warning Policy Boundary

`RuntimeWarning` for an unawaited coroutine and `ResourceWarning` are
correctness failures. They must fail in package-owned pytest configuration so
the result is independent of test order, xdist worker allocation, and whether
the caller is local or CI. The originating test or fixture must close/await the
resource; converting the warning to an ignore, adding a sleep, forcing garbage
collection, or disabling xdist is not a fix.

Third-party deprecations are migration debt, not correctness warnings and not
first-party permission to emit deprecations. Each temporary allowance must be
an exact pytest warning filter constrained by category and the narrowest stable
module/message identity, with an adjacent removal owner, upstream dependency,
and removal condition or tracking issue. Broad `ignore::DeprecationWarning`,
global warning suppression, warning-count snapshots, and order-dependent
filters are forbidden. A new or changed third-party warning fails until it is
fixed or separately classified.

Tests that intentionally exercise a warning continue to use `pytest.warns` (or
the standard warnings capture API) at the behavior boundary. That is an
assertion, not a baseline exception.

## Coverage Contract

- Production coverage excludes `tests/**`, test helpers, mocks, caches,
  generated assets, and migrations where those files are not owned executable
  production behavior. Exclusions must be specific; do not exclude a whole
  application to improve the number.
- A package report is generated from the package's configured production roots,
  not the current directory. Tests covering tests can never raise the metric.
- Each publishing package has its own visible absolute floor. Floors may differ
  because ownership and current baselines differ, but may only stay level or
  rise in ordinary changes. A reduction requires an explicit, reviewed,
  time-bounded architecture exception with an owner; rounding must not permit a
  real regression to disappear.
- SonarCloud's PR gate should own changed-code coverage and analysis once its
  numeric threshold is verified and documented. Coverage XML and LCOV paths,
  source paths, and test exclusions must describe the same ownership as package
  configuration. Missing expected reports fail artifact publication or scan
  prerequisites; they are not interpreted as zero or silently skipped. If
  Sonar cannot supply the required changed-code floor, the replacement gate
  must consume the same structured coverage reports and remain a single
  repository-visible authority.
- SQLite remains the sole platform coverage publisher unless coverage merging
  is deliberately adopted. PostgreSQL and Redis lanes prove semantics; merging
  their execution data without stable path/context handling would conflate
  semantic evidence with the baseline metric.

## Cross-Cutting Layers The Design Must Pass

### Security and configuration

- **Auth surface:** test helpers may use the existing Django authenticated
  client/OIDC-session fixtures, but the entrypoint must not weaken middleware,
  authorization decorators, host/origin validation, or runtime auth settings.
  `AUTH_PROVIDER` is not a new test-runner selector.
- **Secret-handling surface:** clean tests use a fixed or per-run synthetic
  `DJANGO_SECRET_KEY` and existing fake database credentials for ephemeral CI
  services. They must not source local deployment configuration, load a
  developer dotenv as a prerequisite, read cloud credentials, print the
  environment, or upload environment-bearing artifacts. No real token is
  needed for unit coverage or warning enforcement.
- **Environment shape:** `config._runtime_env` decides whether dev/test defaults
  are legal; `config._database_settings` validates `TEST_DB_BACKEND` and DB
  inputs; pytest-django binds `config.settings`; channel settings validate the
  Redis posture. Wrapper defaults must satisfy these incumbents rather than
  bypass them. PostgreSQL `DB_*` and Redis `CHANNEL_LAYER_BACKEND`/`REDIS_*`
  values remain scoped to those service postures.
- **OS/process exposure:** pass non-secret test posture through a child-process
  environment, not values interpolated into shell command strings. Never place
  credentials or secret material in process argv, command traces, cache keys,
  coverage metadata, JUnit, or job summaries. Resolve paths from the repository
  root and quote them; propagate signals and the underlying test exit code.
- **Shape/policy gates:** lockfile sync (`uv sync`/`npm ci`), pytest marker and
  warning policy, coverage source/floor configuration, quality path routing,
  artifact `if-no-files-found: error`, Sonar's quality gate, actionlint, and ADR
  guard all remain fail-closed. A wrapper's success cannot override any one of
  them.
- **Error envelopes:** this work adds no HTTP/API envelope. CLI diagnostics may
  name a missing tool, package, posture, lockfile, or environment variable, but
  must not include secret values, DSNs, full environment dumps, or swallowed
  subprocess output. Use ordinary nonzero exits; do not add an application
  exception hierarchy for tool failures.
- **Logging/observability:** pytest/JUnit, coverage artifacts, and GitHub job
  summaries are the existing evidence surfaces. Keep package/posture and final
  counts visible, sanitize inputs, and do not add runtime application logging,
  audit rows, telemetry, or a database merely to record test execution.

### Persistence and test isolation

Pytest-django owns test-database creation and teardown. The platform backend is
selected only through `TEST_DB_BACKEND`; no wrapper may create an alternate DB
schema, perform production migrations directly, reuse a developer database, or
invent a repository layer for tests. Stateful Redis/PostgreSQL lanes remain
isolated services, and xdist behavior must preserve the existing per-worker DB
lifecycle and marker safeguards.

## Extensibility Seam

The required seam is an explicit **package selector plus execution posture**.
A repository convenience command may select one package (or the documented
aggregate) and a supported posture such as the platform's fast SQLite,
PostgreSQL, or Redis lane. Package-specific dependency, warning, coverage, and
test-selection details stay behind that selection in package-owned config.
Forwarding arbitrary shell text is not a seam.

This permits the next package or service posture to join without copying global
warning/coverage logic. Adding one still requires deliberate ownership updates
to its package metadata and lockfile, quality path routing/job, Dependabot
inventory, Sonar sources/report paths if it publishes coverage, and contributor
docs. Do not auto-discover every `pyproject.toml`: deploy tools, UAT harnesses,
and application packages have different test and coverage contracts.

## Gotchas And Anti-Patterns

- Do not make a green local command depend on an already-populated `.venv`,
  `node_modules`, generated static files, local database, or uncommitted env
  file.
- Do not keep separate command bodies in README, Makefile, pre-commit, and CI.
  Documentation and callers should name the canonical contract.
- Do not use `--cov=.` with `source = ["."]` while only omitting conftest files;
  that is the self-covering metric called out by REV1.
- Do not introduce a single global floor that lets a high-coverage package hide
  regression in a lower-volume owned package.
- Do not parse pytest's terminal prose or coverage HTML to enforce a metric;
  use runner configuration and structured XML/LCOV/Sonar inputs.
- Do not turn warning failures into `continue-on-error`, retry the suite until
  green, or attribute an unawaited coroutine to whichever test triggers garbage
  collection. Fix the fixture/mock that created it.
- Do not treat every `DeprecationWarning` as third-party. First-party
  deprecations fail unless a test explicitly asserts them.
- Do not change runtime production settings, auth, secret hydration, database
  defaults, or application error handling to make test setup convenient.
- Do not silently stop running documentation, risk-register, PostgreSQL, Redis,
  JavaScript, SPA, MCP, migration-proof, or architecture suites while
  simplifying the common entrypoint. Coverage ownership and test ownership are
  different concepts.

## Non-Goals And Boundaries

- No application feature, data migration, API/schema change, controller/service
  refactor, production observability change, or new persistence component.
- No claim that unit coverage proves production PostgreSQL, Redis, browser,
  cloud, or built-image behavior; their existing dedicated lanes remain.
- No wholesale warning cleanup unrelated to the unawaited/resource failures and
  explicitly inventoried third-party deprecations needed for a trustworthy gate.
- No speculative replacement of pytest, coverage.py, Jest/Vitest, SonarCloud,
  uv, npm, pre-commit, or the path-routed GitHub Actions workflow.
- No baseline decrease disguised as metric correction. Record the corrected
  production-only baseline first, then enforce it; compare future results only
  against the same owned-source definition.
