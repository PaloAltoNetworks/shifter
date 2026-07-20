#!/bin/bash
# Base-image fresh-boot validation gate (runner-side), issue #1633.
#
# A green Packer build proves the builder converged; it does NOT prove the AMI
# boots with a working resolver. This launches a FRESH instance from the exact
# built AMI in a runtime-equivalent range subnet (range instance profile, IMDSv2,
# no inbound) and gates publication of /shifter/ami/* on the guest:
#   1. registering with SSM on first boot - SSM registration REQUIRES resolving
#      the regional SSM endpoint, so a successful registration is the DNS proof;
#   2. resolving the regional SSM endpoint through the system resolver via Run
#      Command;
#   3. rebooting and doing both again - the durable DNS fix must survive a
#      reboot, not just a lucky first boot.
# Any failure or timeout exits non-zero so the caller leaves the previous
# known-good SSM pointer untouched.
#
# Env: AMI_ID, AMI_TYPE, INSTANCE_TYPE, SUBNET_ID, SECURITY_GROUP_ID,
#      INSTANCE_PROFILE, RUN_ID (optional)
set -euo pipefail

: "${AMI_ID:?AMI_ID must be set}"
: "${AMI_TYPE:?AMI_TYPE must be set}"
: "${INSTANCE_TYPE:?INSTANCE_TYPE must be set}"
: "${SUBNET_ID:?SUBNET_ID must be set}"
: "${SECURITY_GROUP_ID:?SECURITY_GROUP_ID must be set}"
: "${INSTANCE_PROFILE:?INSTANCE_PROFILE must be set}"
RUN_ID="${RUN_ID:-manual}"
# All Shifter AWS resources live in us-east-2.
PROBE_HOST="ssm.us-east-2.amazonaws.com"

case "$AMI_TYPE" in
  windows) OS_FAMILY="windows" ;;
  kali | ubuntu) OS_FAMILY="linux" ;;
  *)
    echo "::error::base-image-verify does not support ami_type '${AMI_TYPE}'" >&2
    exit 1
    ;;
esac

VERIFY_INSTANCE_ID=""
cleanup() {
  if [[ -n "$VERIFY_INSTANCE_ID" ]]; then
    echo "terminating base-image-verify host ${VERIFY_INSTANCE_ID}"
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
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=ami-verify-${AMI_TYPE}-${RUN_ID}},{Key=Project,Value=ami-verify}]" \
  --count 1 \
  --query 'Instances[0].InstanceId' --output text)"
echo "launched base-image-verify host ${VERIFY_INSTANCE_ID} (${OS_FAMILY})"

aws ec2 wait instance-running --instance-ids "$VERIFY_INSTANCE_ID"

wait_for_ssm_online() {
  local phase="$1"
  local deadline
  # Windows first boot (sysprep specialize + EC2Launch) is slower than Linux.
  deadline=$(( $(date +%s) + 900 ))
  echo "waiting for the SSM agent to come online (${phase})..."
  until aws ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=${VERIFY_INSTANCE_ID}" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null \
    | grep -q Online; do
    if [[ "$(date +%s)" -ge "$deadline" ]]; then
      echo "::error::${AMI_TYPE} AMI ${AMI_ID} did not register with SSM (${phase}); guest DNS is likely broken" >&2
      exit 1
    fi
    sleep 15
  done
  echo "SSM agent online (${phase})"
}

resolve_check() {
  local phase="$1"
  local doc cmd cid out deadline
  if [[ "$OS_FAMILY" == "windows" ]]; then
    doc="AWS-RunPowerShellScript"
    cmd="if (Resolve-DnsName -Name ${PROBE_HOST} -ErrorAction Stop) { Write-Output DNS_OK }"
  else
    doc="AWS-RunShellScript"
    cmd="getent ahosts ${PROBE_HOST} >/dev/null && echo DNS_OK"
  fi
  echo "resolving ${PROBE_HOST} through the guest system resolver (${phase})..."
  cid="$(aws ssm send-command --instance-ids "$VERIFY_INSTANCE_ID" \
    --document-name "$doc" \
    --comment "base-image DNS verify (${phase})" \
    --parameters "{\"commands\":[\"${cmd}\"]}" \
    --query 'Command.CommandId' --output text)"
  deadline=$(( $(date +%s) + 180 ))
  while true; do
    sleep 10
    out="$(aws ssm get-command-invocation --command-id "$cid" \
      --instance-id "$VERIFY_INSTANCE_ID" --query StandardOutputContent --output text 2>/dev/null || true)"
    if printf '%s' "$out" | grep -q DNS_OK; then
      echo "resolver OK (${phase})"
      return 0
    fi
    if [[ "$(date +%s)" -ge "$deadline" ]]; then
      echo "::error::${AMI_TYPE} AMI ${AMI_ID} could not resolve ${PROBE_HOST} (${phase})" >&2
      exit 1
    fi
  done
}

# Fresh boot.
wait_for_ssm_online "fresh boot"
resolve_check "fresh boot"

# Reboot: the durable fix must survive a reboot, not just the first boot.
echo "rebooting to confirm DNS determinism survives a reboot..."
aws ec2 reboot-instances --instance-ids "$VERIFY_INSTANCE_ID"
sleep 45
wait_for_ssm_online "after reboot"
resolve_check "after reboot"

echo "base-image verify PASSED for ${AMI_TYPE} AMI ${AMI_ID}"
