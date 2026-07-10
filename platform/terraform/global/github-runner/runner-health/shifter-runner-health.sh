#!/usr/bin/env bash
# ==============================================================================
# Shifter GitHub Actions runner host-health monitor (issue #292)
# ==============================================================================
# A runner host froze (SSM connectivity lost, instance hung) and the outage was
# only caught by manual investigation. Native EC2 status-check and CPU alarms
# cover the platform layer, but nothing reported whether the installed Actions
# runner systemd service was actually alive on the host.
#
# This script runs from a systemd timer. It reads the liveness of the
# `actions.runner.*` service and publishes it as a CloudWatch custom metric so a
# stopped service surfaces as an alarm. Critically, the alarm on this metric
# treats missing data as breaching: a hung host can no longer run this script, so
# the absence of the heartbeat is itself the signal that the host has frozen.
#
# It deliberately does NOT poll the GitHub API or hold any GitHub token: runner
# online/offline status on GitHub is a separate signal with a separate
# credential risk (see the preflight note). Logging is low-cardinality on
# purpose - runner name, instance id, service state, publish result only. It
# never dumps journald, scrapes process environments, or logs secrets.
# ==============================================================================
set -euo pipefail

NAMESPACE="Shifter/RunnerHealth"

# Per-runner dimension. CloudWatch metrics are account/region scoped, so each
# runner stamps its own RunnerName (written to the EnvironmentFile by the
# instance user_data) to keep the per-runner alarm series from colliding.
RUNNER_NAME="${RUNNER_HEALTH_NAME:-unknown}"

# The installed Actions runner registers a systemd unit named
# `actions.runner.<org-or-repo>.<runner-name>.service`. Match the family rather
# than a specific name so this works regardless of the registered scope.
RUNNER_SERVICE_GLOB="actions.runner.*"

# Region + instance id from IMDSv2; no hard-coded environment-specific values.
TOKEN="$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)"
imds() {
  curl -sS -H "X-aws-ec2-metadata-token: ${TOKEN}" \
    "http://169.254.169.254/latest/meta-data/$1" 2>/dev/null || true
}
REGION="$(imds placement/region)"
INSTANCE_ID="$(imds instance-id)"
# us-east-2 is the project-wide region (see CLAUDE.md); fallback only if IMDS is
# unreachable, never an env-specific override.
REGION="${REGION:-us-east-2}"

# `systemctl is-active <glob>` reports the aggregate state of every matching
# unit. "active" means at least one runner service is up; anything else
# (inactive, failed, or no matching unit) is treated as not-active.
if systemctl is-active --quiet "${RUNNER_SERVICE_GLOB}"; then
  active=1
  state="active"
else
  active=0
  state="inactive"
fi

if aws cloudwatch put-metric-data \
  --region "${REGION}" \
  --namespace "${NAMESPACE}" \
  --metric-name "RunnerServiceActive" \
  --value "${active}" \
  --unit Count \
  --dimensions "RunnerName=${RUNNER_NAME}" >/dev/null 2>&1; then
  publish="ok"
else
  publish="failed"
fi

echo "runner-health: runner=${RUNNER_NAME} instance=${INSTANCE_ID} service=${state} active=${active} publish=${publish}"
