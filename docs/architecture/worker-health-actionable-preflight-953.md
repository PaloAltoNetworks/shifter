# Worker Health Actionability Preflight (#953)

Status: pre-implementation guidance

Date: 2026-06-11

Tracking issue: <https://github.com/Brad-Edwards/Shifter/issues/953>

## Scope Boundary

Issue #953 is about making the existing AWS worker and CTF scheduler
heartbeat checks actionable. The current app-level liveness signal is a
heartbeat file written by the worker or scheduler process and read by a
container health check. The broken boundary is outside the application:
Docker marks the container unhealthy, but `--restart unless-stopped` does
not restart unhealthy containers and the status is not emitted to
CloudWatch, ALB, or ASG health.

Keep these concepts separate:

1. Application liveness: the SQS worker or CTF scheduler poll loop is
   still making progress and touching its heartbeat file.
2. Container health: Docker or Kubernetes probes evaluate that heartbeat.
3. Host remediation: the AWS EC2 host decides whether to restart a stale
   container.
4. Operator visibility: CloudWatch logs, metrics, or alarms show that the
   remediation happened or that a container remains unhealthy.

Kubernetes already makes worker liveness actionable through pod liveness
probes in `platform/k8s/gcp/base/*` and
`platform/charts/shifter/templates/*`. This issue targets the AWS Docker
runtime path only unless the implementation changes shared probe semantics.

## Architecture Decisions

- Preserve the heartbeat-file contract. `run_worker` and
  `run_ctf_scheduler` own the application liveness source; AWS host
  supervision should consume it through Docker health status or the same
  heartbeat paths, not introduce a second application protocol.
- The canonical AWS deployment paths are
  `platform/terraform/modules/portal/ec2/user_data.sh` and
  `.github/workflows/_shifter-platform.yml`. Any runtime supervision
  added for initial bootstrap must also be represented in the SSM
  redeploy workflow so deploys and instance replacement do not diverge.
- CloudWatch alarm and metric resources belong in the existing portal EC2
  or messaging Terraform modules, using the same tag, action, period, and
  environment wiring conventions already used by SQS, Redis, engine
  provisioner, and ASG alarms.
- If a host agent is added, it is a host-runtime concern, not a Django
  service. Keep it small, deterministic, and parameterized by container
  names, health interval, and metric namespace.
- No new app-wide metrics framework is justified for #953. A minimal
  CloudWatch metric/log event from the host is acceptable if it reuses the
  existing EC2 instance profile and Terraform IAM policy style.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #953 |
| --- | --- | --- |
| Worker liveness | `shifter/shifter_platform/shared/management/commands/run_worker.py` | Keep `/tmp/worker-{queue}-heartbeat`; do not add a second worker heartbeat schema. |
| Scheduler liveness | `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py` | Keep `/tmp/ctf-scheduler-heartbeat`; do not fold scheduler health into portal `/health`. |
| AWS container launch | `platform/terraform/modules/portal/ec2/user_data.sh` | Initial boot and ASG replacement must install the same supervision artifact that redeploy uses. |
| AWS redeploy workflow | `.github/workflows/_shifter-platform.yml` | SSM redeploy must not leave stale unit files, stale container lists, or divergent health commands. |
| Portal EC2 IAM/logging | `platform/terraform/modules/portal/ec2/main.tf`, `kms.tf` | Extend least-privilege IAM in this module if `cloudwatch:PutMetricData` is needed; keep CloudWatch logs in the existing CMK-backed log group pattern. |
| Alarm conventions | `platform/terraform/modules/portal/messaging/main.tf`, `portal/redis/main.tf`, `engine-provisioner/alarms.tf` | Match alarm shape (`evaluation_periods`, `period`, dimensions, `alarm_actions`, tags); do not create a parallel alarm DSL. |
| Runtime env binding | `platform/terraform/environments/*/portal`, `platform/terraform/modules/portal/ssm`, `user_data.sh` Parameter Store reads | New knobs bind through Terraform variables or SSM parameters; no hard-coded environment-specific thresholds. |
| GCP/Kubernetes behavior | `platform/k8s/gcp/base/*worker*-deployment.yaml`, `ctf-scheduler-deployment.yaml`, Helm templates | Preserve liveness probe semantics if shared command behavior changes. |
| Tests | `shifter/shifter_platform/tests/platform/test_ctf_scheduler_startup.py`, `tests/management/test_run_worker.py` | Update startup invariants and heartbeat tests with the runtime contract; add host-supervision checks near existing platform tests. |
| Logging hygiene | `config.logging.ECSFormatter`, `shared.log_sanitize` | Logs and metric dimensions use bounded container/instance names only; no env dumps, queue URLs, secret ARNs, or command bodies. |

## Cross-Cutting Layers

- Security: the design touches the EC2 instance profile, SSM deployment
  commands, Docker host privileges, and CloudWatch. Any new IAM permission
  must be scoped in `platform/terraform/modules/portal/ec2/main.tf`; if
  `cloudwatch:PutMetricData` is added, constrain it by namespace where AWS
  supports it and avoid widening Secrets Manager, SQS, or SSM permissions.
- Secret handling: host supervision must not inspect or log container
  environments, `docker inspect` environment arrays, SSM command payloads,
  queue URLs, secret ARNs, Redis URLs, database settings, or Guacamole
  URLs. Use fixed container names and health status only.
- Env-binding shape: health intervals, monitored container names, metric
  namespace, and alarm enablement/thresholds must be parameterized through
  Terraform variables and environment tfvars or through the existing SSM
  bootstrap path. The heartbeat file names themselves remain the shared
  app contract.
- Validation: Terraform changes must pass TFLint and ADR guard; workflow
  changes must pass actionlint; shell generated by `user_data.sh` must
  preserve bootstrap failure behavior and ASG lifecycle completion only
  after the host supervision artifact is installed.
- OS/runtime exposure: a host agent or systemd unit necessarily runs with
  Docker control access. Its scope should be limited to the known worker
  containers (`worker-cms`, `worker-engine`, `worker-mc`,
  `ctf-scheduler`) and should not restart `portal` through this issue.
- Error envelopes: there is no HTTP surface in scope. Operator-facing
  errors go to CloudWatch logs/metrics using sanitized, low-cardinality
  labels: container name, instance id, health state, restart result.

## Extensibility Seam

The seam is a monitored-worker set plus health-action policy:

- monitored containers: default to `worker-cms`, `worker-engine`,
  `worker-mc`, and `ctf-scheduler`;
- health interval / stale threshold: derived from the current Docker
  health interval and heartbeat freshness;
- action: restart unhealthy container and emit a metric/log event, or
  emit-only if a future environment wants alarm-only behavior;
- metric namespace/dimensions: environment-stable namespace with
  low-cardinality dimensions (`ContainerName`, optionally ASG/name
  prefix), not queue URLs or instance-specific secrets.

This seam allows future workers to be added by editing a container list or
variable, not by copying a new shell block, Terraform alarm block, or
workflow fragment.

## Gotchas

- `--restart unless-stopped` handles process exit, not Docker `unhealthy`.
  Acceptance requires a wedged process such as `SIGSTOP` to trigger a
  restart and/or visible metric/alarm inside the health interval.
- Restarting a wedged SQS worker may release in-flight messages only after
  the SQS visibility timeout; do not lower queue visibility or delete
  messages as part of health remediation.
- CTF scheduler is single-replica by design. Do not run multiple
  schedulers on AWS to "fix" liveness; use restart/visibility instead.
- Docker health state is local to the EC2 host. ALB target health and ASG
  instance health will not see worker-only failure unless the design emits
  a metric/alarm or explicitly escalates to instance replacement.
- The AWS workflow contains a redeploy-time copy of the Docker run
  commands. Updating only `user_data.sh` fixes fresh instances but leaves
  SSM redeploys with the old behavior.
- CloudWatch metric dimensions can become expensive and noisy if they
  include instance ids, queue URLs, image tags, or command lines. Keep
  dimensions low-cardinality.
- A host-level monitor that restarts any unhealthy container may mask web
  health issues or fight manual operations. Scope the first version to the
  worker/scheduler set.

## Anti-Patterns

- Treating Docker `HEALTHCHECK` alone as actionable remediation.
- Moving worker health into the public portal `/health` endpoint.
- Adding a second heartbeat file naming convention or duplicate worker
  health schema.
- Replacing the SQS worker or CTF scheduler process model in this issue.
- Logging `docker inspect` output, environment variables, queue URLs, or
  secret ARNs to prove health state.
- Granting broad `cloudwatch:*`, `ssm:*`, `secretsmanager:*`, or
  `docker`-shell behavior beyond the existing host boundary.
- Fixing only one deploy path (`user_data.sh` or SSM workflow) and letting
  the other drift.

## Non-Goals

- No redesign of portal `/health`, ALB health checks, ASG scaling, or the
  portal ASGI runtime.
- No GCP/Kubernetes remediation redesign unless shared worker heartbeat
  behavior changes.
- No SQS schema, handler, visibility-timeout, DLQ, or message envelope
  change.
- No CTF scheduler task-claiming, stale-task recovery, or multi-scheduler
  design change.
- No new Ground Control requirement is attached; GitHub issue #953 is the
  source of truth.
