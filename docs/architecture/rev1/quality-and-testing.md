# REV1 Implementation And Test Review

## Implementation quality

The codebase has strong local discipline: Ruff and format gates are clean,
mypy and Bandit cover multiple Python packages, infrastructure scanners run in
CI, and high-risk operations have focused regression tests. CMS and CTF service
splits improved earlier monoliths, and ACES imports are confined behind a shared
facade.

Remaining quality risk is concentrated in orchestration, delivery, and
deployment surfaces:

- Provisioner configuration, range operations, cloud realization, and setup
  orchestration remain large and mixed-responsibility.
- CTF challenge, event, notification, and admin surfaces remain large.
- Terraform environment compositions are duplicated across environments.
- Quality/deploy workflows and `adr_guard.py` are substantial programs in their
  own right.
- CTF email uses an in-process fire-and-forget pool while status advances before
  recipient outcomes are known.

Existing #561, #682, #683, #686, #688, #689, #692, #991, and #998 cover most
decomposition work. Execute them around stable boundaries rather than as
file-only rewrites; #478 and #994 should precede refactors that might otherwise
preserve the wrong dependency direction.

## Test estate

The reviewed inventory contains about 61,700 lines of production platform
Python and 67,300 lines of platform test code, with 4,134 test functions. The
provisioner has about 24,300 production and 19,800 test lines. By contrast, the
new SPA has about 3,945 production TS/TSX lines, 616 test lines, 40 Vitest tests,
and one short Playwright happy path.

Strengths include dedicated package suites, real Redis and limited PostgreSQL
lanes, authorization and concurrency tests, redaction and shell-injection
tests, import contracts, infrastructure policy tests, ACES conformance tests,
built-image smoke, and Sonar aggregation. This is meaningful coverage. Its main
weakness is production fidelity rather than unit-test quantity.

## Q1: Email delivery is non-durable but recorded as successful

**Severity: high**

[`shared/email.py`](../../../shifter/shifter_platform/shared/email.py) submits
mail to an in-process four-thread executor and does not propagate delivery
results. CTF notification services count work immediately and can mark an
announcement `SENT` before background sends finish.

**Impact:** restart or deployment loses queued mail; transient failures have no
retry/idempotency path; operators and API clients receive a success state that
does not represent recipient delivery.

**Action:** use a durable outbox and worker, recipient-level idempotency,
retry/backoff, truthful aggregate status transitions, and delivery observability.
Existing #525, #92, #1460, and #683 do not close this durability gap.

## Q2: Production PostgreSQL semantics are largely untested

**Severity: high**

`config/_database_settings.py` forces SQLite whenever `TESTING=1`. The primary
CI job sets `TESTING=1`, so its configured PostgreSQL service and DB variables
are ignored for 4,739 tests. Only one CTF submission concurrency module is rerun
in the dedicated PostgreSQL lane.

**Action:** make test backend selection explicit; run a representative or full
production-equivalent PostgreSQL lane; move transaction, constraint,
`select_for_update`, and concurrency invariants into it; and fail when a
PostgreSQL-marked test is skipped. Existing #997 and specific race issues do not
address the systemic mismatch.

## Q3: SPA verification gives false confidence

**Severity: high**

Vitest passes 40 tests at 59.54% statement coverage without a threshold.
Risk-detail, comments, history, router, bootstrap, and context surfaces are at
zero coverage, and Sonar excludes SPA coverage. A committed Playwright create
happy path is never invoked by a workflow. Passing jsdom axe tests also log that
canvas-backed color-contrast evaluation cannot run.

**Action:** add a new-code ratchet and risk-based floor; publish SPA LCOV; cover
authorization, mutation failure, recovery, routing, and bootstrap states; run an
authenticated Playwright lane with isolated data and retained traces; run
representative axe checks in a browser and fail on unexpected axe execution
errors. Existing #713 should own or precede the accessibility policy.

## Q4: Documentation security tests are excluded

**Severity: medium-high**

The platform job passes `--ignore=tests/documentation`, and no other job runs
the suite. Those 25 tests cover authentication, path traversal, and HTML
sanitization. They pass in 7.83 seconds when invoked separately.

**Action:** remove the ignore or add a required dedicated job, and test the path
routing that selects it.

## Q5: Terraform roots are not validated on pull requests

**Severity: medium-high**

PR quality runs TFLint and custom policy scanners, but not backendless
`terraform init` and `terraform validate`. Reusable deploy workflows perform
validation or planning only outside pull-request events.

**Action:** maintain an inventory of Terraform roots, run backendless init and
validate for affected roots, add module contract tests or fixture plans where
feasible, and reject new uncovered roots.

## Q6: Coverage and warnings obscure the real metric

**Severity: medium**

The full default suite passed 4,739 tests in 214.9 seconds. Its report says 94%,
but `source = ["."]` includes tests that cover themselves. Coverage XML without
tests gives 88.05% production line coverage, which is still healthy. CI defines
no visible owned-package or changed-code floor. The run emitted 727 warnings,
including unawaited SSH consumer coroutines caused by test task mocks.

**Action:** omit tests from production coverage, publish owned-package
baselines, enforce non-regression/new-code floors, fail on unawaited-coroutine
and resource warnings, and baseline third-party deprecations separately.

## Q7: Clean-checkout test commands do not match CI

**Severity: medium**

The README documents `uv run pytest`, but a plain platform run inherits
production-style HTTPS behavior because `DJANGO_DEBUG=true` is supplied by CI
rather than established by the test configuration. JavaScript tests also need
an explicit dependency install in a clean worktree.

**Action:** provide a repository entrypoint or deterministic per-package
wrappers that install/sync dependencies and establish the same environment CI
uses. Contributor documentation must be executable from a clean checkout.

## Q8: Routed CI and architecture classification can miss new paths

**Severity: medium**

Path-routed CI is efficient, but a new or renamed production path can skip its
owner's suite. Likewise, architecture checks omit unclassified first-party
apps. Generate or test a source-to-quality-job matrix and fail when production
paths lack lint, security, and test ownership. Align it with the proposed
whole-platform package classification guard.

## Q9: Dead parallel implementation remains active-looking

**Severity: medium**

`mission_control/views/_ranges.py` is a 331-line, zero-coverage duplicate with
no production import while current dispatch uses DRF implementations. It still
receives ACES edits. Extend #992 to delete it and prevent parallel implementation
drift; do not create a duplicate REV1 issue.

## Live and performance evidence

Mocks and fake cloud clients are appropriate for unit tests but cannot prove
cloud IAM, Kubernetes RBAC/admission, remote access, or a live range. Existing
#987 tracks terminal/Guacamole data-path smoke and #1264 tracks live ACES
validation. Define a small scheduled/pre-release environment matrix with an
owner, cost cap, retained evidence, and failure policy rather than provisioning
a range on every PR.

Existing #846 and its children capture measured event bottlenecks. Those should
precede speculative micro-optimization. Performance budgets become meaningful
when the event harness represents real portal and range-access traffic.

## Verification results

- Django CI-equivalent suite: 4,739 passed; 88.05% production-only line
  coverage; 727 warnings.
- Provisioner suite: 1,063 passed, eight skipped.
- Excluded documentation suite: 25 passed when invoked separately.
- Architecture guard, import contracts, Ruff, and format checks passed.
- Relevant baseline GitHub platform, JavaScript, migration, and Sonar checks
  passed.
