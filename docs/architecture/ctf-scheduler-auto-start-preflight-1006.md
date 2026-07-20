# CTF Scheduler Auto-Start Preflight (CTF-1006)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: `CTF-1006` - Scheduler Auto-Start

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

This note is intentionally not an implementation plan. It records the
repository-wide boundaries for maintaining the existing CTF scheduler auto-start
and crash-recovery contract while adding or strengthening test traceability.

## Scope Boundary

`CTF-1006` is about runtime ownership of the CTF scheduler process and durable
recovery of pending work:

1. every supported application runtime starts `python manage.py run_ctf_scheduler`
   without a separate manual operator step;
2. process exits and wedged-heartbeat failures are remediated by the runtime
   layer for that platform;
3. scheduler startup re-evaluates pending and stale `CTFScheduledTask` rows;
4. duplicate execution is prevented by database coordination and idempotent CTF
   range services, not by assuming only one host can ever run a scheduler.

Do not move scheduler ownership into Django app import side effects, request
handlers, cron-only host setup, or Ground Control metadata.

## Architecture Decisions And Guardrails

- Keep the scheduler as a Django management command. `ctf.apps.CtfConfig.ready()`
  registers signals only; it must not spawn background scheduler threads from web
  or ASGI processes.
- Reuse the existing process-supervision surfaces: local compose
  `ctf-scheduler`, AWS Docker launch plus worker-health systemd timer, and GCP
  static base plus Helm `ctf-scheduler` Deployment.
- Preserve the existing heartbeat contract:
  `/tmp/ctf-scheduler-heartbeat` is app liveness for Docker and Kubernetes
  probes; `CTFScheduledTask.updated_at` is scheduled-task liveness for stale
  recovery. Do not conflate them.
- Preserve the durable scheduler contract in `CTFScheduledTask`,
  `ScheduledTaskType`, `ScheduledTaskStatus`, and
  `ctf/management/commands/run_ctf_scheduler.py`. Do not introduce a second task
  table, status enum, queue, or scheduler registry.
- Keep crash recovery startup-owned and database-backed:
  `_recover_stale_tasks()` runs in the poll loop, and `_fetch_due_tasks()` claims
  due work with `select_for_update(skip_locked=True)`.
- Keep GCP least privilege explicit. The `ctf-scheduler` service account may
  launch Jobs through `job-launcher` RBAC, but the provisioner admission policy
  must still deny arbitrary Jobs that target the privileged `provisioner`
  identity.
- Keep AWS remediation host-scoped and low-cardinality. The worker-health agent
  may restart worker/scheduler containers and emit `Shifter/WorkerHealth`
  metrics; it must not restart `portal` or log container environments.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for CTF-1006 |
| --- | --- | --- |
| App startup | `ctf.apps.CtfConfig.ready()` | Register signals only; no scheduler thread/process side effect. |
| Scheduler command | `ctf/management/commands/run_ctf_scheduler.py` | Keep signal handling, heartbeat, stale recovery, due-task claiming, and handler dispatch here. |
| Scheduled task persistence | `ctf.models.CTFScheduledTask`, `ctf.enums` | Use existing fields and status/type enums; no duplicate schemas or task states. |
| Range provisioning | `ctf.services.range.tasks`, `batch`, `provision` | Preserve coalescing, idempotency, heartbeat, and participant row-locking behavior. |
| Local runtime | `shifter/shifter_platform/docker-compose.yml` | `ctf-scheduler` remains a first-class service with restart policy and heartbeat healthcheck. |
| AWS runtime | `platform/terraform/modules/portal/ec2/user_data.sh`, `scripts/portal-deploy/deploy_portal.sh`, `.github/workflows/_shifter-platform.yml` | Fresh boot and SSM redeploy must start the scheduler and install byte-identical worker-health supervision. |
| GCP runtime | `platform/k8s/gcp/base`, `platform/charts/shifter` | Static base and Helm output must stay equivalent for scheduler Deployment, ServiceAccount, token mount, and RBAC. |
| GCP admission | `validatingadmissionpolicy-provisioner-jobs.yaml` | Scheduler token must not be able to run arbitrary privileged provisioner Jobs. |
| Runtime env | `config.settings`, `config/_env_manifest.py`, `platform-runtime` ConfigMap, AWS Parameter Store/env wiring | New knobs, if unavoidable, must be typed, fail-loud, and routed through canonical env binding. |
| Logging | module loggers, `shared.log_sanitize.safe_log_value()` | Log task ids, event ids, statuses, counts, and health state only; no secrets, env dumps, or provider payloads. |
| Tests | `tests/platform/test_ctf_scheduler_startup.py`, `test_worker_health_supervision.py`, `test_gcp_job_launcher_manifests.py`, `tests/ctf/test_services/test_scheduler_concurrency.py` | Strengthen these maintained invariants instead of adding placeholder trace tests. |

## Cross-Cutting Layers

- Auth surface: no new public scheduler control endpoint is needed. Manual
  scheduling/provisioning remains behind the existing CTF organizer permissions
  and event ownership checks; the scheduler command is a trusted runtime process.
- Secret-handling surface: do not pass secrets through scheduler argv,
  `CTFScheduledTask.metadata`, liveness probes, worker-health logs, Kubernetes
  policy fixtures, or Ground Control trace metadata.
- Env-binding shape: scheduler settings belong in `config.settings` using the
  existing helpers and must be reflected in the generated env manifest when they
  are runtime-operational knobs. GCP runtime values flow through
  `platform-runtime`; AWS values flow through the existing Parameter Store/env
  bootstrap path.
- Config validators: Kubernetes changes must satisfy restricted PSS,
  NetworkPolicy, kube-linter, kubeconform, Helm render, and ADR guard checks.
  Terraform/workflow changes must keep TFLint/actionlint/ADR guard happy.
- OS/runtime exposure: command lines should stay non-secret and boring:
  `python manage.py run_ctf_scheduler` plus bounded numeric flags only if needed.
  Do not add host lock files or secret-bearing shell wrappers.
- Error envelopes: scheduler failures stay in internal task state and logs.
  Public CTF APIs keep their existing controlled JSON/shared API envelopes and
  must not expose raw provider exceptions or task `error_message`.
- Observability: keep liveness and remediation low-cardinality: heartbeat files,
  task status transitions, worker-health container names, name-prefix dimensions,
  and aggregate counts.

## Extensibility Seam

The seam is a small runtime-owner profile for each supported platform:

- command: the scheduler management command and optional non-secret numeric
  settings-backed flags;
- health: the shared heartbeat file and probe timing;
- supervision: compose restart, AWS worker-health restart/metric policy, or GCP
  Deployment liveness restart;
- privilege: the service account/token shape required to launch allowed CTF jobs;
- persistence: database task claiming/recovery and range-service idempotency.

Future worker-like processes should extend that profile rather than copying a
new process-management pattern into one deploy target.

## Gotchas And Anti-Patterns

- `AppConfig.ready()` can run in every Django process and during management
  commands; spawning the scheduler there creates duplicate schedulers and
  import-time side effects.
- A process heartbeat proves the loop is alive; it does not prove a claimed task
  is still progressing. Long handlers must keep task `updated_at` fresh.
- Docker `--restart unless-stopped` does not restart unhealthy containers; the
  AWS worker-health timer is the actionable remediation layer.
- GCP `replicas: 1` is an operational default, not the correctness mechanism.
  Database locking and idempotent services still carry duplicate-prevention.
- Updating only one deploy path leaves the requirement partially broken:
  compose, AWS fresh boot, AWS SSM redeploy, static GCP manifests, and Helm must
  stay aligned when command or health semantics change.
- Do not weaken the GCP admission policy just because the scheduler needs to
  create Jobs. It may launch allowed work; it must not inherit provisioner power.
- Do not create trace links to docs or broad smoke tests that do not assert the
  scheduler startup/recovery contract.

## Non-Goals

- No scheduler framework replacement, Celery/RQ/SQS migration, cron-only
  fallback, or new public scheduler API.
- No redesign of CTF event scheduling semantics, CMS/Engine range contracts,
  notification rendering, scoring, or challenge release.
- No broad Kubernetes RBAC, Workload Identity, GCP IAM, AWS instance-profile, or
  portal `/health` redesign.
- No change to Ground Control `IMPLEMENTS` links is required by this preflight;
  implementation follow-up should reconcile meaningful `TESTS` links only when
  maintained tests are added or strengthened.

## Validation

For changes touching architecture, workflows, Kubernetes, Terraform, hooks, or
`shifter/shifter_platform`, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

When implementation touches the matching subsystem, also run the stack-native
platform checks documented in `AGENTS.md` and the focused scheduler/platform
tests listed above.
