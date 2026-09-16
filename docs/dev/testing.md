# Testing: Clean-Checkout Commands and Quality Metrics

This document is the contract for running the test suites and for the coverage
and warning policy that makes the reported numbers trustworthy (REV1 Q6/Q7,
issue #1529). CI (`.github/workflows/_quality.yml`) is the enforcement authority;
the commands here reproduce its posture from a clean checkout.

## Running tests from a clean checkout

The repository `Makefile` is the entrypoint. Each test target syncs the package's
pinned dependencies (`uv sync --group dev` / `npm ci`) and establishes the same
environment CI uses, so a fresh clone runs tests without hand-setting variables.
`make help` lists every target, including the non-test `devmain` promotion
command (see `docs/DEVELOPMENT_WORKFLOW.md`).

| Command | Lane |
| --- | --- |
| `make test-platform` | Platform fast lane (SQLite); the sole coverage publisher |
| `make test-platform-postgres` | PostgreSQL semantics lane (needs Postgres on `:5432`) |
| `make test-platform-redis` | Redis channel-layer lane (needs Redis on `:6379`) |
| `make test-provisioner` | Engine provisioner suite |
| `make test-installation` / `test-bootstrap` / `test-check-layer-imports` | Package suites |
| `make test-js` | Platform JavaScript (Jest) with coverage |
| `make test-platform-e2e` | Authenticated SPA E2E (Playwright); needs a Chromium build |
| `make test-platform-a11y` | Browser accessibility scans (Playwright + axe); needs a Chromium build |
| `make test-adr-guard` | Repository-guard suite; mirrors the `adr-guard-tests` CI job |
| `make test` | Every no-service lane at once |

Running a package directly (`cd <pkg> && uv run pytest`) also works from a clean
checkout: the platform test posture (`DEBUG`, SQLite backend, local provisioner
off) is established in the settings themselves via `config._runtime_env.IS_TEST_RUN`,
not injected by CI. Prerequisites: `uv`, and Node 20.19+ for the JavaScript lane.

## Test posture (why a clean run matches CI)

`config._runtime_env.IS_TEST_RUN` is true when `TESTING=1` or pytest is the entry
point. Under it the settings default to the test posture so a bare `uv run pytest`
does not inherit the production HTTPS posture a fresh checkout would otherwise get:

- `DEBUG` defaults to `True` (`config/settings.py`). An explicit `DJANGO_DEBUG`
  still wins; production (`IS_TEST_RUN` false) is unchanged and defaults to `False`.
- `LOCAL_PROVISIONER` is forced off (`config/_cloud.py`) so range-lifecycle tests
  never shell out to a real provisioner subprocess (which leaks). A test that
  exercises that path sets `settings.LOCAL_PROVISIONER` via the pytest-django
  `settings` fixture.
- `TEST_DB_BACKEND` defaults to `sqlite` (`config/_database_settings.py`).

These are covered by `tests/platform/test_clean_checkout_posture.py`.

## Coverage: two complementary floors

Production coverage measures owned code only. Each publishing package sets
`[tool.coverage.run] source` and omits the whole test tree, conftest hooks, and
migrations in its `pyproject.toml`, so tests can no longer cover themselves (the
platform metric was 94% self-covering, ~88% production-only). CI runs `pytest
--cov` (no path) so package config, not the command line, owns the measured set.

**Absolute per-package floor**, enforced by `[tool.coverage.report] fail_under`
in each package. Floors are per-package (a repository aggregate would let a
high-coverage package mask a regression in a smaller one). Each floor sits one
point under the measured production-only baseline to absorb run-to-run variance;
floors only stay level or rise, and a real reduction requires a reviewed,
time-bounded exception.

| Package | Production-only baseline | `fail_under` |
| --- | --- | --- |
| `shifter/shifter_platform` | 88% | 87 |
| `shifter/engine/provisioner` | 80% | 79 |
| `shifter/installation` | 97% | 96 |
| `scripts/bootstrap` | 86% | 85 |
| `scripts/check_layer_imports` | 96% | 95 |
| `shifter/packer` | 76% | 75 |

**SPA (frontend) floor.** The Django-hosted React SPA
(`shifter/shifter_platform/frontend`) enforces its own absolute floors in
`vite.config.ts` (`test.coverage.thresholds` for statements, branches,
functions, and lines), each set one point under the measured baseline like the
Python packages so the floor absorbs run-to-run variance and only rises. The
measured source set is `src/**/*.{ts,tsx}` excluding tests, test support, and
the generated `src/api/schema.d.ts`; the first-party entrypoint and composition
root stay measured. The SPA's Vitest LCOV (`frontend/coverage/lcov.info`) is
uploaded by the `SPA (shifter_platform frontend)` CI job and restored into the
`sonarcloud` job, so SPA changed lines are held to the same changed-code gate
below (#1526).

**Changed-code floor**, owned by the SonarCloud `raes-strict` quality gate,
which fails a PR when `new_coverage < 80` (80% coverage on changed lines), plus
`new_violations > 0`, new duplicated-lines density > 3%, any new rating worse than
A, and new security hotspots not fully reviewed. PR analysis waits for the gate
(`sonar.qualitygate.wait=true`). The conditions are recorded in
`sonar-project.properties`; each owned Python package publishes its configured
coverage report for Sonar to consume.

## Warning policy

Warning classification lives in `shifter/shifter_platform/pyproject.toml`
`[tool.pytest.ini_options] filterwarnings`, so a direct `pytest` and CI agree
regardless of test order or xdist worker.

- **`ResourceWarning` and unawaited-coroutine `RuntimeWarning` are errors.** They
  are correctness defects; fix the originating fixture/mock (close/await the
  resource) rather than downgrade the filter. Converting to `ignore`, adding a
  sleep, forcing GC, or disabling xdist is not a fix.
- **`DeprecationWarning` is an error by default.** First-party deprecations, and
  any new or changed third-party deprecation, fail until fixed or explicitly
  baselined. Do not add a blanket `ignore::DeprecationWarning`.
- **Third-party deprecation allowances are narrow and owned.** Each is an
  `ignore` filter matched by exact message, with an adjacent owner and removal
  condition. The current set is the `django-health-check` (`<5.0`) class-based
  check deprecations, tracked for migration + removal in
  [#1601](https://github.com/Brad-Edwards/shifter/issues/1601).
- Tests that intentionally assert a warning use `pytest.warns` at the behavior
  boundary; that is an assertion, not a baseline exception.

## Authenticated SPA end-to-end (Playwright)

`make test-platform-e2e` runs the authenticated browser journeys against the
**real Django-hosted built SPA** (#1526). It is hermetic: it builds the SPA,
migrates and seeds a job-local database, and drives Playwright through normal
Django sessions and CSRF. The CI job `shifter-platform-e2e` in
`.github/workflows/_quality.yml` runs the same flow against a job-local
PostgreSQL service and feeds the `PR Gate`; the make target uses SQLite locally.

Synthetic actors are established by the dev/test-only `seed_e2e` management
command (staff, threat-research, and standard actors, plus the staff actor's
administrable organization) and by `dev_login` (CTF organizer/participant). The
Playwright config's `auth.setup.ts` logs each actor in once and reuses its
`storageState`. No cloud, provisioner, IdP, or live-range dependency is used:
`LOCAL_PROVISIONER`/`ENGINE_TASK_*` stay unset, so a range launch enqueues
nothing and contacts no cloud.

Hermetic scope: login/auth-revocation, workspace lifecycle
(create/rename/archive/restore), shared-audit history, authorization denial
(client advisory **and** the authoritative API 403), and CTF
organizer/participant/threat-research role landings. Journeys that require a live
provisioner (range readiness/terminal/cleanup, CTF range, Guacamole) are the
deployed tier and are tracked separately, not run in the PR lane.

Authenticated Playwright traces are retained only on a local retry and are never
uploaded as CI artifacts (ADR-055-R7). Reproduce failures locally with
`make test-platform-e2e`.

## Browser accessibility (Playwright + axe)

`make test-platform-a11y` runs `@axe-core/playwright` over the ADR-055 surface
matrix (`frontend/e2e/a11y/`) against the same hermetic stack, with the WCAG 2.2
A/AA tag set. The `Accessibility` job in `.github/workflows/deploy.yml` runs it on
**every** pull request as a direct `PR Gate` dependency (it does not inherit the
frontend path skip, per ADR-055-R2), against a job-local PostgreSQL.

The debt baseline is an exact set of privacy-safe fingerprints
(`frontend/e2e/a11y/baseline.json`): the scan fails on any new or resolved
finding, and the `accessibility-baseline` adr_guard check enforces that the
committed baseline may only shrink versus the trusted base branch (additions
require an exact-fingerprint waiver in `docs/adr/exceptions.yaml` naming ADR-055,
per R4/R6). The matrix reconciles fail-closed against the SPA route table
(`src/test/a11y-surface-reconcile.test.ts`); a new route group with no coverage
or exclusion fails. Nightly multi-browser runs, deployed-target scans, the
WCAG-EM manual audit, and the release-evidence gate are the remaining ADR-055
tail tracked in [#2117](https://github.com/Brad-Edwards/shifter/issues/2117).
