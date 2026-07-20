# Worker Restart Metric Filter Preflight (#274)

Status: pre-implementation guidance

Date: 2026-06-25

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/274>

## Scope Boundary

Issue #274 is a requirement-free maintenance issue. The GitHub issue is the
shipping contract: create CloudWatch visibility for SQS worker restart warnings
emitted by `run_worker` and alert when restarts are frequent.

Keep these concepts separate:

1. Application restart detection: `run_worker` sees a stale heartbeat file on
   startup and logs `Worker restart detected: queue=...`.
2. Host remediation/liveness: the #953 worker-health supervisor restarts
   unhealthy Docker containers and emits `Shifter/WorkerHealth` metrics.
3. Backend queue pressure: SQS queue depth, age, and DLQ alarms live in the
   portal messaging module.
4. Portal web capacity: `Shifter/PortalCapacity` is for request-path and
   terminal saturation, not background worker lifecycle.
5. Alert routing: portal alarms notify the existing per-environment SNS alerts
   topic when `alarm_email` is configured.

This issue should add observability, not alter worker heartbeat semantics,
message handling, queue visibility timeouts, or host restart policy.

## Architecture Decisions

- Put the metric filter and alarm in `platform/terraform/modules/portal/ec2`
  unless a broader monitoring module already exists for the same portal log
  group. The EC2 module owns `/portal/{name_prefix}` through
  `aws_cloudwatch_log_group.portal` and already owns worker-health alarms.
- Use the issue namespace and metric name for the log-derived signal:
  `Shifter/Workers` / `WorkerRestarts`. Do not put this app-log-derived count in
  `Shifter/PortalCapacity`, and do not confuse it with the host supervisor's
  `Shifter/WorkerHealth` `Restarted` metric.
- Route notifications through the existing environment alerts topic. Reuse
  `worker_health_alarm_actions` if the implementation broadens that variable to
  mean worker-lifecycle alarms; add a separate `worker_restart_alarm_actions`
  only if routing genuinely differs. Do not create a new SNS topic for this
  single alarm.
- Scope custom metrics to the environment with `NamePrefix = var.name_prefix`.
  CloudWatch custom metrics are account/region scoped; dev and prod must not
  share one undimensioned `WorkerRestarts` series.
- Treat `queue` as a low-cardinality diagnostic dimension only if the filter
  pattern can extract it from structured fields. The current ECS JSON log has
  the queue embedded inside the `message` string, so a literal substring pattern
  such as `"\"Worker restart detected\""` does not itself expose a queue field
  for metric dimensions.
- If queue dimensioning is mandatory, first make the warning structured using
  the existing `config.logging.ECSFormatter` path, then validate the CloudWatch
  filter pattern against a sample ECS JSON event. Do not add ad hoc log parsing
  infrastructure.
- The alert condition remains the issue contract: `Sum > 3` over `300` seconds,
  `evaluation_periods = 1`, `treat_missing_data = "notBreaching"`, and SNS
  actions wired from the environment.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #274 |
| --- | --- | --- |
| Worker restart source | `shifter/shifter_platform/shared/management/commands/run_worker.py` | Preserve the stale-heartbeat warning contract unless adding a structured, bounded queue field. |
| ECS JSON logging | `shifter/shifter_platform/config/logging.py`, `config/_logging_config.py` | Reuse the existing formatter/labels path; do not introduce a second logging schema. |
| Portal log group | `platform/terraform/modules/portal/ec2/main.tf` | Bind filters to `aws_cloudwatch_log_group.portal.name`, not hard-coded `/portal/dev` or `/portal/prod`. |
| Worker lifecycle alarms | `platform/terraform/modules/portal/ec2/main.tf`, `worker-health/**`, `test_worker_health_supervision.py` | Keep #953 remediation metrics separate, but follow the same alarm/action/tag style. |
| Portal observability alarm shape | `platform/terraform/modules/portal/ec2/observability.tf` | Match explicit period, statistic, dimensions, actions, tags, and missing-data behavior. |
| Existing log metric filter | `platform/terraform/modules/engine-provisioner/alarms.tf` | Reuse provider-native `aws_cloudwatch_log_metric_filter`; do not build a Lambda/Logs Insights pipeline. |
| SQS alarm conventions | `platform/terraform/modules/portal/messaging/main.tf` | Keep restart alerts separate from backlog/message-age/DLQ alarms. |
| Alert routing | `platform/terraform/environments/{dev,prod}/portal/main.tf` shared `aws_sns_topic.alerts` | Wire through module variables from the existing topic; no new notification surface. |
| Structural tests | `shifter/shifter_platform/tests/platform/test_worker_health_supervision.py` | Add focused Terraform invariant tests near existing platform tests. |
| Enforcement | `scripts/adr_guard/adr_guard.py`, `.tflint.hcl`, Checkov, Terraform fmt/validate | Do not weaken IaC or architecture gates to land an alarm. |

## Cross-Cutting Layers

- Auth surface: none. Do not add an HTTP/admin diagnostics endpoint for this
  issue.
- Secret-handling surface: metric filters and dimensions may include only
  bounded identifiers such as `NamePrefix` and queue names (`cms`, `engine`,
  `mc`). Do not log or dimension by queue URL, ARNs, image tags, command lines,
  environment variables, secret names, exception text, request data, or user
  identifiers.
- Env-binding shape: the log group comes from `local.log_group_name`; alert
  actions come from environment roots; thresholds should be Terraform variables
  only if the implementation needs environment-specific values. Avoid workflow-
  only knobs or hard-coded environment names.
- IAM/policy surface: CloudWatch Logs metric filters and alarms do not require
  widening the EC2 instance role or adding `cloudwatch:PutMetricData`. The #953
  and #940 namespace-conditioned PutMetricData grants must stay unchanged.
- OS/runtime exposure: no new host agent, Docker argv, systemd unit, or SSM
  command is needed. The existing Docker `awslogs` driver sends container logs
  to the portal log group.
- Config validators: Terraform variable validation/preconditions, TFLint,
  Checkov, ADR guard, and Terraform validate remain active for the touched IaC.
  If a structured log field is added, Django/Python tests must pin the emitted
  field without weakening logging hygiene.
- Error-envelope surface: none. Metric-filter or alarm failures are
  deployment/operator issues, not user-facing API responses.
- CloudWatch metric-filter surface: dimensions are supported only from JSON or
  space-delimited fields that the filter pattern exposes, and metric filters
  with dimensions cannot use `default_value`. Validate the pattern with a sample
  ECS JSON log before relying on queue dimensions.

AWS reference: <https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntaxForMetricFilters.html>

## Extensibility Seam

The durable seam is a worker restart signal contract:

- namespace/name: `Shifter/Workers` / `WorkerRestarts`;
- required scope dimension: `NamePrefix`;
- optional diagnostic dimension: `Queue`, sourced from a structured log field;
- alert threshold: restarts per period, defaulting to `> 3` in `300` seconds;
- queue set: derive from the existing SQS worker consumer set or a small
  validated Terraform variable if per-queue alarms are used;
- action routing: existing per-environment alert topic.

The next reasonable changes should be parameter changes, not a new monitoring
stack: add a worker queue, tune the restart threshold by environment, add a
dashboard widget, or introduce GCP parity later without rewriting worker
heartbeat/remediation.

## Gotchas

- A metric filter with `dimensions = { Queue = ... }` creates dimensioned metric
  series. A plain alarm without matching dimensions will not automatically alarm
  on the sum of all queue-specific series. Use an aggregate `NamePrefix` series,
  supported metric math, or per-queue alarms deliberately.
- The issue's sample Terraform omits `treat_missing_data`; follow repo alarm
  conventions and make missing logs non-breaching.
- Do not copy `default_value = "0"` from the engine-provisioner metric filter if
  this metric transformation has dimensions; CloudWatch does not allow default
  values for dimensioned metric filters.
- The warning is emitted only when a stale heartbeat file exists on worker
  startup. It is not identical to the #953 host supervisor's `Restarted` metric,
  and it may not fire for graceful deploys that clean up heartbeats.
- Testing repeated crashes should avoid dumping `docker inspect`, container
  env, or SSM command payloads into logs or artifacts.
- If a log label with a dot in the JSON key is used, the CloudWatch JSON filter
  syntax may need bracket notation. Validate the exact pattern before merge.

## Anti-Patterns

- Creating a new monitoring module, SNS topic, Lambda, Logs Insights scheduled
  query, or app metrics framework for this one log-derived counter.
- Reusing `Shifter/PortalCapacity` for SQS worker lifecycle events.
- Collapsing the log-derived restart count with host remediation metrics without
  preserving the semantic difference.
- Hard-coding `/portal/dev`, `dev-portal`, or queue names in environment roots
  when module variables already carry the shape.
- Dimensioning custom metrics by instance id, queue URL, ARN, image tag,
  command line, exception text, request path, user/session id, or secret name.
- Changing SQS visibility timeouts, DLQ policy, heartbeat file names, or worker
  process behavior to make the alarm easier to test.

## Non-Goals

- No implementation in this preflight note.
- No new ADR is required unless implementation changes repo-wide logging schema,
  creates a new monitoring abstraction, or changes worker liveness/remediation
  contracts.
- No GCP/Kubernetes parity, Prometheus/statsd deployment, CloudWatch dashboard,
  HTTP diagnostics endpoint, persistence, DTO, service, repository, or exception
  hierarchy is required for #274.
- No change to worker message schemas, queue consumers, visibility timeout, DLQ
  handling, host supervisor scope, or portal web autoscaling.

## Validation

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups that touch Terraform should also run:

```bash
terraform fmt -check -recursive platform/terraform
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

If structured app logging changes are made, add or update focused Python tests
under `shifter/shifter_platform/tests` and run the relevant `uv run pytest`
target.
