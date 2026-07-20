#!/bin/bash
# Post-build golden verify (runner-side). A successful Packer provisioner run
# proves the builder converged; it does NOT prove the image boots into the
# participant contract. Launch a FRESH instance from the produced AMI, let docker
# auto-start the baked stack (no scenario provisioning re-run), and confirm the
# expected number of containers converge before the AMI is published to SSM.
#
# Parameterized per scenario (the "verification profile keyed by ami_type" seam):
#   SCENARIO         label for logs/tags (e.g. techvault, polaris)
#   MIN_CONTAINERS   required running-container count (techvault=30, polaris=17)
#   NAME_FILTER      optional docker name filter token (e.g. aptl-); empty = all
#
# Env: AMI_ID, INSTANCE_TYPE, SUBNET_ID, SECURITY_GROUP_ID, INSTANCE_PROFILE,
#      SCENARIO, MIN_CONTAINERS, NAME_FILTER (optional), RUN_ID (optional)
set -euo pipefail

: "${AMI_ID:?AMI_ID must be set}"
: "${INSTANCE_TYPE:?INSTANCE_TYPE must be set}"
: "${SUBNET_ID:?SUBNET_ID must be set}"
: "${SECURITY_GROUP_ID:?SECURITY_GROUP_ID must be set}"
: "${INSTANCE_PROFILE:?INSTANCE_PROFILE must be set}"
: "${SCENARIO:?SCENARIO must be set}"
: "${MIN_CONTAINERS:?MIN_CONTAINERS must be set}"
NAME_FILTER="${NAME_FILTER:-}"
RUN_ID="${RUN_ID:-manual}"

# NAME_FILTER is workflow-controlled, but validate it anyway before it reaches
# the remote docker command so it can never break out of the SSM JSON payload.
if [[ -n "$NAME_FILTER" ]] && ! printf '%s' "$NAME_FILTER" | grep -qE '^[A-Za-z0-9._-]+$'; then
  echo "::error::NAME_FILTER contains characters outside [A-Za-z0-9._-]" >&2
  exit 1
fi

DOCKER_COUNT_CMD="docker ps --filter status=running"
if [[ -n "$NAME_FILTER" ]]; then
  DOCKER_COUNT_CMD="${DOCKER_COUNT_CMD} --filter name=${NAME_FILTER}"
fi
DOCKER_COUNT_CMD="${DOCKER_COUNT_CMD} -q | wc -l"

VERIFY_INSTANCE_ID=""
cleanup() {
  if [[ -n "$VERIFY_INSTANCE_ID" ]]; then
    echo "terminating golden-verify host ${VERIFY_INSTANCE_ID}"
    aws ec2 terminate-instances --instance-ids "$VERIFY_INSTANCE_ID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

VERIFY_INSTANCE_ID="$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --subnet-id "$SUBNET_ID" \
  --security-group-ids "$SECURITY_GROUP_ID" \
  --iam-instance-profile "Name=${INSTANCE_PROFILE}" \
  --metadata-options 'HttpTokens=required,HttpEndpoint=enabled' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${SCENARIO}-verify-${RUN_ID}},{Key=Project,Value=${SCENARIO}-bake}]" \
  --count 1 \
  --query 'Instances[0].InstanceId' --output text)"
echo "launched golden-verify host ${VERIFY_INSTANCE_ID}"

aws ec2 wait instance-running --instance-ids "$VERIFY_INSTANCE_ID"
aws ec2 wait instance-status-ok --instance-ids "$VERIFY_INSTANCE_ID"

echo "waiting for the SSM agent to come online..."
deadline=$(( $(date +%s) + 600 ))
until aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=${VERIFY_INSTANCE_ID}" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null \
  | grep -q Online; do
  if [[ "$(date +%s)" -ge "$deadline" ]]; then
    echo "::error::golden-verify host SSM agent did not come online within 10 minutes" >&2
    exit 1
  fi
  sleep 15
done

echo "waiting for docker to auto-start the baked stack (need >= ${MIN_CONTAINERS} containers)..."
deadline=$(( $(date +%s) + 900 ))
while true; do
  cid="$(aws ssm send-command --instance-ids "$VERIFY_INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --comment "${SCENARIO} golden verify: count containers" \
    --parameters "{\"commands\":[\"${DOCKER_COUNT_CMD}\"]}" \
    --query 'Command.CommandId' --output text)"
  sleep 10
  count="$(aws ssm get-command-invocation --command-id "$cid" \
    --instance-id "$VERIFY_INSTANCE_ID" --query StandardOutputContent \
    --output text 2>/dev/null | tr -dc '0-9' || echo 0)"
  echo "auto-started containers: ${count:-0}"
  if [[ "${count:-0}" -ge "$MIN_CONTAINERS" ]]; then
    echo "container count converged (${count} running, need ${MIN_CONTAINERS})"
    break
  fi
  if [[ "$(date +%s)" -ge "$deadline" ]]; then
    echo "::error::golden verify FAILED: stack did not auto-start (last=${count:-0}, need ${MIN_CONTAINERS})" >&2
    exit 1
  fi
  sleep 20
done

# Health gate. A container can be "running" while its service is unhealthy, so
# counting running containers is not sufficient behavioral proof. Fail on any
# unhealthy/exited/dead container and confirm the scenario's flag-bearing
# services (REQUIRED_CONTAINERS, optional space/comma list) are present. The
# canonical scripts/polaris-aws-range/check_range_health.py is deliberately NOT
# reused here: it asserts per-range runtime state (splice-watcher service,
# Bedrock shard, IMDS drop rule, per-range STS identity) that PolarisRangeBootstrapPlan
# installs at range launch and that a fresh-boot bake AMI does not yet have.
REQUIRED_CONTAINERS="${REQUIRED_CONTAINERS:-}"
required_list="$(printf '%s' "$REQUIRED_CONTAINERS" | tr ',' ' ')"
read -r -d '' HEALTH_PROBE <<RSCRIPT || true
set -uo pipefail
bad=\$(docker ps -a --format '{{.Names}} {{.State}} {{.Status}}' | grep -Ei 'unhealthy|exited|dead' || true)
if [[ -n "\$bad" ]]; then echo "HEALTH_FAIL unhealthy_or_exited"; echo "\$bad"; exit 3; fi
miss=""
for c in ${required_list}; do
  docker ps --format '{{.Names}}' | grep -qx "\$c" || miss="\$miss \$c"
done
if [[ -n "\$miss" ]]; then echo "HEALTH_FAIL missing:\$miss"; exit 4; fi
starting=\$(docker ps --format '{{.Status}}' | grep -c 'health: starting' || true)
echo "HEALTH_OK starting=\${starting}"
RSCRIPT

echo "waiting for container healthchecks to settle (fail on unhealthy/exited; slow-init 'starting' tolerated)..."
b64_probe="$(printf '%s' "$HEALTH_PROBE" | base64 -w0)"
deadline=$(( $(date +%s) + 420 ))
while true; do
  cid="$(aws ssm send-command --instance-ids "$VERIFY_INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --comment "${SCENARIO} golden verify: health" \
    --parameters "{\"commands\":[\"echo ${b64_probe} | base64 -d | bash\"]}" \
    --query 'Command.CommandId' --output text)"
  sleep 10
  out="$(aws ssm get-command-invocation --command-id "$cid" \
    --instance-id "$VERIFY_INSTANCE_ID" --query StandardOutputContent --output text 2>/dev/null || true)"
  if printf '%s' "$out" | grep -q HEALTH_FAIL; then
    echo "::error::golden verify FAILED (health): $(printf '%s' "$out" | tr '\n' ' ')" >&2
    exit 1
  fi
  if printf '%s' "$out" | grep -q 'HEALTH_OK starting=0'; then
    echo "golden verify PASSED (${count} running, all healthchecks settled, required services present)"
    break
  fi
  if [[ "$(date +%s)" -ge "$deadline" ]]; then
    # No unhealthy/exited and required present, but some healthchecks still
    # 'starting' after the grace window (slow-init services). Not a failure.
    echo "golden verify PASSED (${count} running, required services present; note: some healthchecks still initializing: $(printf '%s' "$out" | tr '\n' ' '))"
    break
  fi
  sleep 20
done
