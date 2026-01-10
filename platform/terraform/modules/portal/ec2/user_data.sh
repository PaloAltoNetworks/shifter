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
if [ -n "$LIFECYCLE_HOOK_NAME" ]; then
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
  if [ -n "$LIFECYCLE_HOOK_NAME" ] && [ -n "$ASG_NAME" ]; then
    echo "Completing lifecycle action with result: $result"
    aws autoscaling complete-lifecycle-action \
      --lifecycle-hook-name "$LIFECYCLE_HOOK_NAME" \
      --auto-scaling-group-name "$ASG_NAME" \
      --instance-id "$INSTANCE_ID" \
      --lifecycle-action-result "$result" \
      --region "$AWS_REGION" || echo "Warning: Failed to complete lifecycle action"
  fi
}

# Trap errors and abandon lifecycle on failure
trap 'echo "Bootstrap failed!"; complete_lifecycle_action ABANDON; exit 1' ERR

# ------------------------------------------------------------------------------
# Install Docker
# ------------------------------------------------------------------------------
echo "Installing Docker..."
dnf install -y docker amazon-ecr-credential-helper
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
if [ -z "$PS_PREFIX" ]; then
  echo "No Parameter Store prefix configured. Skipping container deployment."
  echo "Bootstrap complete (Docker only)."
  exit 0
fi

echo "Reading configuration from Parameter Store..."

get_param() {
  aws ssm get-parameter --name "$1" --query 'Parameter.Value' --output text --region "$AWS_REGION"
}

IMAGE_TAG=$(get_param "$PS_PREFIX/image-tag")
ECR_REGISTRY=$(get_param "$PS_PREFIX/ecr-registry")
ECR_REPOSITORY=$(get_param "$PS_PREFIX/ecr-repository")
DOMAIN_NAME=$(get_param "$PS_PREFIX/domain-name")
S3_BUCKET=$(get_param "$PS_PREFIX/s3-bucket")
DB_SECRET_ARN=$(get_param "$PS_PREFIX/db-secret-arn")
APP_SECRET_ARN=$(get_param "$PS_PREFIX/app-secret-arn")
COGNITO_SECRET_ARN=$(get_param "$PS_PREFIX/cognito-secret-arn")
PULUMI_ECS_CLUSTER_ARN=$(get_param "$PS_PREFIX/pulumi-ecs-cluster-arn")
PULUMI_TASK_DEFINITION_ARN=$(get_param "$PS_PREFIX/pulumi-task-definition-arn")
PULUMI_ECS_SECURITY_GROUP_ID=$(get_param "$PS_PREFIX/pulumi-ecs-security-group-id")
PULUMI_PRIVATE_SUBNET_IDS=$(get_param "$PS_PREFIX/pulumi-private-subnet-ids")
SQS_CMS_URL=$(get_param "$PS_PREFIX/sqs-cms-url")
SQS_ENGINE_URL=$(get_param "$PS_PREFIX/sqs-engine-url")
SQS_MC_URL=$(get_param "$PS_PREFIX/sqs-mc-url")
REDIS_ENDPOINT=$(get_param "$PS_PREFIX/redis-endpoint" || echo "")

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
COMMON_ENV="$COMMON_ENV -e DJANGO_ALLOWED_HOSTS=$DOMAIN_NAME"
COMMON_ENV="$COMMON_ENV -e DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN_NAME"
COMMON_ENV="$COMMON_ENV -e SITE_URL=https://$DOMAIN_NAME"
COMMON_ENV="$COMMON_ENV -e PULUMI_ECS_CLUSTER_ARN=$PULUMI_ECS_CLUSTER_ARN"
COMMON_ENV="$COMMON_ENV -e PULUMI_TASK_DEFINITION_ARN=$PULUMI_TASK_DEFINITION_ARN"
COMMON_ENV="$COMMON_ENV -e PULUMI_ECS_SECURITY_GROUP_ID=$PULUMI_ECS_SECURITY_GROUP_ID"
COMMON_ENV="$COMMON_ENV -e PULUMI_PRIVATE_SUBNET_IDS=$PULUMI_PRIVATE_SUBNET_IDS"
COMMON_ENV="$COMMON_ENV -e SQS_CMS_URL=$SQS_CMS_URL"
COMMON_ENV="$COMMON_ENV -e SQS_ENGINE_URL=$SQS_ENGINE_URL"
COMMON_ENV="$COMMON_ENV -e SQS_MC_URL=$SQS_MC_URL"

# Add Redis if configured
if [ -n "$REDIS_ENDPOINT" ]; then
  COMMON_ENV="$COMMON_ENV -e REDIS_HOST=$REDIS_ENDPOINT"
fi

# ------------------------------------------------------------------------------
# Deploy containers
# ------------------------------------------------------------------------------
echo "Pulling image..."
docker pull "$IMAGE"

echo "Stopping existing containers..."
docker stop portal worker-cms worker-engine worker-mc 2>/dev/null || true
docker rm portal worker-cms worker-engine worker-mc 2>/dev/null || true

echo "Starting portal..."
eval docker run -d --name portal --restart unless-stopped -p 8000:8000 $COMMON_ENV "$IMAGE"

echo "Starting workers..."
eval docker run -d --name worker-cms --restart unless-stopped $COMMON_ENV "$IMAGE" python manage.py run_worker --queue cms
eval docker run -d --name worker-engine --restart unless-stopped $COMMON_ENV "$IMAGE" python manage.py run_worker --queue engine
eval docker run -d --name worker-mc --restart unless-stopped $COMMON_ENV "$IMAGE" python manage.py run_worker --queue mc

echo "All containers started:"
docker ps

# ------------------------------------------------------------------------------
# Complete lifecycle action on success
# ------------------------------------------------------------------------------
complete_lifecycle_action CONTINUE

echo "=========================================="
echo "Shifter Platform bootstrap complete!"
echo "=========================================="
