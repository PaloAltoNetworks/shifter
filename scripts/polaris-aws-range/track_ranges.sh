#!/bin/bash
# Live tracker for polaris range provisioning during the BSides Ottawa
# event. Run in a separate terminal:
#
#   ./scripts/polaris-aws-range/track_ranges.sh
#
# Or with a faster cadence:
#
#   INTERVAL=15 ./scripts/polaris-aws-range/track_ranges.sh
#
# Read-only: only lists EC2, ECS, and SSM param state. Does not mutate
# anything.
set -eu

PROFILE="${AWS_PROFILE:-panw-shifter-dev-workstation}"
REGION="${AWS_REGION:-us-east-2}"
INTERVAL="${INTERVAL:-30}"
CLUSTER="dev-portal-pulumi"

echo "tracker: profile=$PROFILE region=$REGION interval=${INTERVAL}s cluster=$CLUSTER"
echo "  (ctrl-c to stop)"
echo

# Resolve polaris AMI once (unlikely to change mid-event)
AMI=$(aws ssm get-parameter --name /shifter/ami/polaris-vm --profile "$PROFILE" --region "$REGION" --query Parameter.Value --output text)

while true; do
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    clear
    echo "=== polaris range tracker @ $ts (refresh ${INTERVAL}s) ==="
    echo

    # Provisioner tasks
    running=$(aws ecs list-tasks --cluster "$CLUSTER" --profile "$PROFILE" --region "$REGION" --desired-status RUNNING --output json 2>/dev/null \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["taskArns"]))')
    stopped_recent=$(aws ecs list-tasks --cluster "$CLUSTER" --profile "$PROFILE" --region "$REGION" --desired-status STOPPED --output json 2>/dev/null \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["taskArns"]))')
    echo "provisioner tasks:  running=$running   stopped(recent)=$stopped_recent"
    echo

    # Range instances
    # shellcheck disable=SC2016  # Backticks are JMESPath literals, not shell substitutions.
    aws ec2 describe-instances \
        --profile "$PROFILE" --region "$REGION" \
        --filters "Name=image-id,Values=$AMI" "Name=instance-state-name,Values=running,pending,stopping" \
        --query 'Reservations[].Instances[].[Tags[?Key==`shifter:range_id`].Value|[0],Tags[?Key==`shifter:user_id`].Value|[0],Tags[?Key==`Name`].Value|[0],State.Name,InstanceId,LaunchTime]' \
        --output text \
        | sort -k1,1n -k3,3 \
        | awk 'BEGIN{
            printf "%-8s %-8s %-6s %-10s %-22s %s\n","range","user","role","state","instance","launched"
            printf "%-8s %-8s %-6s %-10s %-22s %s\n","-----","----","----","-----","--------","--------"
          }
          {printf "%-8s %-8s %-6s %-10s %-22s %s\n",$1,$2,$3,$4,$5,$6}'

    # Stopped DC1 windows instances (per-range)
    echo
    echo "dc01 windows instances (per-range):"
    # shellcheck disable=SC2016  # Backticks are JMESPath literals, not shell substitutions.
    aws ec2 describe-instances \
        --profile "$PROFILE" --region "$REGION" \
        --filters "Name=tag:Name,Values=dc01" "Name=tag-key,Values=shifter:range_id" "Name=instance-state-name,Values=running,pending,stopping" \
        --query 'Reservations[].Instances[].[Tags[?Key==`shifter:range_id`].Value|[0],State.Name,InstanceId]' \
        --output text | sort -k1,1n | awk '{printf "  range=%s  state=%s  %s\n",$1,$2,$3}'

    sleep "$INTERVAL"
done
