#!/usr/bin/env bash
# ==============================================================================
# Shifter worker-container health supervisor (issue #953)
# ==============================================================================
# Docker marks the worker/scheduler containers `unhealthy` via their heartbeat
# health-cmds, but `--restart unless-stopped` only acts on process exit, not on
# health status, and nothing emits that status to CloudWatch. A wedged worker
# (alive but not heartbeating, e.g. SIGSTOP) therefore stays unhealthy and
# invisible indefinitely.
#
# This script runs from a systemd timer. For each monitored container it reads
# the Docker health status, restarts the ones that are unhealthy or missing, and
# emits CloudWatch metrics so the failure surfaces as a restart AND an alarm
# instead of a silent stall. It deliberately never touches the `portal`
# container — web health is a separate concern (ALB / portal /health).
#
# Logging is intentionally low-cardinality: container name, instance id, health
# state, and restart result only. It never logs container env, `docker inspect`
# output, queue URLs, or secret values.
# ==============================================================================
set -euo pipefail

# Extensibility seam: the monitored set, metric namespace, and restart grace are
# named here so adding a worker is a one-line edit, not a new code path. The set
# is the worker/scheduler containers only — never `portal`.
MONITORED=(worker-cms worker-engine worker-mc ctf-scheduler)
NAMESPACE="Shifter/WorkerHealth"

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

# Per-environment dimension. CloudWatch metrics are account/region scoped, so
# without this dev and prod (same account/region) would share one metric series
# and cross-trip each other's alarm. WH_NAME_PREFIX is supplied by the systemd
# EnvironmentFile that each deploy path writes (e.g. "dev-portal").
NAME_PREFIX="${WH_NAME_PREFIX:-unknown}"

put_metric() {
  # $1 metric name, $2 value, $3 container name (dimension)
  aws cloudwatch put-metric-data \
    --region "${REGION}" \
    --namespace "${NAMESPACE}" \
    --metric-name "$1" \
    --value "$2" \
    --unit Count \
    --dimensions "NamePrefix=${NAME_PREFIX}" "ContainerName=$3" >/dev/null 2>&1 ||
    echo "worker-health: put-metric-data failed metric=$1 container=$3"
}

unhealthy_total=0
for container in "${MONITORED[@]}"; do
  status="$(docker inspect \
    -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
    "${container}" 2>/dev/null || echo missing)"

  if [ "${status}" = "unhealthy" ] || [ "${status}" = "missing" ]; then
    unhealthy_total=$((unhealthy_total + 1))
    put_metric "Unhealthy" 1 "${container}"
    echo "worker-health: container=${container} instance=${INSTANCE_ID} state=${status} action=restart"
    if docker restart "${container}" >/dev/null 2>&1; then
      put_metric "Restarted" 1 "${container}"
      echo "worker-health: container=${container} instance=${INSTANCE_ID} restart=ok"
    else
      echo "worker-health: container=${container} instance=${INSTANCE_ID} restart=failed"
    fi
  else
    put_metric "Unhealthy" 0 "${container}"
  fi
done

# Aggregate metric the CloudWatch alarm watches (no per-container dimension, so a
# single alarm covers the whole worker set with low-cardinality data).
aws cloudwatch put-metric-data \
  --region "${REGION}" \
  --namespace "${NAMESPACE}" \
  --metric-name "UnhealthyWorkers" \
  --value "${unhealthy_total}" \
  --unit Count \
  --dimensions "NamePrefix=${NAME_PREFIX}" >/dev/null 2>&1 ||
  echo "worker-health: aggregate put-metric-data failed"

echo "worker-health: instance=${INSTANCE_ID} unhealthy_total=${unhealthy_total}"
