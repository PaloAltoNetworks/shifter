# Built Image Stack Smoke Preflight (#922)

Status: pre-implementation guidance

Date: 2026-06-14

Issue: GitHub #922, "test: built-image stack smoke in CI (boot the real
container, assert health/WS/workers)".

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as a CI artifact-runtime verification problem, not a new portal
runtime, health framework, worker framework, or deploy workflow. The defect is
that CI can pass while the production portal image cannot boot under its real
entrypoint with the dependencies it needs at runtime.

Keep these concepts separate:

1. Source-tree tests: pytest/import checks that run against local source and
   test settings.
2. Image build verification: the production Dockerfile must complete dependency
   install, `compilemessages`, and `collectstatic` as the non-root app user.
3. Container boot verification: the built image must run `entrypoint.sh`, import
   `config.asgi:application`, wait for Postgres, run migrations once, and exec
   the production Gunicorn/Uvicorn ASGI command.
4. Runtime readiness: `/health` / `/health/` must exercise the existing
   dependency-aware `django-health-check` registry, not a synthetic OK path.
5. Worker liveness: SQS workers and the CTF scheduler own heartbeat files under
   `/tmp`; worker health must not be folded into portal HTTP health.

The smoke should run on hosted runners without cloud credentials. Any local AWS
or GCP behavior in the smoke must be represented by local test doubles or
non-secret env values, not by real provider auth.

## Architecture Decisions

- Build the same production portal image shape as deploy builds: context
  `./shifter`, file `shifter/shifter_platform/Dockerfile`. Do not add a test
  Dockerfile, test entrypoint, or source-tree ASGI import as the artifact proof.
- Run the web container through `./entrypoint.sh` with no command override. The
  point is to catch regressions in secret hydration guards, database waiting,
  migration gating, writable runtime directories, `HOME`, and the final
  Gunicorn/Uvicorn command.
- Use local Postgres and Redis service containers. The smoke should configure
  direct env vars for DB/app/OIDC/Redis only as far as needed to boot locally;
  it must not require AWS Secrets Manager, GCP Secret Manager, SSM, ECR, SQS, or
  cloud credentials.
- Reuse `/health` and `/health/` as defined by issue #477 / #919. Do not create
  a new smoke-only health endpoint or assert on a hard-coded response body.
- Prove a websocket handshake through `config.asgi:application`,
  `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and a real routed
  consumer. Since routed consumers require authentication for meaningful accept,
  the smoke must use a real Django session or a narrowly scoped authenticated
  setup against the running container rather than adding an unauthenticated
  test websocket route.
- Preserve the migration ownership split from #918/#953: runtime web and
  worker containers should not each run migrations. A stack smoke may run one
  explicit migration path and then boot long-running containers with
  `SKIP_MIGRATIONS=1`, or otherwise prove that the intended smoke topology runs
  `manage.py migrate --noinput` exactly once.
- Keep compile/static artifact checks at image build unless the product
  contract deliberately moves them. The current production image already runs
  `compilemessages` and `collectstatic` during `docker build` as `appuser`.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #922 |
| --- | --- | --- |
| Quality workflow | `.github/workflows/_quality.yml` | Add the smoke as a hosted-runner quality job; keep it behind the existing `skip_tests` contract and normal Quality result handling. |
| Path routing | `.github/workflows/deploy.yml` `shifter_platform` and `portal_image` filters | Use the existing path signals as the source of truth. Do not duplicate changed-file parsing inside `_quality.yml`. |
| Portal image build | `shifter/shifter_platform/Dockerfile` | Reuse the production image build inputs and non-root runtime contract; no parallel Dockerfile. |
| Runtime bootstrap | `shifter/shifter_platform/entrypoint.sh` and `entrypoint-lib.sh` | Exercise the real entrypoint. Do not bypass DB wait, secret/env validation, or the Gunicorn/Uvicorn `exec`. |
| ASGI routing | `shifter/shifter_platform/config/asgi.py` | Preserve `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and the existing route lists. |
| Health readiness | `config.health.CoarseHealthCheckView`, `config.health_checks`, `config.urls`, `config.middleware.HealthCheckMiddleware` | Probe the same dependency-aware public health contract consumed by ALB, Docker, GCP, and installation checks. |
| Channel layer | `config/_channels.py` and `config/settings.py` | Use the explicit Redis backend posture when the smoke starts Redis; do not add a test-only Channels settings module. |
| Worker heartbeat | `shared/management/commands/run_worker.py`, `ctf/management/commands/run_ctf_scheduler.py` | Keep `/tmp/worker-{queue}-heartbeat` and `/tmp/ctf-scheduler-heartbeat`; do not invent a second worker-health schema. |
| AWS runtime/deploy migration contract | `scripts/portal-deploy/deploy_portal.sh`, `_shifter-platform.yml`, `tests/platform/test_ctf_scheduler_startup.py` | Reuse the "migrate once, boot runtime with `SKIP_MIGRATIONS=1`" invariant if the smoke models multi-container runtime. |
| Existing tests | `tests/platform/test_portal_dockerfile.py`, `tests/test_asgi_worker_smoke.py`, `tests/mission_control/test_health.py`, `tests/platform/test_worker_health_supervision.py` | Extend structural invariants where needed instead of adding duplicate assertions in unrelated suites. |
| Logging hygiene | `config._logging_config`, `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value()` | Diagnostics may name container/job/check status, not secrets, DSNs, Redis AUTH URLs, or env dumps. |
| Workflow enforcement | `actionlint`, `scripts/adr_guard/adr_guard.py`, ADR-003 workflow guardrails | Workflow edits are guardrail-file edits and must pass the repo workflow/ADR gates. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- GitHub token and runner surface: the job runs on hosted runners with
  `contents: read` only unless an existing upload action needs more. It must not
  request `id-token: write`, cloud roles, PATs, or repository write scopes.
- Secret-handling surface: local smoke secrets are ephemeral non-production
  values such as `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, test DB password,
  and OIDC placeholder IDs. Do not use repository secrets, cloud secret
  managers, SSM, ECR login, or real queue URLs. Do not print full env dumps.
- Env-binding shape: bind settings through existing env names consumed by
  `config/settings.py`, `config/_channels.py`, and `entrypoint.sh`
  (`DB_*`, `DJANGO_*`, `FIELD_ENCRYPTION_KEY`, `OIDC_*`,
  `CHANNEL_LAYER_BACKEND`, `REDIS_*`, `SKIP_MIGRATIONS`). Avoid smoke-only
  settings modules or magic env names that bypass validators.
- Config validators: production settings must still fail closed for missing
  `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, required OIDC values, and invalid
  Redis TLS/AUTH posture. The smoke may choose plaintext local Redis, but it
  must not relax the `REDIS_TLS=true` password/CA checks.
- Auth surface: `/health` stays unauthenticated and coarse; websocket routes
  stay authenticated. If the smoke creates a session, it should create only a
  local throwaway user in the smoke database and should not enable
  `/dev-login/` by setting `ENVIRONMENT=development` on a production-shaped
  container.
- OS/process exposure: command argv and logs may contain image tags, container
  names, ports, and non-secret test values. They must not contain secret manager
  payloads, signed URLs, Redis passwords, Django session cookies, or full
  database URLs. The check must catch the `/home/appuser` / `HOME` writable-dir
  regression by running as the image's non-root user.
- Error-envelope surface: public `/health` responses must remain coarse JSON
  labels. Workflow diagnostics should use GitHub Actions annotations and
  bounded container logs; do not add a new exception hierarchy or public
  diagnostics endpoint for smoke-only failures.
- Persistence surface: use disposable CI Postgres state and volumes. No schema,
  migration, model, repository, or DTO change is needed to add this smoke.

Maintainability incumbents the implementation must build on:

- `_quality.yml` as the quality job host, with setup patterns matching existing
  Docker/uv jobs.
- `deploy.yml` as the canonical path classifier for `shifter_platform` /
  `portal_image`; any reusable-workflow input needed by `_quality.yml` should be
  passed from there, not recomputed ad hoc.
- `Dockerfile`, `entrypoint.sh`, `entrypoint-lib.sh`, `config/asgi.py`,
  `config/health.py`, `config/health_checks.py`, and `_channels.py` as the
  production runtime contracts.
- `run_worker.py` / `run_ctf_scheduler.py` heartbeat files as the liveness
  contract for background processes.
- Existing platform structural tests for Dockerfile, migration ownership,
  worker health, and ASGI worker import.

Extensibility seam:

The seam is a reusable local stack-smoke harness with parameterized image tag,
container/service names, host ports, health paths, websocket path, and monitored
heartbeat files. The first version should default to the portal web container,
Postgres, Redis, and the current worker/scheduler set. The next reasonable
variation, such as adding a scheduler-only assertion, switching the websocket
route, or running the same smoke after a dependency-lock change, should be a
parameter change rather than a copy of the whole workflow block.

## Whole-Repo Scope

In scope for the implementation:

- `.github/workflows/deploy.yml` if `_quality.yml` needs typed path-signal
  inputs for portal/platform gating.
- `.github/workflows/_quality.yml` for the hosted stack-smoke job.
- `shifter/shifter_platform/Dockerfile`, `entrypoint.sh`, and
  `entrypoint-lib.sh` only if the smoke exposes a real runtime bug.
- `shifter/shifter_platform/config/asgi.py`, `config/_channels.py`,
  `config/health.py`, `config/health_checks.py`, `config/middleware.py`, and
  `config/urls.py` only if the smoke exposes an existing contract mismatch.
- `shifter/shifter_platform/shared/management/commands/run_worker.py` and
  `ctf/management/commands/run_ctf_scheduler.py` only if heartbeat behavior is
  already wrong.
- `scripts/portal-deploy/deploy_portal.sh` and `_shifter-platform.yml`
  migration invariants as the incumbent runtime model to compare against.
- `scripts/adr_guard/adr_guard.py`, ADR docs, and operator docs only if the
  workflow routing or architecture guardrail contract changes.

Usually out of scope:

- Terraform module redesign, ECR publishing, AWS/GCP IAM, SSM/Secrets Manager,
  Kubernetes/Helm probe changes, production deploy convergence, ALB/GCP backend
  routing, auth-provider redesign, Guacamole token brokering, SQS queue
  semantics, and app schema/model changes.

## Gotchas And Anti-Patterns

- Do not make the smoke import `config.asgi:application` from the source tree
  and call that "built-image" coverage.
- Do not override the web command with `python manage.py runserver`, Daphne, or
  a direct Gunicorn command that skips `entrypoint.sh`.
- Do not set `TESTING=1` or `DJANGO_DEBUG=true` for the production-image smoke;
  that bypasses the validators that have historically failed only in the built
  artifact.
- Do not turn on `ENVIRONMENT=development` to get `/dev-login/` for a shortcut.
  That tests a dev-only bypass, not production auth/session behavior.
- Do not use a public cloud endpoint, cloud credential, real SSM parameter,
  real Secrets Manager secret, or ECR push/pull for this hosted-runner smoke.
- Do not conflate liveness and readiness. `/health` is dependency readiness;
  worker heartbeat files are worker liveness; websocket accept proves ASGI and
  Channels path viability.
- Do not add a second health endpoint, second channel-layer config, second
  worker heartbeat naming convention, custom exception hierarchy, or duplicate
  validation layer.
- Do not assert only "container is running". The home-directory regression and
  ASGI import failures are exactly the class of runtime failures this job must
  catch through real endpoint/heartbeat assertions.
- Do not print full container logs blindly on success. On failure, bound the log
  tail and avoid commands that dump environment variables or session cookies.
- Do not weaken `actionlint`, ADR guard, Dockerfile hash/lock discipline, health
  response secrecy, or entrypoint fail-closed behavior to make CI convenient.

## Non-Goals

- No implementation in this preflight note.
- No new deploy framework, provider abstraction, health framework, auth system,
  logging framework, schema/DTO layer, persistence model, or workflow parser.
- No change to production cloud deploy routing, ECR repositories, Terraform
  state, IAM roles, Secrets Manager/SSM contracts, GCP runtime rendering, or
  Kubernetes probes unless the smoke uncovers a pre-existing defect.
- No redesign of portal `/health`, websocket consumers, worker/scheduler
  process models, SQS message envelopes, Guacamole behavior, or user-facing
  authentication flows.
- No formal Ground Control requirement is attached; GitHub issue #922 remains
  the source of truth.
