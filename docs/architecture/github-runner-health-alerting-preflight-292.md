# GitHub Runner Health Alerting Preflight (#292)

Status: pre-implementation guidance

Date: 2026-06-25

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/292>

## Scope Boundary

This issue adds health visibility for the EC2 self-hosted GitHub Actions runner
pool. It is infrastructure and operations work, not a change to CI routing,
workflow trust, or application runtime behavior.

Keep these signals separate:

1. EC2 platform health: AWS instance and system status checks, plus sustained
   CPU saturation as a hang proxy.
2. SSM reachability: whether AWS Systems Manager can manage the runner host.
3. Runner service liveness: whether the installed `actions.runner.*` systemd
   service is active on the host.
4. GitHub scheduler status: whether GitHub reports a registered runner online.
5. Remediation: operator runbook steps or a deliberately scoped EC2
   recover/reboot action.

One metric or Lambda that tries to collapse all five will be hard to operate and
will blur the security boundary around GitHub tokens and SSM privileges.

The GitHub issue is the source of truth for acceptance. No Ground Control
requirement is attached.

## Architecture Decisions

- Build on the existing runner Terraform root:
  `platform/terraform/global/github-runner/**`. Do not create a second runner
  stack or a generic monitoring framework for this issue.
- Use Terraform-managed CloudWatch alarms for native EC2 signals:
  `StatusCheckFailed`, `StatusCheckFailed_Instance`,
  `StatusCheckFailed_System`, and sustained `CPUUtilization`.
- Runner process health should follow the existing portal worker-health shape:
  a small host-level systemd timer emits a low-cardinality custom metric to a
  runner-specific namespace, then CloudWatch alarms on the metric or missing
  data. Keep this host-runtime concern out of Django and out of workflows.
- SSM connectivity can be covered in two layers. First, missing runner
  heartbeat data should alarm because a hung host cannot publish. If acceptance
  requires the exact SSM `PingStatus=ConnectionLost` state, add a small
  AWS-native poller with `ssm:DescribeInstanceInformation` and
  `cloudwatch:PutMetricData`; keep it read-only and token-free.
- Do not poll the GitHub API from CloudWatch/Lambda with a PAT as the first
  design. Local runner service health plus EC2/SSM reachability catches the
  incident class described in the issue without introducing long-lived GitHub
  credentials on AWS. If GitHub API status becomes required later, use a
  dedicated credential design and do not pass tokens in process argv or
  Terraform variables.
- Notifications should flow through SNS alarm actions. The runner root may own a
  runner-alerts topic or accept an `alarm_actions` list, but alarms should not
  hard-code email, Slack, or Teams destinations. Slack/Teams can subscribe to
  SNS later through the account's approved integration.
- Auto-recovery must be narrow and opt-in. `StatusCheckFailed_System` is the
  only obvious candidate for EC2 recover/reboot automation. Runner service
  offline, SSM disconnected, and CPU saturation should notify first; automatic
  restart there can destroy diagnostic state or interrupt jobs.
- The response runbook should live under `docs/ops/` and link back to this
  preflight. It should cover SSM session checks, service status, GitHub runner
  page/API verification, safe reboot/stop-start criteria, and post-recovery
  queue verification.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #292 |
| --- | --- | --- |
| Runner infrastructure | `platform/terraform/global/github-runner/{main.tf,variables.tf,outputs.tf,README.md}` | Add alarms, IAM, host health artifacts, variables, and operator docs here unless a shared topic is deliberately imported. |
| Runner deploy wrapper | `scripts/runner-deploy.sh` | Preserve plan-by-default behavior and the tracked lockfile; do not add unreviewed AWS mutations or GitHub API calls to ordinary plan runs. |
| Bootstrap runner guidance | `scripts/bootstrap/runner.py`, `scripts/bootstrap/README.md` | Keep registration and troubleshooting instructions aligned with the Terraform root and runbook. |
| CloudWatch alarm shape | `platform/terraform/modules/portal/messaging/main.tf`, `portal/ec2/{main.tf,observability.tf}`, `portal/redis/main.tf`, `engine-provisioner/alarms.tf` | Use explicit period, evaluation periods, statistic, dimensions, `treat_missing_data`, `alarm_actions`, `ok_actions`, and tags. |
| Host health monitor precedent | `platform/terraform/modules/portal/ec2/worker-health/**`, `shifter/shifter_platform/tests/platform/test_worker_health_supervision.py` | Reuse the systemd timer plus custom-metric invariants conceptually; do not make the runner monitor restart portal workers or share its namespace. |
| IAM least privilege | `platform/terraform/modules/portal/ec2/main.tf` `cloudwatch_metrics*` policies | `cloudwatch:PutMetricData` uses `Resource="*"` with a `cloudwatch:namespace` condition. Do not grant `cloudwatch:*` or widen SSM/ECR. |
| Alert destination pattern | `platform/terraform/environments/*/portal/main.tf` shared `alerts` topic and `*_alarm_actions` variables | Parameterize alarm actions; keep destination plumbing outside individual alarm resources. |
| Terraform security policy | `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml`, ADR-004 | New Checkov skips require inline rationale and ADR exception metadata; do not add broad skip-checks for this root. |
| Live identifier hygiene | `scripts/adr_guard/adr_guard.py` ADR-004 identifier check | Do not commit the live instance IDs from the issue. Use Terraform references, outputs, or tag filters. |
| Workflow runner exposure | ADR-003 in `docs/adr/index.yaml`, `scripts/adr_guard/adr_guard.py` deploy workflow checks | This issue must not route pull requests to self-hosted deploy runners or weaken workflow gating. |

## Cross-Cutting Layers

Security layers the intended design must pass:

- GitHub auth surface: runner registration tokens remain one-time operator
  actions. The health design should not add a PAT, registration token, or
  removal token to Terraform state, user data, SSM Parameter Store, Lambda env,
  CloudWatch logs, or process argv. If a future GitHub API poller is approved,
  it needs a separate credential design with narrow scope, rotation, and log
  redaction.
- AWS IAM surface: the runner EC2 role currently has inline SSM agent and ECR
  access. Add only the minimum needed for health publication, preferably
  `cloudwatch:PutMetricData` constrained by `cloudwatch:namespace`. A Lambda SSM
  poller, if added, gets read-only SSM describe permission and namespace-bound
  metric write; it must not get `ssm:SendCommand`.
- Secret-handling surface: metrics, logs, dashboards, alarm descriptions, and
  runbook examples must not include runner registration tokens, GitHub tokens,
  repository secrets, environment dumps, SSM command payloads, Docker env, or
  Terraform state contents.
- Env-binding shape: thresholds, periods, alarm enablement/actions, runner
  count, metric namespace, and optional auto-recovery behavior are Terraform
  variables or local values in the runner root. Do not hard-code account-local
  instance IDs, emails, Slack webhooks, or region-specific values beyond the
  root's existing `var.region` default.
- Config validation layer: Terraform changes must pass `terraform fmt`,
  TFLint, Checkov through the existing config, and ADR guard. Shell/systemd
  artifacts should be pinned by structural tests like the worker-health monitor.
- OS/runtime exposure: host scripts run with systemd and can observe runner
  service state. They should use `systemctl is-active 'actions.runner.*'` or an
  explicit service name pattern, IMDSv2 for region/instance identity, and AWS CLI
  argv arrays. They must not run arbitrary SSM commands, scrape process
  environments, or dump `journalctl` contents into CloudWatch metrics.
- Error/log surface: failures should log bounded status fields such as runner
  name, instance id, service active/inactive, SSM ping state, and metric publish
  result. Avoid stack traces or command output that could contain workflow data.
- Notification surface: CloudWatch alarms publish to SNS. Alarm messages should
  be actionable and name the signal, threshold, and runbook, but should not carry
  credentials, live issue-provided identifiers, or rendered Terraform inputs.

Maintainability incumbents the implementation must build on:

- The `global/github-runner` Terraform root as the owning boundary.
- Existing CloudWatch alarm conventions in portal/messaging, portal/ec2,
  portal/redis, log-aggregation, and engine-provisioner.
- The portal worker-health systemd timer pattern for local liveness to
  CloudWatch metrics.
- `scripts/runner-deploy.sh` for local runner Terraform operations.
- `scripts/bootstrap/runner.py` and `platform/terraform/global/github-runner/README.md`
  for operator-facing runner lifecycle instructions.
- ADR guard, TFLint, Checkov, and actionlint if workflows are touched.

Extensibility point:

Use a single runner health signal contract:

- monitored runners: derived from `aws_instance.runner` and `runner_count`, not
  hard-coded IDs;
- signals: EC2 status, CPU saturation, runner service active, optional SSM ping;
- metric namespace and dimensions: environment/account scoped, low cardinality,
  with `RunnerName` and optionally `InstanceId`;
- notification actions: `alarm_actions` list for SNS destinations;
- remediation action: separate variable-gated list for EC2 recover/reboot only.

That contract lets a future change add runner disk pressure, agent version
drift, GitHub API status, or Slack/Teams delivery without editing every alarm or
adding a second monitoring root.

## Whole-Repo Scope

Likely in scope for implementation:

- `platform/terraform/global/github-runner/**`
- `scripts/runner-deploy.sh` only if outputs or validation messages change
- `scripts/bootstrap/runner.py` and `scripts/bootstrap/README.md` if operator
  registration/troubleshooting instructions change
- `docs/ops/github-runner-health-alerts.md` or similar runbook
- `shifter/shifter_platform/tests/platform/**` or a small repo-native test path
  for structural invariants around Terraform, IAM, and systemd artifacts
- `changelog.d/292.changed.md` or `292.fixed.md` if the implementation changes
  deploy/runtime behavior rather than docs only

Usually out of scope:

- `.github/workflows/**` runner routing changes, unless a test or doc link is
  required. Do not use this issue to move job classes between runner pools.
- Portal, engine, CTF, GCP/Kubernetes, range provisioning, or application health
  endpoints.
- New shared metrics frameworks, config schemas, exception hierarchies, or
  persistence models.
- GitHub App/PAT credential management unless the implementation explicitly
  chooses GitHub API status as a separate monitored signal.

## Gotchas And Anti-Patterns

- Do not commit live EC2 instance IDs from the issue body. This violates the
  repo's identifier hygiene guard and couples alarms to replaceable hosts.
- Do not conflate an active `actions.runner.*` service with GitHub accepting
  jobs. Treat GitHub API status as a distinct signal with a distinct credential
  risk.
- Do not make SSM `PingStatus` a local-only check if the host can hang. Missing
  host heartbeat data should alarm; exact SSM ping status requires external
  read-only polling.
- Do not alarm on high CPU with a one-period threshold. Sustained saturation is
  useful as a hang proxy; short spikes are normal for build jobs.
- Do not auto-reboot on runner service offline, SSM disconnected, or high CPU by
  default. Notify and follow the runbook first.
- Do not put GitHub tokens, Slack webhooks, or SNS email endpoints in user data,
  shell history, SSM commands, tfvars examples, or CloudWatch logs.
- Do not add `ssm:SendCommand`, `cloudwatch:*`, `secretsmanager:*`, or broad KMS
  grants to implement simple monitoring.
- Do not reuse `Shifter/WorkerHealth` for runner metrics. Use a runner-specific
  namespace so worker alarms and runner alarms cannot cross-trip.
- Do not weaken ADR guard, Checkov, TFLint, actionlint, self-hosted runner
  exposure checks, or identifier hygiene to land the monitoring change.

## Non-Goals

- No implementation in this preflight note.
- No new autoscaling runner fleet, runner replacement controller, GitHub App,
  Slack/Teams integration, or CI routing redesign.
- No migration away from the current plain EC2 runner root.
- No changes to application health endpoints, worker liveness, portal
  autoscaling, range provisioning, or GCP/Kubernetes runtime behavior.
- No Ground Control requirement or traceability object is created for this
  requirement-free issue.

## Validation

For this preflight documentation change, run:

```sh
python3 scripts/adr_guard/adr_guard.py --files docs/architecture/github-runner-health-alerting-preflight-292.md --level fast
```

For the eventual implementation, also run the repo-mandated Terraform and
architecture checks for touched files:

```sh
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```
