#!/usr/bin/env bash
# Bulk register N POLARIS ranges into the portal CMS + engine DBs by
# running register_range.py once per range index with per-range env vars
# (Kali instance id, subnet id, CIDR, Kali private IP). Inputs come from
# `terraform output` when called with no args.
#
# Usage:
#
#   ./register_ranges_parallel.sh                      # all indices in state
#   ./register_ranges_parallel.sh 0 1 2                # explicit subset
#
# Environment:
#
#   POLARIS_EMAIL_PREFIX (default: polaris-smoke)
#   POLARIS_EMAIL_DOMAIN (default: example.com)
#   POLARIS_PORTAL_INSTANCE_ID
#     Defaults to the first running `dev-portal-ec2` instance found via
#     ec2 describe-instances; set explicitly to pin to a specific portal
#     VM if there are multiple behind the ALB.
#
# Emits JSON on stdout: one object per range with the new engine/cms
# range ids, the user email, and the kali instance id. Consumer can pipe
# this to jq to drive follow-up playwright / CTF invite flows.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-panw-shifter-dev-workstation}"
AWS_REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE AWS_REGION

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTER_PY="${SCRIPT_DIR}/register_range.py"

if [[ ! -f "$REGISTER_PY" ]]; then
    echo "missing $REGISTER_PY" >&2
    exit 1
fi

EMAIL_PREFIX="${POLARIS_EMAIL_PREFIX:-polaris-smoke}"
EMAIL_DOMAIN="${POLARIS_EMAIL_DOMAIN:-example.com}"

PORTAL_INSTANCE_ID="${POLARIS_PORTAL_INSTANCE_ID:-}"
if [[ -z "$PORTAL_INSTANCE_ID" ]]; then
    PORTAL_INSTANCE_ID="$(aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
        ec2 describe-instances \
        --filters "Name=tag:Name,Values=dev-portal-ec2" \
                  "Name=instance-state-name,Values=running" \
        --query 'Reservations[0].Instances[0].InstanceId' \
        --output text 2>/dev/null || true)"
fi
if [[ -z "$PORTAL_INSTANCE_ID" || "$PORTAL_INSTANCE_ID" == "None" ]]; then
    echo "could not find a running dev-portal-ec2 instance; set POLARIS_PORTAL_INSTANCE_ID" >&2
    exit 1
fi
echo "using portal instance: $PORTAL_INSTANCE_ID" >&2

# Pull per-range data from terraform output. Do this once up front so we
# never re-read state between invocations.
TF_OUT_FILE="$(mktemp /tmp/polaris_tf_output.XXXXXX.json)"
trap 'rm -f "$TF_OUT_FILE"' EXIT
terraform -chdir="$SCRIPT_DIR" output -json > "$TF_OUT_FILE"

# If no indices passed, take them from the terraform output.
if (( $# > 0 )); then
    INDICES=("$@")
else
    mapfile -t INDICES < <(python3 -c '
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
for k in d["range_indices"]["value"]:
    print(k)
' "$TF_OUT_FILE")
fi

if (( ${#INDICES[@]} == 0 )); then
    echo "no range indices to register" >&2
    exit 1
fi

# Pre-stage register_range.py content on the portal once (the same file
# works for every range; only env vars differ between invocations).
B64="$(base64 -w0 "$REGISTER_PY")"
STAGE_CMD="echo '${B64}' | base64 -d > /tmp/register_range.py"

STAGE_JSON="$(mktemp /tmp/polaris_stage.XXXXXX.json)"
python3 -c "
import json, sys
with open(sys.argv[1], 'w') as f:
    json.dump({'commands': [sys.argv[2]]}, f)
" "$STAGE_JSON" "$STAGE_CMD"

STAGE_ID="$(aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
    ssm send-command --instance-ids "$PORTAL_INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters "file://${STAGE_JSON}" \
    --timeout-seconds 60 \
    --query 'Command.CommandId' --output text)"

# Wait briefly for the staging command to finish.
for _ in $(seq 1 10); do
    status="$(aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
        ssm get-command-invocation \
        --command-id "$STAGE_ID" --instance-id "$PORTAL_INSTANCE_ID" \
        --query 'Status' --output text 2>/dev/null || echo Pending)"
    [[ "$status" == "Success" ]] && break
    sleep 2
done
rm -f "$STAGE_JSON"

register_one() {
    local idx="$1"
    local email="${EMAIL_PREFIX}-${idx}@${EMAIL_DOMAIN}"

    python3 - "$TF_OUT_FILE" "$idx" <<'PY' > /tmp/polaris_range_$$.env
import json, sys
with open(sys.argv[1]) as f:
    tf = json.load(f)
idx = sys.argv[2]
kali_id = tf["range_polaris_instance_ids"]["value"][idx]
kali_ip = tf["range_polaris_private_ips"]["value"][idx]
subnet_id = tf["range_subnet_ids"]["value"][idx]
subnet_cidr = tf["range_subnet_cidrs"]["value"][idx]
print(f"POLARIS_KALI_INSTANCE_ID={kali_id}")
print(f"POLARIS_KALI_PRIVATE_IP={kali_ip}")
print(f"POLARIS_SUBNET_ID={subnet_id}")
print(f"POLARIS_SUBNET_CIDR={subnet_cidr}")
PY
    # shellcheck disable=SC1090
    source /tmp/polaris_range_$$.env
    rm -f /tmp/polaris_range_$$.env

    local cmd
    cmd="docker exec -i "
    cmd+="-e POLARIS_USER_EMAIL=${email} "
    cmd+="-e POLARIS_RANGE_NAME=polaris-smoke-${idx} "
    cmd+="-e POLARIS_KALI_INSTANCE_ID=${POLARIS_KALI_INSTANCE_ID} "
    cmd+="-e POLARIS_KALI_PRIVATE_IP=${POLARIS_KALI_PRIVATE_IP} "
    cmd+="-e POLARIS_SUBNET_ID=${POLARIS_SUBNET_ID} "
    cmd+="-e POLARIS_SUBNET_CIDR=${POLARIS_SUBNET_CIDR} "
    cmd+="-e POLARIS_SUBNET_INDEX=$((4000 + idx)) "
    cmd+="portal python - < /tmp/register_range.py 2>&1"

    local params
    params="$(mktemp /tmp/polaris_reg.XXXXXX.json)"
    python3 -c "
import json, sys
with open(sys.argv[1], 'w') as f:
    json.dump({'commands': [sys.argv[2]]}, f)
" "$params" "$cmd"

    local reg_id
    reg_id="$(aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
        ssm send-command --instance-ids "$PORTAL_INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters "file://${params}" \
        --timeout-seconds 180 \
        --query 'Command.CommandId' --output text)"
    rm -f "$params"

    for _ in $(seq 1 60); do
        local status
        status="$(aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
            ssm get-command-invocation \
            --command-id "$reg_id" --instance-id "$PORTAL_INSTANCE_ID" \
            --query 'Status' --output text 2>/dev/null || echo Pending)"
        case "$status" in
            Success)
                local out
                out="$(aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
                    ssm get-command-invocation \
                    --command-id "$reg_id" --instance-id "$PORTAL_INSTANCE_ID" \
                    --query 'StandardOutputContent' --output text)"
                # The last JSON line holds {"attacker_uuid", "range_id"}.
                local json_line
                json_line="$(echo "$out" | grep -oE '^\{"attacker_uuid".*\}$' | tail -1)"
                if [[ -n "$json_line" ]]; then
                    python3 -c "
import json, sys
d = json.loads(sys.argv[1])
d['range_index'] = sys.argv[2]
d['participant_email'] = sys.argv[3]
print(json.dumps(d))
" "$json_line" "$idx" "$email"
                else
                    echo "{\"range_index\":\"$idx\",\"participant_email\":\"$email\",\"error\":\"no_json_line\"}" >&2
                fi
                return 0
                ;;
            Failed|Cancelled|TimedOut)
                echo "register_range $idx: $status" >&2
                aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
                    ssm get-command-invocation \
                    --command-id "$reg_id" --instance-id "$PORTAL_INSTANCE_ID" \
                    --query '[StandardOutputContent,StandardErrorContent]' \
                    --output text >&2
                return 1
                ;;
            *)
                sleep 3
                ;;
        esac
    done
    echo "register_range $idx: wall-clock timeout" >&2
    return 1
}

for idx in "${INDICES[@]}"; do
    echo "=== registering range ${idx} ===" >&2
    register_one "$idx"
done
