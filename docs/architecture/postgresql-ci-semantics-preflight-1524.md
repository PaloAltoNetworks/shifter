# PostgreSQL CI Semantics Preflight (#1524)

Status: pre-implementation guidance

Issue #1524 is the authoritative contract. This note fixes the architecture
boundary for the change; it is not an implementation plan.

## Decision Boundary

Keep test posture and test database selection as separate concepts.
`TESTING=1` selects safe test behavior; it must not imply SQLite. The test
backend is an explicit, settings-owned choice with exactly the supported values
`sqlite` and `postgres`. Invalid, absent where required, or contradictory
selection must raise Django's existing `ImproperlyConfigured` error and name
the variable, never silently fall back.

`config/_database_settings.py` remains the only owner of `DATABASES`. A
PostgreSQL test run must use the stock `django.db.backends.postgresql` settings
path and pytest-django's normal database creation, migration, xdist suffixing,
and teardown. Remove the directory-scoped CTF fixture that mutates an already
loaded `ConnectionHandler`, creates databases manually, and calls `migrate`
itself. That fixture duplicates both settings and pytest-django lifecycle logic.

Retain the fast SQLite suite, explicitly selected as SQLite, and add a required
PostgreSQL lane that runs the same broad application-test scope as the required
main platform lane, except tests owned by another real service posture
(currently `redis`), and includes `postgres` evidence. Reusing that broad scope
is preferred over a new hand-maintained path allowlist: transaction and
constraint behavior is cross-cutting, and the repository already contains
PostgreSQL-sensitive tests outside the current CTF concurrency module. Do not
duplicate tests into a second PostgreSQL tree or absorb separately tracked test
scope such as the currently excluded documentation suite.

No new ADR is needed. ADR-002 already requires workflow changes to carry
matching guidance, ADR-003 makes Quality blocking, ADR-019 requires behavioral
tests at real boundaries, and the fail-fast settings precedent is recorded in
`settings-fail-fast-preflight-558.md`.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Test/runtime posture | `config/_runtime_env.py`, `TESTING`, `ENVIRONMENT=test` | Reuse the existing posture vocabulary. Do not create a second settings module or make `DJANGO_DEBUG` a database selector. |
| Database config and validation | `config/_database_settings.py::_build_databases`, `required_runtime_env`, `django.core.exceptions.ImproperlyConfigured` | Parse and validate the backend here once. Reuse the existing PostgreSQL host/name/user/password/options construction; do not build a second DB dict in tests or workflows. |
| Database observability | `config/_posture.py::describe_database_posture` and `log_settings_posture`, protected by `shared.log_sanitize` | Report the selected engine accurately when `TESTING=1`; never log passwords or a DSN. |
| Environment-binding inventory | `config/_env_manifest.py`, generated `config/env-manifest.json`, and `tests/config/test_env_manifest.py` | Let the existing extractor own the new test-only binding and regenerate its artifact. Do not hand-maintain a parallel env schema. |
| Test database lifecycle | pytest-django plus `tests/conftest.py`; xdist policy in `pyproject.toml` | Let pytest-django create `test_<name>` and per-worker databases, apply migrations, flush, and tear down. Do not use the service database directly or access Django connection-handler internals. |
| Backend-specific ownership | registered `postgres` marker in `pyproject.toml` | Mark only claims that are invalid on SQLite. The marker is evidence ownership, not a runtime skip switch or a substitute for the full PostgreSQL lane. |
| Quality routing and gating | `.github/workflows/_quality.yml`, `.github/quality-path-filters.yaml`, and `deploy.yml`'s aggregate `PR Gate` | Keep the lane in the existing `shifter_platform` Quality route on a GitHub-hosted runner with `contents: read`; a failed lane must fail the reusable Quality workflow. |
| Workflow syntax/policy | `actionlint`, ADR guard, and `scripts/adr_guard/tests/test_deploy_workflow.py` | Reuse these gates. Add a narrow workflow-as-data regression only if ordinary settings/pytest tests cannot prove the lane remains required. |
| Production persistence behavior | Django models/services using `transaction.atomic`, model constraints, `select_for_update`, `skip_locked`, and the `Range.allocate_subnet_index` table lock | Exercise the real incumbents; do not add repositories, DTOs, controller shims, lock services, or duplicate constraints for this CI change. |
| Existing PostgreSQL migration proof | `engine/tests/test_subnet_allocation_migrations_postgres.py` and the separate `migration-proof-tests` job | Keep migration-history/container proof distinct from the application-suite backend lane. One does not replace the other. |

## Required Evidence And Marker Contract

The PostgreSQL lane must execute the existing behavioral estate, including the
following correctness surfaces:

- model and migration constraints, including partial/conditional uniqueness
  and `IntegrityError` translation paths;
- `select_for_update()` and `skip_locked` users in CTF submission/scheduler,
  engine lifecycle/outbox, CMS reconciliation, range provisioning/recovery,
  scoring, and Guacamole bootstrap flows;
- `Range.allocate_subnet_index()` and range-creation invariants, so the real
  PostgreSQL `LOCK TABLE ... IN EXCLUSIVE MODE` branch is exercised;
- the existing threaded CTF submission races and any new concurrency proof
  added for a correctness claim that SQLite cannot make.

The existing `postgres` marker must become fail-closed. A PostgreSQL run must
assert that the resolved Django connection vendor is PostgreSQL, collect at
least one PostgreSQL-marked test, and fail if any selected PostgreSQL-marked
test is skipped. Remove per-test `skipif(TEST_DB_BACKEND != postgres)` behavior:
the SQLite command excludes the marker, while selecting a PostgreSQL-marked
test under the wrong backend is a configuration error. Pytest's non-zero
no-tests-collected status is useful but insufficient because a full lane can
still pass thousands of unmarked tests after all marked evidence disappears;
the marker count belongs in the canonical root pytest harness, not a shell grep
of pytest prose.

## Cross-Cutting Layers

- **GitHub auth and runner exposure:** use `ubuntu-latest`, `contents: read`, no
  environment binding, OIDC permission, cloud credential, or self-hosted
  runner. The lane tests source code and an ephemeral service only.
- **Secret handling:** PostgreSQL credentials and Django keys are disposable CI
  values, scoped through step/service environment variables. Never use
  production secrets, print the environment, construct a logged DSN, put a
  password in process argv, or persist credentials in reports/artifacts.
- **Environment/config shape:** `TESTING=1`, `ENVIRONMENT=test`, and the explicit
  backend selector pass through `_runtime_env`, `_database_settings`, the env
  manifest freshness check, root pytest setup, pre-commit commands, package
  scripts, and workflow step env. Any `TESTING=1` command that imports Django
  settings must state or inherit a deliberate backend. PostgreSQL CI also
  supplies the existing `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and
  `DB_PASSWORD` shape; SQLite steps must not carry ignored PostgreSQL values.
- **Database validation/lifecycle:** `_build_databases()` validates the selector
  and `required_runtime_env` owns DB requiredness. pytest-django owns test DB
  naming and lifecycle. The lane must not connect to RDS/Cloud SQL, use the RDS
  IAM backend, or manually issue `CREATE DATABASE`/`migrate` from a nested
  conftest.
- **OS/network exposure:** the PostgreSQL service is bound only to the
  ephemeral hosted runner and uses a health check. Tests connect through normal
  psycopg/Django parameters; no shell interpolation of SQL identifiers or
  credentials is needed.
- **Error envelopes:** failures are settings-import errors, pytest failures, or
  GitHub job annotations/summaries. They do not pass through DRF,
  `shared.api.errors`, views, controllers, or public `/health`; do not expose
  internal hosts, credentials, SQL payloads, or stack traces through an
  application response.
- **Logging/measurement:** use pytest's native summary/JUnit timing and slow-test
  durations plus `$GITHUB_STEP_SUMMARY` for backend, PostgreSQL major, test
  counts, skipped PostgreSQL count, elapsed minutes, and hosted-runner minutes.
  Keep reports non-secret and make the evidence available on failures. Measure
  before setting a timeout; then choose a timeout with explicit headroom rather
  than optimizing by dropping correctness categories.

## Extensibility Seam

`TEST_DB_BACKEND` is the backend seam for local and CI reproduction; adding a
future supported backend must extend the settings validator and test lifecycle
contract rather than add another directory conftest. Keep the PostgreSQL image
major as one lane-level pin aligned with the production compatibility target
(currently PostgreSQL 16 for AWS); do not scatter version literals through
test helpers. A future PostgreSQL upgrade or temporary compatibility matrix
should change that pin/parameter without changing marker semantics or copying
the suite. PostgreSQL 15/16 provider-version parity is not required by #1524.

## Whole-Repo Scope

The implementation boundary includes:

- `.github/workflows/_quality.yml` and `.github/quality-path-filters.yaml`;
- `.pre-commit-config.yaml` and `shifter/shifter_platform/package.json` commands
  that import Django under `TESTING=1`;
- `shifter/shifter_platform/config/_database_settings.py`, `_posture.py`,
  `_env_manifest.py`, and generated `env-manifest.json`;
- `shifter/shifter_platform/pyproject.toml` and root `tests/conftest.py`;
- database/posture/config tests under `tests/config/` and a narrow test-harness
  or workflow regression where needed;
- existing transaction, constraint, allocator, locking, and concurrency tests
  selected by the full PostgreSQL lane;
- removal of `tests/ctf/test_services/conftest.py` after its only responsibility
  moves to the canonical settings/pytest seams.

Review every PostgreSQL service declaration in `_quality.yml`. A step that is
deliberately SQLite must select SQLite and carry no ignored `DB_*` bundle; a
step that declares PostgreSQL must select PostgreSQL or lose the service. In
particular, the main pytest, Redis posture, PostgreSQL semantics, and model-FK
jobs must not retain today's ambiguous mix.

## Gotchas And Anti-Patterns

- Do not replace the current narrow fixture with a repo-wide fixture that still
  mutates `settings.DATABASES`, `connections._connections`, or cached settings.
- Do not run tests against or preserve the service's base `shifter` database.
  `--reuse-db` may apply only to the isolated test databases pytest-django
  creates and names.
- Do not equate “PostgreSQL service is healthy” with “Django used PostgreSQL.”
  Assert the resolved vendor from inside the test process.
- Do not grep terminal output for `passed`, `skipped`, or collection counts.
  Use pytest hooks/reports and structured JUnit data.
- Do not make every `django_db` test PostgreSQL-marked. Generic behavior runs on
  both backends; the marker identifies backend-exclusive evidence.
- Do not allow an invalid selector, missing marked evidence, skipped marked
  test, or zero-test selection to warn and exit zero.
- Do not serialize the entire Quality workflow merely to measure this lane.
  It can run alongside the SQLite job; report its own cost and duration.
- Do not weaken coverage, Redis integration, migration proof, actionlint,
  ADR guard, PR Gate, or existing transaction/constraint assertions to recover
  runtime.
- Do not add a database repository, lock abstraction, test DTO/schema,
  exception hierarchy, logging framework, workflow DSL, or second env manifest.

## Non-Goals

- No application behavior, persistence schema, migration, API, controller,
  service, repository, DTO, auth flow, or public error-envelope change.
- No replacement of PostgreSQL locking or constraints with application locks,
  mocks, SQLite emulation, or cloud-managed database calls.
- No testing of RDS IAM authentication, TLS/CA policy, failover, replication,
  backups, Cloud SQL connectors, or PostgreSQL 15/16 provider parity.
- No removal of SQLite from fast local/pre-commit coverage and no commitment to
  run the full PostgreSQL lane in pre-commit.
- No change to documentation-test routing or duplicate PostgreSQL coverage
  artifact; the lane is production-semantics evidence, while the existing main
  suite remains the coverage publisher.
- No consolidation of the specialized migration-proof or built-image stack
  smoke jobs into this source-tree pytest lane.

## Validation Boundary

Workflow edits require `actionlint` and the full architecture guard:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
actionlint
```

The implementation must also prove settings selector failures, accurate
non-secret posture reporting, env-manifest freshness, SQLite local behavior,
PostgreSQL vendor resolution, positive marked-test collection, fail-on-marked-
skip behavior, the full PostgreSQL lane, and recorded runtime/cost.
