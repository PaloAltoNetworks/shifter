#!/usr/bin/env bash
# Emergency range isolation: cut network access immediately.
# Usage:
#   ./scripts/isolate-range.sh <dev|prod> [range-id] [--confirm] [--detach-igw] [--deny-nacl]

set -u
set -o pipefail

usage() {
    cat <<'EOF'
Usage: ./scripts/isolate-range.sh <dev|prod> [range-id] [--confirm] [--detach-igw] [--deny-nacl]

Examples:
  ./scripts/isolate-range.sh dev
  ./scripts/isolate-range.sh dev range-abc123
  ./scripts/isolate-range.sh prod --confirm

Flags:
  --confirm     Required when environment is prod.
  --detach-igw  Also detach internet gateways from affected VPCs.
  --deny-nacl   Also force deny-all entries into affected network ACLs.
EOF
}

LOG_FILE="/tmp/isolate-range-$(date -u +%Y%m%dT%H%M%SZ).log"
AWS_REGION="${AWS_REGION:-us-east-2}"
ENVIRONMENT=""
RANGE_ID=""
CONFIRM=false
DETACH_IGW=false
DENY_NACL=false
FAILED_ACTIONS=0

log() {
    local message="$1"
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[$ts] ${message}" | tee -a "$LOG_FILE"
}

fail() {
    log "ERROR: $1"
    exit 1
}

run_aws_action() {
    local description="$1"
    shift

    log "ACTION: ${description}"
    if aws --no-cli-pager --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@" >>"$LOG_FILE" 2>&1; then
        log "OK: ${description}"
        return 0
    fi

    log "FAILED: ${description}"
    FAILED_ACTIONS=$((FAILED_ACTIONS + 1))
    return 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        dev|prod)
            if [[ -z "$ENVIRONMENT" ]]; then
                ENVIRONMENT="$1"
            elif [[ -z "$RANGE_ID" ]]; then
                RANGE_ID="$1"
            else
                fail "Unexpected positional argument: $1"
            fi
            shift
            ;;
        --confirm)
            CONFIRM=true
            shift
            ;;
        --detach-igw)
            DETACH_IGW=true
            shift
            ;;
        --deny-nacl)
            DENY_NACL=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            if [[ -z "$ENVIRONMENT" ]]; then
                fail "Environment must be dev or prod"
            elif [[ -z "$RANGE_ID" ]]; then
                RANGE_ID="$1"
                shift
            else
                fail "Unknown argument: $1"
            fi
            ;;
    esac
done

[[ -z "$ENVIRONMENT" ]] && fail "Environment is required (dev|prod)"
if [[ "$ENVIRONMENT" == "prod" && "$CONFIRM" != "true" ]]; then
    fail "prod isolation requires --confirm"
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$REPO_ROOT/.env" ]]; then
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
fi

if [[ "$ENVIRONMENT" == "dev" ]]; then
    AWS_PROFILE="${PANW_SHIFTER_DEV_PROFILE:?PANW_SHIFTER_DEV_PROFILE not set. Check .env file.}"
else
    AWS_PROFILE="${PANW_SHIFTER_PROD_PROFILE:?PANW_SHIFTER_PROD_PROFILE not set. Check .env file.}"
fi

COMMON_FILTERS=("Name=tag:shifter:environment,Values=${ENVIRONMENT}" "Name=tag-key,Values=shifter:range_id")
if [[ -n "$RANGE_ID" ]]; then
    COMMON_FILTERS+=("Name=tag:shifter:range_id,Values=${RANGE_ID}")
fi

log "Starting emergency isolation"
log "Environment: ${ENVIRONMENT}"
log "Range ID: ${RANGE_ID:-ALL}"
log "AWS Profile: ${AWS_PROFILE}"
log "Region: ${AWS_REGION}"
log "Options: detach_igw=${DETACH_IGW}, deny_nacl=${DENY_NACL}"
log "Audit log: ${LOG_FILE}"

read_ids() {
    tr '\t' '\n' | sed '/^[[:space:]]*$/d'
}

mapfile -t SECURITY_GROUP_IDS < <(
    aws --no-cli-pager --profile "$AWS_PROFILE" --region "$AWS_REGION" ec2 describe-security-groups \
        --filters "${COMMON_FILTERS[@]}" \
        --query 'SecurityGroups[].GroupId' \
        --output text 2>>"$LOG_FILE" | read_ids
)

if [[ "${#SECURITY_GROUP_IDS[@]}" -eq 0 ]]; then
    fail "No matching range security groups found"
fi

log "Security groups to isolate: ${#SECURITY_GROUP_IDS[@]}"

isolate_security_group() {
    local sg_id="$1"
    local ingress_text egress_text
    local ingress_rules=() egress_rules=()

    log "Isolating security group ${sg_id}"

    ingress_text="$(aws --no-cli-pager --profile "$AWS_PROFILE" --region "$AWS_REGION" ec2 describe-security-group-rules \
        --filters "Name=group-id,Values=${sg_id}" "Name=is-egress,Values=false" \
        --query 'SecurityGroupRules[].SecurityGroupRuleId' --output text 2>>"$LOG_FILE" || true)"
    if [[ -n "$ingress_text" && "$ingress_text" != "None" ]]; then
        read -r -a ingress_rules <<<"$ingress_text"
        run_aws_action "Revoke ingress rules on ${sg_id}" ec2 revoke-security-group-ingress --group-id "$sg_id" --security-group-rule-ids "${ingress_rules[@]}"
    else
        log "No ingress rules to revoke on ${sg_id}"
    fi

    egress_text="$(aws --no-cli-pager --profile "$AWS_PROFILE" --region "$AWS_REGION" ec2 describe-security-group-rules \
        --filters "Name=group-id,Values=${sg_id}" "Name=is-egress,Values=true" \
        --query 'SecurityGroupRules[].SecurityGroupRuleId' --output text 2>>"$LOG_FILE" || true)"
    if [[ -n "$egress_text" && "$egress_text" != "None" ]]; then
        read -r -a egress_rules <<<"$egress_text"
        run_aws_action "Revoke egress rules on ${sg_id}" ec2 revoke-security-group-egress --group-id "$sg_id" --security-group-rule-ids "${egress_rules[@]}"
    else
        log "No egress rules to revoke on ${sg_id}"
    fi
}

for sg_id in "${SECURITY_GROUP_IDS[@]}"; do
    isolate_security_group "$sg_id"
done

declare -A VPC_ID_SET=()
for sg_id in "${SECURITY_GROUP_IDS[@]}"; do
    vpc_id="$(aws --no-cli-pager --profile "$AWS_PROFILE" --region "$AWS_REGION" ec2 describe-security-groups \
        --group-ids "$sg_id" --query 'SecurityGroups[0].VpcId' --output text 2>>"$LOG_FILE" || true)"
    if [[ -n "$vpc_id" && "$vpc_id" != "None" ]]; then
        VPC_ID_SET["$vpc_id"]=1
    fi
done

if [[ "$DETACH_IGW" == "true" ]]; then
    for vpc_id in "${!VPC_ID_SET[@]}"; do
        mapfile -t igw_ids < <(
            aws --no-cli-pager --profile "$AWS_PROFILE" --region "$AWS_REGION" ec2 describe-internet-gateways \
                --filters "Name=attachment.vpc-id,Values=${vpc_id}" \
                --query 'InternetGateways[].InternetGatewayId' \
                --output text 2>>"$LOG_FILE" | read_ids
        )
        for igw_id in "${igw_ids[@]}"; do
            run_aws_action "Detach IGW ${igw_id} from ${vpc_id}" ec2 detach-internet-gateway --internet-gateway-id "$igw_id" --vpc-id "$vpc_id"
        done
    done
fi

if [[ "$DENY_NACL" == "true" ]]; then
    mapfile -t subnet_ids < <(
        aws --no-cli-pager --profile "$AWS_PROFILE" --region "$AWS_REGION" ec2 describe-subnets \
            --filters "${COMMON_FILTERS[@]}" \
            --query 'Subnets[].SubnetId' \
            --output text 2>>"$LOG_FILE" | read_ids
    )

    declare -A nacl_id_set=()
    for subnet_id in "${subnet_ids[@]}"; do
        nacl_id="$(aws --no-cli-pager --profile "$AWS_PROFILE" --region "$AWS_REGION" ec2 describe-network-acls \
            --filters "Name=association.subnet-id,Values=${subnet_id}" \
            --query 'NetworkAcls[0].NetworkAclId' \
            --output text 2>>"$LOG_FILE" || true)"
        if [[ -n "$nacl_id" && "$nacl_id" != "None" ]]; then
            nacl_id_set["$nacl_id"]=1
        fi
    done

    for nacl_id in "${!nacl_id_set[@]}"; do
        run_aws_action "NACL ${nacl_id} ingress deny-all IPv4" ec2 replace-network-acl-entry --network-acl-id "$nacl_id" --ingress --rule-number 1 --protocol -1 --rule-action deny --cidr-block 0.0.0.0/0
        run_aws_action "NACL ${nacl_id} egress deny-all IPv4" ec2 replace-network-acl-entry --network-acl-id "$nacl_id" --egress --rule-number 1 --protocol -1 --rule-action deny --cidr-block 0.0.0.0/0
        run_aws_action "NACL ${nacl_id} ingress deny-all IPv6" ec2 replace-network-acl-entry --network-acl-id "$nacl_id" --ingress --rule-number 2 --protocol -1 --rule-action deny --ipv6-cidr-block ::/0
        run_aws_action "NACL ${nacl_id} egress deny-all IPv6" ec2 replace-network-acl-entry --network-acl-id "$nacl_id" --egress --rule-number 2 --protocol -1 --rule-action deny --ipv6-cidr-block ::/0
    done
fi

if [[ "$FAILED_ACTIONS" -gt 0 ]]; then
    log "Isolation completed with ${FAILED_ACTIONS} failed action(s). See ${LOG_FILE}"
    exit 2
fi

log "Isolation completed successfully. See ${LOG_FILE}"
