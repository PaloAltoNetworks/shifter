#!/bin/bash
set -euo pipefail

# Dev Workstation Manager
# Manages an EC2 instance in the dev account for Docker-based development.
#
# Usage:
#   ./scripts/dev-workstation.sh create    # First-time setup
#   ./scripts/dev-workstation.sh start     # Start stopped instance
#   ./scripts/dev-workstation.sh stop      # Stop instance (preserves data)
#   ./scripts/dev-workstation.sh ssh       # SSH into workstation (interactive)
#   ./scripts/dev-workstation.sh ssh CMD   # Run CMD on workstation
#   ./scripts/dev-workstation.sh sync      # Sync project files
#   ./scripts/dev-workstation.sh update-ip # Update security group with current IP
#   ./scripts/dev-workstation.sh status    # Show instance status and IP
#   ./scripts/dev-workstation.sh terminate # Destroy everything

AWS_PROFILE="panw-shifter-dev-workstation"
AWS_REGION="${AWS_REGION:-us-east-2}"
KEY_NAME="shifter-dev-workstation"
KEY_PATH="$HOME/.ssh/${KEY_NAME}.pem"
SG_NAME="shifter-dev-workstation"
INSTANCE_NAME="shifter-dev-workstation"
INSTANCE_TYPE="t3.large"
VOLUME_SIZE=50
STATE_FILE="$HOME/.shifter-dev-workstation"

aws_cmd() {
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"
}

save_state() {
    cat > "$STATE_FILE" <<EOF
INSTANCE_ID=$INSTANCE_ID
SG_ID=$SG_ID
EOF
}

load_state() {
    if [[ ! -f "$STATE_FILE" ]]; then
        echo "No workstation found. Run: $0 create"
        exit 1
    fi
    source "$STATE_FILE"
}

get_public_ip() {
    curl -s https://checkip.amazonaws.com
}

get_instance_ip() {
    aws_cmd ec2 describe-instances \
        --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].PublicIpAddress' \
        --output text
}

get_instance_state() {
    aws_cmd ec2 describe-instances \
        --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' \
        --output text
}

wait_for_ssh() {
    local ip=$1
    echo "Waiting for SSH..."
    for i in $(seq 1 30); do
        if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i "$KEY_PATH" ec2-user@"$ip" "echo ok" &>/dev/null; then
            echo "SSH ready."
            return 0
        fi
        sleep 5
    done
    echo "SSH timed out."
    return 1
}

cmd_create() {
    if [[ -f "$STATE_FILE" ]]; then
        echo "Workstation already exists. Use 'terminate' first to recreate."
        exit 1
    fi

    echo "Creating dev workstation..."

    # Key pair
    if [[ -f "$KEY_PATH" ]]; then
        echo "Key $KEY_PATH already exists, reusing."
        # Ensure it exists in AWS too
        if ! aws_cmd ec2 describe-key-pairs --key-names "$KEY_NAME" &>/dev/null; then
            echo "Key exists locally but not in AWS. Delete $KEY_PATH and re-run create."
            exit 1
        fi
    else
        echo "Creating key pair..."
        aws_cmd ec2 create-key-pair \
            --key-name "$KEY_NAME" \
            --query 'KeyMaterial' --output text > "$KEY_PATH"
        chmod 600 "$KEY_PATH"
    fi

    # Security group
    echo "Creating security group..."
    SG_ID=$(aws_cmd ec2 create-security-group \
        --group-name "$SG_NAME" \
        --description "Shifter dev workstation SSH access" \
        --query 'GroupId' --output text)

    MY_IP=$(get_public_ip)
    echo "Allowing SSH from $MY_IP..."
    aws_cmd ec2 authorize-security-group-ingress \
        --group-id "$SG_ID" \
        --protocol tcp --port 22 --cidr "${MY_IP}/32" > /dev/null

    # AMI - latest Amazon Linux 2023
    AMI_ID=$(aws_cmd ec2 describe-images \
        --owners amazon \
        --filters "Name=name,Values=al2023-ami-2023*-x86_64" "Name=state,Values=available" \
        --query 'sort_by(Images, &CreationDate)[-1].ImageId' --output text)
    echo "Using AMI: $AMI_ID"

    # Launch
    echo "Launching $INSTANCE_TYPE instance..."
    INSTANCE_ID=$(aws_cmd ec2 run-instances \
        --image-id "$AMI_ID" \
        --instance-type "$INSTANCE_TYPE" \
        --key-name "$KEY_NAME" \
        --security-group-ids "$SG_ID" \
        --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":${VOLUME_SIZE},\"VolumeType\":\"gp3\"}}]" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${INSTANCE_NAME}}]" \
        --user-data '#!/bin/bash
set -e
dnf update -y
dnf install -y docker git
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
touch /tmp/setup-complete
' \
        --query 'Instances[0].InstanceId' --output text)

    save_state
    echo "Instance: $INSTANCE_ID"

    echo "Waiting for instance to start..."
    aws_cmd ec2 wait instance-running --instance-ids "$INSTANCE_ID"

    IP=$(get_instance_ip)
    echo "Public IP: $IP"

    # Wait for user data
    echo "Waiting for Docker setup..."
    for i in $(seq 1 30); do
        if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i "$KEY_PATH" ec2-user@"$IP" "test -f /tmp/setup-complete" &>/dev/null; then
            echo "Setup complete."
            break
        fi
        sleep 10
    done

    # Initial sync
    cmd_sync

    echo ""
    echo "Workstation ready: ssh -i $KEY_PATH ec2-user@$IP"
}

cmd_start() {
    load_state
    STATE=$(get_instance_state)
    if [[ "$STATE" == "running" ]]; then
        echo "Already running at $(get_instance_ip)"
        return
    fi
    echo "Starting instance..."
    aws_cmd ec2 start-instances --instance-ids "$INSTANCE_ID" > /dev/null
    aws_cmd ec2 wait instance-running --instance-ids "$INSTANCE_ID"
    IP=$(get_instance_ip)
    echo "Started at $IP"

    # IP may have changed, update SG
    cmd_update_ip
    wait_for_ssh "$IP"
}

cmd_stop() {
    load_state
    echo "Stopping instance (data preserved)..."
    aws_cmd ec2 stop-instances --instance-ids "$INSTANCE_ID" > /dev/null
    echo "Stopped."
}

cmd_ssh() {
    load_state
    IP=$(get_instance_ip)
    if [[ $# -gt 0 ]]; then
        ssh -o StrictHostKeyChecking=no -i "$KEY_PATH" ec2-user@"$IP" "$@"
    else
        echo "Connecting to $IP..."
        ssh -o StrictHostKeyChecking=no -i "$KEY_PATH" ec2-user@"$IP"
    fi
}

cmd_sync() {
    load_state
    IP=$(get_instance_ip)

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
    REPO_DIR="$(dirname "$PROJECT_DIR")"

    RSYNC_EXCLUDES=(
        --exclude '.venv'
        --exclude '__pycache__'
        --exclude '*.pyc'
        --exclude 'node_modules'
        --exclude '.git'
        --exclude 'postgres_data'
    )
    RSYNC_SSH=(-e "ssh -o StrictHostKeyChecking=no -i $KEY_PATH")

    # Sync platform (shifter_platform/ -> ~/shifter/)
    echo "Syncing platform to workstation..."
    rsync -az --delete "${RSYNC_EXCLUDES[@]}" "${RSYNC_SSH[@]}" \
        "$PROJECT_DIR/" ec2-user@"$IP":~/shifter/

    # Sync engine dir (engine/ -> ~/engine/)
    # docker-compose.yml references ../engine/ for build contexts and volume mounts
    if [[ -d "$REPO_DIR/engine" ]]; then
        echo "Syncing engine to workstation..."
        rsync -az --delete "${RSYNC_EXCLUDES[@]}" "${RSYNC_SSH[@]}" \
            "$REPO_DIR/engine/" ec2-user@"$IP":~/engine/
    fi

    # Sync cyberscript shared library (cyberscript/ -> ~/shifter/cyberscript/)
    # Required for Docker image build (pip install /cyberscript)
    if [[ -d "$REPO_DIR/cyberscript" ]]; then
        echo "Syncing cyberscript to workstation..."
        rsync -az --delete "${RSYNC_EXCLUDES[@]}" "${RSYNC_SSH[@]}" \
            "$REPO_DIR/cyberscript/" ec2-user@"$IP":~/shifter/cyberscript/
    fi

    echo "Synced."
}

cmd_update_ip() {
    load_state
    MY_IP=$(get_public_ip)
    echo "Updating security group to allow $MY_IP..."

    # Remove all existing SSH rules
    EXISTING=$(aws_cmd ec2 describe-security-groups \
        --group-ids "$SG_ID" \
        --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`].IpRanges[].CidrIp' \
        --output text)

    for cidr in $EXISTING; do
        aws_cmd ec2 revoke-security-group-ingress \
            --group-id "$SG_ID" \
            --protocol tcp --port 22 --cidr "$cidr" > /dev/null 2>&1 || true
    done

    aws_cmd ec2 authorize-security-group-ingress \
        --group-id "$SG_ID" \
        --protocol tcp --port 22 --cidr "${MY_IP}/32" > /dev/null
    echo "Done. SSH allowed from $MY_IP only."
}

cmd_status() {
    load_state
    STATE=$(get_instance_state)
    echo "Instance: $INSTANCE_ID"
    echo "State:    $STATE"
    if [[ "$STATE" == "running" ]]; then
        echo "IP:       $(get_instance_ip)"
        echo "SSH:      ssh -i $KEY_PATH ec2-user@$(get_instance_ip)"
    fi
}

cmd_terminate() {
    load_state
    echo "This will TERMINATE the workstation and DELETE the security group."
    read -rp "Are you sure? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        echo "Aborted."
        exit 0
    fi

    echo "Terminating instance..."
    aws_cmd ec2 terminate-instances --instance-ids "$INSTANCE_ID" > /dev/null
    aws_cmd ec2 wait instance-terminated --instance-ids "$INSTANCE_ID"

    echo "Deleting security group..."
    aws_cmd ec2 delete-security-group --group-id "$SG_ID" 2>/dev/null || true

    rm -f "$STATE_FILE"
    echo "Terminated. Key pair retained at $KEY_PATH (delete manually if desired)."
}

case "${1:-}" in
    create)     cmd_create ;;
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    ssh)        shift; cmd_ssh "$@" ;;
    sync)       cmd_sync ;;
    update-ip)  cmd_update_ip ;;
    status)     cmd_status ;;
    terminate)  cmd_terminate ;;
    *)
        echo "Usage: $0 {create|start|stop|ssh|sync|update-ip|status|terminate}"
        exit 1
        ;;
esac
