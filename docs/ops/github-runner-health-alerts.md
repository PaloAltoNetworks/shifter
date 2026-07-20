# GitHub Runner Health Alerts Runbook

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/292>
Design note: [`docs/architecture/github-runner-health-alerting-preflight-292.md`](../architecture/github-runner-health-alerting-preflight-292.md)
Region: `us-east-2`

This runbook is the operator procedure for responding to CloudWatch alarms on the
self-hosted GitHub Actions runner pool
(`platform/terraform/global/github-runner/`). The alarms exist because a runner
host once froze (SSM connectivity lost, instance hung) and the outage was only
caught by manual investigation. A queued Actions job waited until the host was
manually stop/started.

## Signals

Each runner (`shifter-github-runner-N`) has four CloudWatch alarms. All publish
to the `shifter-github-runner-alerts` SNS topic; alarm and OK transitions both
notify.

| Alarm suffix | Source metric | Fires when | Auto-action |
|---|---|---|---|
| `status-check-instance` | `AWS/EC2 StatusCheckFailed_Instance` | guest OS or network unreachable for two 60-second periods | none (notify) |
| `status-check-system` | `AWS/EC2 StatusCheckFailed_System` | AWS hardware fault for two 60-second periods | EC2 `recover` when `enable_system_auto_recovery = true` |
| `cpu-high` | `AWS/EC2 CPUUtilization` | average CPU above `cpu_alarm_threshold` (default 95%) for two 5-minute periods | none (notify) |
| `service-inactive` | `Shifter/RunnerHealth RunnerServiceActive` | `actions.runner.*` service inactive **or the host stops reporting** for two 60-second periods | none (notify) |

The `service-inactive` alarm treats missing data as **breaching**: a hung host
cannot run the host monitor, so the absence of the heartbeat is itself the
hung-host signal. This is the alarm that catches the original incident class. All
alarms fire within the 10-minute acceptance window.

## How the runner-service signal works

A systemd timer (`shifter-runner-health.timer`, every 60 seconds) runs
`/usr/local/bin/shifter-runner-health.sh`, which reports
`systemctl is-active 'actions.runner.*'` as the `RunnerServiceActive` custom
metric (1 = active, 0 = inactive), dimensioned by `RunnerName`. The monitor holds
no GitHub token and does not poll the GitHub API; it only reads local service
state and calls `cloudwatch:PutMetricData` under a namespace-scoped IAM grant.

> A freshly applied runner host reports `RunnerServiceActive = 0` until the runner
> is registered (`./config.sh` + `svc.sh install/start`, see the root README).
> Expect `service-inactive` to be in ALARM during standup; it clears once the
> service is running. Register promptly after apply.

## Rolling out the monitor to existing runners

The monitor is installed by instance `user_data`, which only runs on first boot.
`aws_instance.runner` sets `user_data_replace_on_change = true`, so applying the
runner root **replaces** any existing runner whose `user_data` changed and the
replacement boot installs the monitor. Plan against the existing pool before
applying.

- A replaced runner loses its registration. Re-register it (mint a new
  registration token, re-run `config.sh` + `svc.sh`, see the root README) after
  the new instance comes up.
- To avoid dropping all self-hosted capacity at once, apply with `-target` one
  runner at a time, or accept a brief capacity gap and re-register both.
- Until a replaced runner is re-registered, its `service-inactive` alarm is in
  ALARM (expected, since `RunnerServiceActive = 0`); it clears once `svc.sh start`
  runs.

## Responding to an alarm

1. **Identify the runner.** The alarm name is
   `shifter-github-runner-N-<suffix>`. Resolve its instance id:
   ```sh
   cd platform/terraform/global/github-runner
   terraform output runner_instance_ids
   ```

2. **Open an SSM session** (no SSH):
   ```sh
   aws ssm start-session --target <instance-id> --region us-east-2
   ```
   If the session itself fails to connect, treat the host as hung and skip to
   step 5 (the `service-inactive` breaching alarm and/or a failed instance status
   check corroborate this).

3. **Check the runner service** on the host:
   ```sh
   systemctl status 'actions.runner.*'
   systemctl is-active 'actions.runner.*'
   journalctl -u 'actions.runner.*' --no-pager -n 50
   ```
   A stopped-but-recoverable service: `sudo systemctl restart 'actions.runner.*'`.

4. **Verify GitHub's view.** Confirm the runner shows online at
   <https://github.com/Brad-Edwards/shifter/settings/actions/runners>. An active
   local service with the runner showing offline on GitHub points at network or
   registration, not the host; re-register per the root README if needed.

5. **Safe reboot / stop-start criteria.** A hung host (SSM unreachable, instance
   status check failing, no heartbeat) needs a power cycle:
   - **System status check failing:** if `enable_system_auto_recovery` is set,
     EC2 auto-recovery already moved the instance to healthy hardware (id, EBS,
     IP preserved); confirm and wait. Otherwise trigger a manual recover.
   - **Instance status check failing or host frozen:** stop/start (not just
     reboot, which keeps it on the same wedged host):
     ```sh
     aws ec2 stop-instances --instance-ids <instance-id> --region us-east-2
     aws ec2 start-instances --instance-ids <instance-id> --region us-east-2
     ```
     A new boot re-runs user_data and re-installs the health monitor; the runner
     service auto-starts if it was installed as a service.
   - Do **not** reflexively reboot on `cpu-high` alone; a long build can saturate
     CPU legitimately. Inspect first.

6. **Post-recovery verification.**
   - `RunnerServiceActive` returns to 1 and the alarm transitions to OK.
   - The runner shows online on GitHub.
   - Re-run or re-queue the affected Actions job and confirm it picks up.

## Notification setup

Alarm actions always target the `shifter-github-runner-alerts` SNS topic
(`terraform output runner_alerts_topic_arn`). To receive alerts:

- **Email:** set `alarm_email` in the runner root tfvars and apply; confirm the
  subscription email.
- **Slack / Teams:** subscribe the channel integration (for example, AWS Chatbot)
  to the topic ARN. No alarm resource changes are required.

## Deferred signals

Out of scope for #292, documented here so the gap is explicit:

- **Exact SSM `PingStatus=ConnectionLost`.** The `service-inactive` breaching
  alarm already catches a host that cannot be SSM-managed (it stops publishing).
  An exact ping-status signal needs a read-only AWS-native poller
  (`ssm:DescribeInstanceInformation` + `cloudwatch:PutMetricData`); add it only if
  acceptance later requires the precise SSM state.
- **GitHub-API runner-online status.** Distinguishing "service active locally" from
  "GitHub accepting jobs" needs a long-lived GitHub credential on AWS. Deferred to
  avoid introducing a PAT; revisit with a dedicated, rotated, scoped credential
  design if required.
