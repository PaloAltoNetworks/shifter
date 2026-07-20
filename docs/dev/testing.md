# Testing: Clean-Checkout Commands and Quality Metrics

This document is the contract for running the test suites and for the coverage
and warning policy that makes the reported numbers trustworthy (REV1 Q6/Q7,
issue #1529). CI (`.github/workflows/_quality.yml`) is the enforcement authority;
the commands here reproduce its posture from a clean checkout.

## Running tests from a clean checkout

The repository `Makefile` is the entrypoint. Each target syncs the package's
pinned dependencies (`uv sync --group dev` / `npm ci`) and establishes the same
environment CI uses, so a fresh clone runs tests without hand-setting variables.
`make help` lists every target.

| Command | Lane |
| --- | --- |
| `make test-platform` | Platform fast lane (SQLite); the sole coverage publisher |
| `make test-platform-postgres` | PostgreSQL semantics lane (needs Postgres on `:5432`) |
| `make test-platform-redis` | Redis channel-layer lane (needs Redis on `:6379`) |
| `make test-provisioner` | Engine provisioner suite |
| `make test-installation` / `test-bootstrap` / `test-check-layer-imports` | Package suites |
| `make test-js` | Platform JavaScript (Jest) with coverage |
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
| `shifter/packer` | n/a (Packer HCL; no owned production Python) | not a coverage publisher |

**Changed-code floor**, owned by the SonarCloud `aces-strict` quality gate,
which fails a PR when `new_coverage < 80` (80% coverage on changed lines), plus
`new_violations > 0`, new duplicated-lines density > 3%, any new rating worse than
A, and new security hotspots not fully reviewed. PR analysis waits for the gate
(`sonar.qualitygate.wait=true`). The conditions are recorded in
`sonar-project.properties`; the platform SQLite lane is the sole coverage report
Sonar consumes.

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
