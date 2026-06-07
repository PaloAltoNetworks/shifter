#!/bin/bash
set -euo pipefail

# ==============================================================================
# Shifter Platform - EC2 Bootstrap Script
# ==============================================================================
# This script runs on first boot via cloud-init (user_data).
# It installs Docker, reads config from Parameter Store, deploys containers,
# and completes the ASG lifecycle hook (if applicable).
# ==============================================================================

# Configuration from Terraform template
AWS_REGION="${aws_region}"
ECR_REPOSITORY_URL="${ecr_repository_url}"
LOG_GROUP_NAME="${log_group_name}"
PS_PREFIX="${ssm_parameter_store_prefix}"
LIFECYCLE_HOOK_NAME="${lifecycle_hook_name}"

# Get instance ID from IMDS
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)

# Get ASG name from instance tags (if in ASG)
ASG_NAME=""
if [[ -n "$LIFECYCLE_HOOK_NAME" ]]; then
  ASG_NAME=$(aws autoscaling describe-auto-scaling-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'AutoScalingInstances[0].AutoScalingGroupName' \
    --output text \
    --region "$AWS_REGION" 2>/dev/null || echo "")
fi

echo "=========================================="
echo "Starting Shifter Platform bootstrap"
echo "Instance: $INSTANCE_ID"
echo "Region: $AWS_REGION"
echo "=========================================="

# ------------------------------------------------------------------------------
# Function: Complete lifecycle action
# ------------------------------------------------------------------------------
complete_lifecycle_action() {
  local result=$1
  if [[ -n "$LIFECYCLE_HOOK_NAME" ]] && [[ -n "$ASG_NAME" ]]; then
    echo "Completing lifecycle action with result: $result"
    aws autoscaling complete-lifecycle-action \
      --lifecycle-hook-name "$LIFECYCLE_HOOK_NAME" \
      --auto-scaling-group-name "$ASG_NAME" \
      --instance-id "$INSTANCE_ID" \
      --lifecycle-action-result "$result" \
      --region "$AWS_REGION" || echo "Warning: Failed to complete lifecycle action"
  fi
  return 0
}

# Trap errors and abandon lifecycle on failure
trap 'echo "Bootstrap failed!"; complete_lifecycle_action ABANDON; exit 1' ERR

# ------------------------------------------------------------------------------
# Install Docker
# ------------------------------------------------------------------------------
echo "Installing Docker..."
install_docker() {
  local attempt
  local delay

  for attempt in 1 2 3 4 5; do
    if dnf makecache --refresh && dnf install -y docker amazon-ecr-credential-helper; then
      return 0
    fi

    delay=$((attempt * 20))
    echo "Docker install attempt $attempt failed; retrying in $delay seconds..."
    sleep "$delay"
  done

  echo "Docker install failed after 5 attempts."
  return 1
}

install_docker
systemctl enable docker
systemctl start docker

# Add ec2-user to docker group
usermod -aG docker ec2-user

# Configure Docker daemon to use awslogs driver by default
mkdir -p /etc/docker
cat <<EOF > /etc/docker/daemon.json
{
  "log-driver": "awslogs",
  "log-opts": {
    "awslogs-region": "$AWS_REGION",
    "awslogs-group": "$LOG_GROUP_NAME",
    "awslogs-create-group": "false"
  }
}
EOF

# Restart Docker to apply logging config
systemctl restart docker

# Configure Docker to use ECR credential helper
ECR_REGISTRY=$(echo "$ECR_REPOSITORY_URL" | cut -d'/' -f1)

mkdir -p /root/.docker /home/ec2-user/.docker
cat <<EOF > /root/.docker/config.json
{
  "credHelpers": {
    "$ECR_REGISTRY": "ecr-login"
  }
}
EOF

cp /root/.docker/config.json /home/ec2-user/.docker/config.json
chown -R ec2-user:ec2-user /home/ec2-user/.docker

echo "Docker installed and configured."

# ------------------------------------------------------------------------------
# Read configuration from Parameter Store
# ------------------------------------------------------------------------------
if [[ -z "$PS_PREFIX" ]]; then
  echo "No Parameter Store prefix configured. Skipping container deployment."
  echo "Bootstrap complete (Docker only)."
  exit 0
fi

echo "Reading configuration from Parameter Store..."

get_param() {
  aws ssm get-parameter --name "$1" --with-decryption --query 'Parameter.Value' --output text --region "$AWS_REGION"
  return 0
}

validate_bootstrap_email_list() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" && ! "$value" =~ ^[A-Za-z0-9._%+@,-]+$ ]]; then
    echo "Invalid $name: expected a comma-separated email list"
    exit 1
  fi
}

IMAGE_TAG=$(get_param "$PS_PREFIX/image-tag")
ECR_REGISTRY=$(get_param "$PS_PREFIX/ecr-registry")
ECR_REPOSITORY=$(get_param "$PS_PREFIX/ecr-repository")
DOMAIN_NAME=$(get_param "$PS_PREFIX/domain-name")
S3_BUCKET=$(get_param "$PS_PREFIX/s3-bucket")
DB_SECRET_ARN=$(get_param "$PS_PREFIX/db-secret-arn")
APP_SECRET_ARN=$(get_param "$PS_PREFIX/app-secret-arn")
COGNITO_SECRET_ARN=$(get_param "$PS_PREFIX/cognito-secret-arn")
ENGINE_ECS_CLUSTER_ARN=$(get_param "$PS_PREFIX/engine-ecs-cluster-arn")
ENGINE_TASK_DEFINITION_ARN=$(get_param "$PS_PREFIX/engine-task-definition-arn")
ENGINE_ECS_SECURITY_GROUP_ID=$(get_param "$PS_PREFIX/engine-ecs-security-group-id")
ENGINE_PRIVATE_SUBNET_IDS=$(get_param "$PS_PREFIX/engine-private-subnet-ids")
SQS_CMS_URL=$(get_param "$PS_PREFIX/sqs-cms-url")
SQS_ENGINE_URL=$(get_param "$PS_PREFIX/sqs-engine-url")
SQS_MC_URL=$(get_param "$PS_PREFIX/sqs-mc-url")
REDIS_ENDPOINT=$(get_param "$PS_PREFIX/redis-endpoint" || echo "")
CHANNEL_LAYER_BACKEND=$(get_param "$PS_PREFIX/channel-layer-backend" 2>/dev/null || echo "")
GUACAMOLE_SECRET_ARN=$(get_param "$PS_PREFIX/guacamole-secret-arn" 2>/dev/null || echo "")
DC_DOMAIN_PASSWORD_SECRET_ARN=$(get_param "$PS_PREFIX/dc-domain-password-secret-arn" 2>/dev/null || echo "")
GUACAMOLE_BASE_URL=$(get_param "$PS_PREFIX/guacamole-base-url" 2>/dev/null || echo "")
GUACAMOLE_API_BASE_URL=$(get_param "$PS_PREFIX/guacamole-api-base-url" 2>/dev/null || echo "")
DB_HOST_OVERRIDE=$(get_param "$PS_PREFIX/db-host-override" 2>/dev/null || echo "")
EMAIL_BACKEND=$(get_param "$PS_PREFIX/email-backend")
CTF_FROM_EMAIL=$(get_param "$PS_PREFIX/ctf-from-email")
CTFD_PLATFORM_URL=$(get_param "$PS_PREFIX/ctfd-platform-url" 2>/dev/null || echo "")
PLATFORM_BOOTSTRAP_STAFF_EMAILS=$(get_param "$PS_PREFIX/platform-bootstrap-staff-emails" 2>/dev/null || echo "")
PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=$(get_param "$PS_PREFIX/platform-bootstrap-superuser-emails" 2>/dev/null || echo "")
validate_bootstrap_email_list "PLATFORM_BOOTSTRAP_STAFF_EMAILS" "$PLATFORM_BOOTSTRAP_STAFF_EMAILS"
validate_bootstrap_email_list "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS" "$PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS"

IMAGE="$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG"
echo "Deploying image: $IMAGE"

# ------------------------------------------------------------------------------
# Build container environment variables
# ------------------------------------------------------------------------------
COMMON_ENV="-e AWS_REGION=$AWS_REGION"
COMMON_ENV="$COMMON_ENV -e AWS_S3_BUCKET_NAME=$S3_BUCKET"
COMMON_ENV="$COMMON_ENV -e DB_SECRET_ARN=$DB_SECRET_ARN"
COMMON_ENV="$COMMON_ENV -e APP_SECRET_ARN=$APP_SECRET_ARN"
COMMON_ENV="$COMMON_ENV -e COGNITO_SECRET_ARN=$COGNITO_SECRET_ARN"
COMMON_ENV="$COMMON_ENV -e DJANGO_ALLOWED_HOSTS=$DOMAIN_NAME,localhost,127.0.0.1"
COMMON_ENV="$COMMON_ENV -e DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN_NAME"
COMMON_ENV="$COMMON_ENV -e SITE_URL=https://$DOMAIN_NAME"
COMMON_ENV="$COMMON_ENV -e ENGINE_ECS_CLUSTER_ARN=$ENGINE_ECS_CLUSTER_ARN"
COMMON_ENV="$COMMON_ENV -e ENGINE_TASK_DEFINITION_ARN=$ENGINE_TASK_DEFINITION_ARN"
COMMON_ENV="$COMMON_ENV -e ENGINE_ECS_SECURITY_GROUP_ID=$ENGINE_ECS_SECURITY_GROUP_ID"
COMMON_ENV="$COMMON_ENV -e ENGINE_PRIVATE_SUBNET_IDS=$ENGINE_PRIVATE_SUBNET_IDS"
COMMON_ENV="$COMMON_ENV -e SQS_CMS_URL=$SQS_CMS_URL"
COMMON_ENV="$COMMON_ENV -e SQS_ENGINE_URL=$SQS_ENGINE_URL"
COMMON_ENV="$COMMON_ENV -e SQS_MC_URL=$SQS_MC_URL"

# Add Redis if configured
if [[ -n "$REDIS_ENDPOINT" ]]; then
  COMMON_ENV="$COMMON_ENV -e REDIS_HOST=$REDIS_ENDPOINT"
fi

# Channel-layer backend posture (ADR-018, #849), decoupled from autoscaling.
# When unset (pre-ADR-018 environments) Django falls back to the
# REDIS_HOST-presence heuristic; when "redis" it fails closed without REDIS_HOST.
if [[ -n "$CHANNEL_LAYER_BACKEND" ]]; then
  COMMON_ENV="$COMMON_ENV -e CHANNEL_LAYER_BACKEND=$CHANNEL_LAYER_BACKEND"
fi

# Add Guacamole config if configured (for RDP integration)
if [[ -n "$GUACAMOLE_SECRET_ARN" ]]; then
  COMMON_ENV="$COMMON_ENV -e GUACAMOLE_SECRET_ARN=$GUACAMOLE_SECRET_ARN"
fi
if [[ -n "$GUACAMOLE_BASE_URL" ]]; then
  COMMON_ENV="$COMMON_ENV -e GUACAMOLE_BASE_URL=$GUACAMOLE_BASE_URL"
fi
if [[ -n "$GUACAMOLE_API_BASE_URL" ]]; then
  COMMON_ENV="$COMMON_ENV -e GUACAMOLE_API_BASE_URL=$GUACAMOLE_API_BASE_URL"
fi

# Pass the DC domain password secret ARN through; the container's
# entrypoint resolves it to the DC_DOMAIN_PASSWORD env var used by the
# portal's Windows-DC RDP credential lookup. The secret is Terraform-
# managed (created and seeded by the engine-provisioner module), so it
# always carries an AWSCURRENT value — same posture as the DB / app /
# Cognito secret ARNs above.
if [[ -n "$DC_DOMAIN_PASSWORD_SECRET_ARN" ]]; then
  COMMON_ENV="$COMMON_ENV -e DC_DOMAIN_PASSWORD_SECRET_ARN=$DC_DOMAIN_PASSWORD_SECRET_ARN"
fi

# Add DB host override if configured
if [[ -n "$DB_HOST_OVERRIDE" ]]; then
  COMMON_ENV="$COMMON_ENV -e DB_HOST=$DB_HOST_OVERRIDE"
fi

# Email configuration
COMMON_ENV="$COMMON_ENV -e EMAIL_BACKEND=$EMAIL_BACKEND"
COMMON_ENV="$COMMON_ENV -e CTF_FROM_EMAIL=$CTF_FROM_EMAIL"

if [[ -n "$PLATFORM_BOOTSTRAP_STAFF_EMAILS" ]]; then
  COMMON_ENV="$COMMON_ENV -e PLATFORM_BOOTSTRAP_STAFF_EMAILS=$PLATFORM_BOOTSTRAP_STAFF_EMAILS"
fi
if [[ -n "$PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS" ]]; then
  COMMON_ENV="$COMMON_ENV -e PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=$PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS"
fi

if [[ -n "$CTFD_PLATFORM_URL" ]]; then
  COMMON_ENV="$COMMON_ENV -e CTFD_PLATFORM_URL=$CTFD_PLATFORM_URL"
fi

# ------------------------------------------------------------------------------
# Deploy containers
# ------------------------------------------------------------------------------
echo "Pulling image..."
docker pull "$IMAGE"

echo "Stopping existing containers..."
docker stop portal worker-cms worker-engine worker-mc ctf-scheduler 2>/dev/null || true
docker rm portal worker-cms worker-engine worker-mc ctf-scheduler 2>/dev/null || true

echo "Starting portal..."
eval docker run -d --name portal --restart unless-stopped -p 8000:8000 $COMMON_ENV "$IMAGE"

echo "Starting workers..."
WORKER_HEALTH_BASE="--health-interval 30s --health-timeout 5s --health-start-period 90s --health-retries 2"
WORKER_CMS_HEALTH="--health-cmd='find /tmp/worker-cms-heartbeat -mmin -2 | grep -q .'"
WORKER_ENGINE_HEALTH="--health-cmd='find /tmp/worker-engine-heartbeat -mmin -2 | grep -q .'"
WORKER_MC_HEALTH="--health-cmd='find /tmp/worker-mc-heartbeat -mmin -2 | grep -q .'"
CTF_SCHEDULER_HEALTH="--health-cmd='find /tmp/ctf-scheduler-heartbeat -mmin -2 | grep -q .'"
eval docker run -d --name worker-cms --restart unless-stopped $WORKER_HEALTH_BASE "$WORKER_CMS_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_worker --queue cms
eval docker run -d --name worker-engine --restart unless-stopped $WORKER_HEALTH_BASE "$WORKER_ENGINE_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_worker --queue engine
eval docker run -d --name worker-mc --restart unless-stopped $WORKER_HEALTH_BASE "$WORKER_MC_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_worker --queue mc
eval docker run -d --name ctf-scheduler --restart unless-stopped $WORKER_HEALTH_BASE "$CTF_SCHEDULER_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_ctf_scheduler

echo "All containers started:"
docker ps

# ------------------------------------------------------------------------------
# Complete lifecycle action on success
# ------------------------------------------------------------------------------
complete_lifecycle_action CONTINUE

echo "=========================================="
echo "Shifter Platform bootstrap complete!"
echo "=========================================="
