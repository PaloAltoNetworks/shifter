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
DJANGO_ENVIRONMENT="${django_environment}"
ECR_REPOSITORY_URL="${ecr_repository_url}"
LOG_GROUP_NAME="${log_group_name}"
PS_PREFIX="${ssm_parameter_store_prefix}"
LIFECYCLE_HOOK_NAME="${lifecycle_hook_name}"

# Get instance ID from IMDS
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)

# ASG name is resolved lazily at lifecycle-completion time (see resolve_asg_name
# below), NOT once here: early-boot / warm-pool launches return empty from
# describe-auto-scaling-instances, and caching that empty value is what left
# instances stuck in Pending:Wait until the launch hook ABANDONed them (#1032).
ASG_NAME=""

# ASG-name discovery tuning. Non-secret constants; no per-environment variation
# is needed, so they stay in-script rather than becoming Terraform inputs.
ASG_DISCOVERY_ATTEMPTS=5
ASG_DISCOVERY_DELAY_SECONDS=6
IMDS_CURL_MAX_TIME=5

echo "=========================================="
echo "Starting Shifter Platform bootstrap"
echo "Instance: $INSTANCE_ID"
echo "Region: $AWS_REGION"
echo "=========================================="

# ------------------------------------------------------------------------------
# Function: Resolve the ASG name for this instance (bounded retry)
# ------------------------------------------------------------------------------
# Primary source is the IMDS instance tag aws:autoscaling:groupName: the launch
# template enables instance_metadata_tags, and the tag reflects ASG membership
# immediately (including warm-pool launches, where describe-auto-scaling-instances
# is briefly empty). The Auto Scaling API is the fallback. Discovery is retried
# because early boot can lag both sources. Echoes the resolved name, or nothing
# if it stays unresolved after all attempts.
resolve_asg_name() {
  local attempt=1
  local name=""

  while [[ "$attempt" -le "$ASG_DISCOVERY_ATTEMPTS" ]]; do
    # Primary: IMDS instance tag. Reuses the IMDSv2 token, bounded by --max-time,
    # no IMDSv1 fallback; -f makes a missing-tag 404 yield empty (not an error
    # body). The token is not logged.
    name=$(curl -f -s --max-time "$IMDS_CURL_MAX_TIME" \
      -H "X-aws-ec2-metadata-token: $TOKEN" \
      "http://169.254.169.254/latest/meta-data/tags/instance/aws:autoscaling:groupName" \
      2>/dev/null || echo "")
    if [[ -n "$name" ]]; then
      printf '%s' "$name"
      return 0
    fi

    # Fallback: Auto Scaling API. --output text prints "None" for an empty
    # result, so treat that as unresolved.
    name=$(aws autoscaling describe-auto-scaling-instances \
      --instance-ids "$INSTANCE_ID" \
      --query 'AutoScalingInstances[0].AutoScalingGroupName' \
      --output text \
      --region "$AWS_REGION" 2>/dev/null || echo "")
    if [[ -n "$name" && "$name" != "None" ]]; then
      printf '%s' "$name"
      return 0
    fi

    if [[ "$attempt" -lt "$ASG_DISCOVERY_ATTEMPTS" ]]; then
      sleep "$ASG_DISCOVERY_DELAY_SECONDS"
    fi
    attempt=$((attempt + 1))
  done

  return 0
}

# ------------------------------------------------------------------------------
# Function: Complete lifecycle action
# ------------------------------------------------------------------------------
# Returns non-zero when a configured launch hook cannot be completed, so callers
# can fail bootstrap loudly instead of leaving the instance stuck in
# Pending:Wait (#1032). A no-op (return 0) when no launch hook is configured
# (single-instance mode).
complete_lifecycle_action() {
  local result=$1

  if [[ -z "$LIFECYCLE_HOOK_NAME" ]]; then
    return 0
  fi

  # Resolve/refresh the ASG name at completion time; never trust an empty cache.
  if [[ -z "$ASG_NAME" ]]; then
    ASG_NAME=$(resolve_asg_name)
  fi

  if [[ -z "$ASG_NAME" ]]; then
    echo "ERROR: launch hook '$LIFECYCLE_HOOK_NAME' is configured but the ASG name could not be resolved for $INSTANCE_ID; cannot complete lifecycle action ($result)." >&2
    return 1
  fi

  echo "Completing lifecycle action with result: $result (asg=$ASG_NAME)"
  aws autoscaling complete-lifecycle-action \
    --lifecycle-hook-name "$LIFECYCLE_HOOK_NAME" \
    --auto-scaling-group-name "$ASG_NAME" \
    --instance-id "$INSTANCE_ID" \
    --lifecycle-action-result "$result" \
    --region "$AWS_REGION"
}

# Trap errors and abandon lifecycle on failure. Disarm the trap first so a
# best-effort ABANDON that itself fails cannot re-enter this handler, and never
# let the abandon attempt mask the non-zero exit.
on_error() {
  trap - ERR
  echo "Bootstrap failed!" >&2
  complete_lifecycle_action ABANDON || true
  exit 1
}
trap on_error ERR

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

# Portal runtime capacity knobs (#930) are non-secret integers fed from SSM into
# the container env, then interpolated into the `eval docker run` argv below. A
# non-integer value is rejected before any container starts so the argv cannot be
# injected. Empty is always allowed (parameter unset -> image default applies).
#
# validate_uint accepts 0 because the app treats a <= 0 TERMINAL_* cap as
# "disabled" (a deliberate break-glass; tfvars validation keeps deployed values
# positive). validate_positive_int additionally rejects 0, for knobs like the
# worker count where 0 is never valid.
validate_uint() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" && ! "$value" =~ ^[0-9]+$ ]]; then
    echo "Invalid $name: expected a non-negative integer"
    exit 1
  fi
}

validate_positive_int() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" && ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid $name: expected a positive integer"
    exit 1
  fi
}

validate_bool() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" && "$value" != "true" && "$value" != "false" ]]; then
    echo "Invalid $name: expected 'true' or 'false'"
    exit 1
  fi
}

image_ref() {
  local registry="$1"
  local repository="$2"
  local digest="$3"
  local tag="$4"

  if [[ -n "$digest" ]]; then
    if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
      echo "Invalid image digest: expected sha256:<hex>"
      exit 1
    fi
    printf '%s/%s@%s\n' "$registry" "$repository" "$digest"
    return
  fi

  printf '%s/%s:%s\n' "$registry" "$repository" "$tag"
}

IMAGE_DIGEST=$(get_param "$PS_PREFIX/image-digest" 2>/dev/null || echo "")
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
# Redis AUTH + in-transit encryption (#938). Present only on the secure path;
# entrypoint.sh hydrates REDIS_SECRET_ID into REDIS_PASSWORD/REDIS_CA_PEM.
REDIS_SECRET_ARN=$(get_param "$PS_PREFIX/redis-secret-arn" 2>/dev/null || echo "")
REDIS_TLS=$(get_param "$PS_PREFIX/redis-tls" 2>/dev/null || echo "")
REDIS_CA_MODE=$(get_param "$PS_PREFIX/redis-ca-mode" 2>/dev/null || echo "")
GUACAMOLE_SECRET_ARN=$(get_param "$PS_PREFIX/guacamole-secret-arn" 2>/dev/null || echo "")
DC_DOMAIN_PASSWORD_SECRET_ARN=$(get_param "$PS_PREFIX/dc-domain-password-secret-arn" 2>/dev/null || echo "")
GUACAMOLE_BASE_URL=$(get_param "$PS_PREFIX/guacamole-base-url" 2>/dev/null || echo "")
GUACAMOLE_API_BASE_URL=$(get_param "$PS_PREFIX/guacamole-api-base-url" 2>/dev/null || echo "")
DB_HOST_OVERRIDE=$(get_param "$PS_PREFIX/db-host-override" 2>/dev/null || echo "")
EMAIL_BACKEND=$(get_param "$PS_PREFIX/email-backend")
CTF_FROM_EMAIL=$(get_param "$PS_PREFIX/ctf-from-email")
CTFD_PLATFORM_URL=$(get_param "$PS_PREFIX/ctfd-platform-url" 2>/dev/null || echo "")
# Range event outbox topic ID (#476). Required by the outbox drainer; emitted
# into COMMON_ENV so the drainer container can publish to SNS. The value is a
# topic ARN (not a secret), so it is safe to pass as a non-secret env var.
RANGE_EVENTS_TOPIC_ID=$(get_param "$PS_PREFIX/range-events-topic-id" 2>/dev/null || echo "")
PLATFORM_BOOTSTRAP_STAFF_EMAILS=$(get_param "$PS_PREFIX/platform-bootstrap-staff-emails" 2>/dev/null || echo "")
PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=$(get_param "$PS_PREFIX/platform-bootstrap-superuser-emails" 2>/dev/null || echo "")
validate_bootstrap_email_list "PLATFORM_BOOTSTRAP_STAFF_EMAILS" "$PLATFORM_BOOTSTRAP_STAFF_EMAILS"
validate_bootstrap_email_list "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS" "$PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS"

# Portal runtime capacity tunables (#930). Process-local: the per-instance
# ceiling is PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS. Same parameter names the
# SSM redeploy path (scripts/portal-deploy/deploy_portal.sh) reads; validated as
# integers before they reach the docker argv, and only emitted when set.
PORTAL_WEB_WORKERS=$(get_param "$PS_PREFIX/portal-web-workers" 2>/dev/null || echo "")
TERMINAL_MAX_SESSIONS=$(get_param "$PS_PREFIX/terminal-max-sessions" 2>/dev/null || echo "")
TERMINAL_MAX_SESSIONS_PER_USER=$(get_param "$PS_PREFIX/terminal-max-sessions-per-user" 2>/dev/null || echo "")
TERMINAL_IDLE_TIMEOUT_SECONDS=$(get_param "$PS_PREFIX/terminal-idle-timeout-seconds" 2>/dev/null || echo "")
TERMINAL_MAX_SESSION_SECONDS=$(get_param "$PS_PREFIX/terminal-max-session-seconds" 2>/dev/null || echo "")
TERMINAL_READ_POLL_SECONDS=$(get_param "$PS_PREFIX/terminal-read-poll-seconds" 2>/dev/null || echo "")
validate_positive_int "PORTAL_WEB_WORKERS" "$PORTAL_WEB_WORKERS"
validate_uint "TERMINAL_MAX_SESSIONS" "$TERMINAL_MAX_SESSIONS"
validate_uint "TERMINAL_MAX_SESSIONS_PER_USER" "$TERMINAL_MAX_SESSIONS_PER_USER"
validate_uint "TERMINAL_IDLE_TIMEOUT_SECONDS" "$TERMINAL_IDLE_TIMEOUT_SECONDS"
validate_uint "TERMINAL_MAX_SESSION_SECONDS" "$TERMINAL_MAX_SESSION_SECONDS"
validate_uint "TERMINAL_READ_POLL_SECONDS" "$TERMINAL_READ_POLL_SECONDS"

# Portal web capacity metrics (#940). Enable flag + busy-ratio denominator come
# from SSM (same params the SSM redeploy path reads); the NamePrefix dimension
# comes from the Terraform name_prefix so it matches the CloudWatch alarms.
PORTAL_CAPACITY_METRICS_ENABLED=$(get_param "$PS_PREFIX/portal-capacity-metrics-enabled" 2>/dev/null || echo "")
PORTAL_WORKER_SOFT_CONCURRENCY=$(get_param "$PS_PREFIX/portal-worker-soft-concurrency" 2>/dev/null || echo "")
validate_bool "PORTAL_CAPACITY_METRICS_ENABLED" "$PORTAL_CAPACITY_METRICS_ENABLED"
validate_positive_int "PORTAL_WORKER_SOFT_CONCURRENCY" "$PORTAL_WORKER_SOFT_CONCURRENCY"

IMAGE=$(image_ref "$ECR_REGISTRY" "$ECR_REPOSITORY" "$IMAGE_DIGEST" "$IMAGE_TAG")
echo "Deploying image: $IMAGE"

# ------------------------------------------------------------------------------
# Build container environment variables
# ------------------------------------------------------------------------------
COMMON_ENV="-e AWS_REGION=$AWS_REGION"
COMMON_ENV="$COMMON_ENV -e ENVIRONMENT=$DJANGO_ENVIRONMENT"
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

# Redis AUTH + in-transit encryption (#938). Only the secret reference and
# non-secret flags travel here; the AUTH token is hydrated from Secrets Manager
# by entrypoint.sh, never passed via docker argv.
if [[ -n "$REDIS_SECRET_ARN" ]]; then
  COMMON_ENV="$COMMON_ENV -e REDIS_SECRET_ID=$REDIS_SECRET_ARN"
fi
if [[ -n "$REDIS_TLS" ]]; then
  COMMON_ENV="$COMMON_ENV -e REDIS_TLS=$REDIS_TLS"
fi
if [[ -n "$REDIS_CA_MODE" ]]; then
  COMMON_ENV="$COMMON_ENV -e REDIS_CA_MODE=$REDIS_CA_MODE"
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

# Portal runtime capacity tunables (#930), validated as integers above.
if [[ -n "$PORTAL_WEB_WORKERS" ]]; then
  COMMON_ENV="$COMMON_ENV -e PORTAL_WEB_WORKERS=$PORTAL_WEB_WORKERS"
fi
if [[ -n "$TERMINAL_MAX_SESSIONS" ]]; then
  COMMON_ENV="$COMMON_ENV -e TERMINAL_MAX_SESSIONS=$TERMINAL_MAX_SESSIONS"
fi
if [[ -n "$TERMINAL_MAX_SESSIONS_PER_USER" ]]; then
  COMMON_ENV="$COMMON_ENV -e TERMINAL_MAX_SESSIONS_PER_USER=$TERMINAL_MAX_SESSIONS_PER_USER"
fi
if [[ -n "$TERMINAL_IDLE_TIMEOUT_SECONDS" ]]; then
  COMMON_ENV="$COMMON_ENV -e TERMINAL_IDLE_TIMEOUT_SECONDS=$TERMINAL_IDLE_TIMEOUT_SECONDS"
fi
if [[ -n "$TERMINAL_MAX_SESSION_SECONDS" ]]; then
  COMMON_ENV="$COMMON_ENV -e TERMINAL_MAX_SESSION_SECONDS=$TERMINAL_MAX_SESSION_SECONDS"
fi
if [[ -n "$TERMINAL_READ_POLL_SECONDS" ]]; then
  COMMON_ENV="$COMMON_ENV -e TERMINAL_READ_POLL_SECONDS=$TERMINAL_READ_POLL_SECONDS"
fi

# Portal web capacity metrics (#940), validated above. The NamePrefix dimension
# is the Terraform name_prefix so the emitted series matches the CloudWatch
# alarms/dashboard; it is always set so an enabled emitter is never unlabelled.
COMMON_ENV="$COMMON_ENV -e PORTAL_CAPACITY_NAME_PREFIX=${name_prefix}"
if [[ -n "$PORTAL_CAPACITY_METRICS_ENABLED" ]]; then
  COMMON_ENV="$COMMON_ENV -e PORTAL_CAPACITY_METRICS_ENABLED=$PORTAL_CAPACITY_METRICS_ENABLED"
fi
if [[ -n "$PORTAL_WORKER_SOFT_CONCURRENCY" ]]; then
  COMMON_ENV="$COMMON_ENV -e PORTAL_WORKER_SOFT_CONCURRENCY=$PORTAL_WORKER_SOFT_CONCURRENCY"
fi

if [[ -n "$CTFD_PLATFORM_URL" ]]; then
  COMMON_ENV="$COMMON_ENV -e CTFD_PLATFORM_URL=$CTFD_PLATFORM_URL"
fi

# Range event topic ID (#476). The outbox drainer publishes directly to SNS;
# the value must be present for the drainer to function. Pass unconditionally
# so a missing SSM param surfaces as an empty-string at boot rather than a
# silent omission — the drainer fails closed (CommandError) if unset.
if [[ -n "$RANGE_EVENTS_TOPIC_ID" ]]; then
  COMMON_ENV="$COMMON_ENV -e RANGE_EVENTS_TOPIC_ID=$RANGE_EVENTS_TOPIC_ID"
fi

# Migrations are deploy-owned. Runtime containers skip boot-time migration so
# ASG refreshes and warm-pool reuse cannot race the same RDS schema.
COMMON_ENV="$COMMON_ENV -e SKIP_MIGRATIONS=1"

# ------------------------------------------------------------------------------
# Deploy containers
# ------------------------------------------------------------------------------
echo "Pulling image..."
docker pull "$IMAGE"

echo "Stopping existing containers..."
# Docker stop timeout exceeds the Gunicorn graceful-timeout (30s) so long-lived
# terminal/WebSocket connections drain before SIGKILL (issue #931). Sized below
# the ASG termination drain window.
docker stop --time ${docker_stop_timeout} portal worker-cms worker-engine worker-mc worker-outbox-drainer worker-reconciler ctf-scheduler guacamole-bootstrap-prune aces-operation-record-prune 2>/dev/null || true
# Force-remove so a redeploy is idempotent (matches scripts/portal-deploy/deploy_portal.sh,
# #1127); the docker stop above already does the graceful drain (#931).
docker rm -f portal worker-cms worker-engine worker-mc worker-outbox-drainer worker-reconciler ctf-scheduler guacamole-bootstrap-prune aces-operation-record-prune 2>/dev/null || true

echo "Starting portal..."
eval docker run -d --name portal --restart unless-stopped -p 8000:8000 $COMMON_ENV "$IMAGE"

echo "Starting workers..."
WORKER_HEALTH_BASE="--health-interval 30s --health-timeout 5s --health-start-period 90s --health-retries 2"
WORKER_CMS_HEALTH="--health-cmd='find /tmp/worker-cms-heartbeat -mmin -2 | grep -q .'"
WORKER_ENGINE_HEALTH="--health-cmd='find /tmp/worker-engine-heartbeat -mmin -2 | grep -q .'"
WORKER_MC_HEALTH="--health-cmd='find /tmp/worker-mc-heartbeat -mmin -2 | grep -q .'"
CTF_SCHEDULER_HEALTH="--health-cmd='find /tmp/ctf-scheduler-heartbeat -mmin -2 | grep -q .'"
GUAC_PRUNE_HEALTH="--health-cmd='find /tmp/guacamole-bootstrap-prune-heartbeat -mmin -2 | grep -q .'"
ACES_PRUNE_HEALTH="--health-cmd='find /tmp/aces-operation-record-prune-heartbeat -mmin -2 | grep -q .'"
OUTBOX_DRAINER_HEALTH="--health-cmd='find /tmp/worker-outbox-drainer-heartbeat -mmin -2 | grep -q .'"
RECONCILER_HEALTH="--health-cmd='find /tmp/worker-reconciler-heartbeat -mmin -2 | grep -q .'"
eval docker run -d --name worker-cms --restart unless-stopped $WORKER_HEALTH_BASE "$WORKER_CMS_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_worker --queue cms
eval docker run -d --name worker-engine --restart unless-stopped $WORKER_HEALTH_BASE "$WORKER_ENGINE_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_worker --queue engine
eval docker run -d --name worker-mc --restart unless-stopped $WORKER_HEALTH_BASE "$WORKER_MC_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_worker --queue mc
eval docker run -d --name worker-outbox-drainer --restart unless-stopped $WORKER_HEALTH_BASE "$OUTBOX_DRAINER_HEALTH" $COMMON_ENV "$IMAGE" python manage.py drain_range_event_outbox --loop --interval 10
eval docker run -d --name worker-reconciler --restart unless-stopped $WORKER_HEALTH_BASE "$RECONCILER_HEALTH" $COMMON_ENV "$IMAGE" python manage.py reconcile_range_events --loop --interval 60
eval docker run -d --name ctf-scheduler --restart unless-stopped $WORKER_HEALTH_BASE "$CTF_SCHEDULER_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_ctf_scheduler
eval docker run -d --name guacamole-bootstrap-prune --restart unless-stopped $WORKER_HEALTH_BASE "$GUAC_PRUNE_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_guacamole_bootstrap_prune
eval docker run -d --name aces-operation-record-prune --restart unless-stopped $WORKER_HEALTH_BASE "$ACES_PRUNE_HEALTH" $COMMON_ENV "$IMAGE" python manage.py run_aces_operation_record_prune

echo "All containers started:"
docker ps

# ------------------------------------------------------------------------------
# Worker-container health supervisor (#953)
# ------------------------------------------------------------------------------
# Docker --restart unless-stopped does not act on `unhealthy`, so a wedged
# worker would stall silently. Install a systemd-timer agent that restarts
# unhealthy worker/scheduler containers and emits a CloudWatch metric. The
# artifacts are single-sourced under modules/portal/ec2/worker-health/ and
# injected base64-encoded so this fresh-boot path and the SSM redeploy path
# install byte-identical files. Installed before completing the lifecycle hook
# so a fresh instance only reports healthy once supervision is live.
echo "Installing worker-container health supervisor..."
echo "${worker_health_monitor_b64}" | base64 -d > /usr/local/bin/shifter-worker-health.sh
chmod 0755 /usr/local/bin/shifter-worker-health.sh
echo "${worker_health_service_b64}" | base64 -d > /etc/systemd/system/shifter-worker-health.service
echo "${worker_health_timer_b64}" | base64 -d > /etc/systemd/system/shifter-worker-health.timer
# Per-environment metric dimension so dev and prod alarms stay independent.
echo "WH_NAME_PREFIX=${name_prefix}" > /etc/shifter-worker-health.env
systemctl daemon-reload
systemctl enable --now shifter-worker-health.timer

# ------------------------------------------------------------------------------
# Complete lifecycle action on success
# ------------------------------------------------------------------------------
# For a configured launch hook this is a required part of successful bootstrap:
# if it cannot be completed the instance would sit in Pending:Wait until the ASG
# ABANDONs it, so fail loudly here rather than printing a false success (#1032).
if ! complete_lifecycle_action CONTINUE; then
  echo "ERROR: failed to complete the launch lifecycle action; bootstrap did not succeed." >&2
  # Best-effort ABANDON so a resolved-ASG-but-failed-CONTINUE instance is
  # replaced immediately instead of sitting in Pending:Wait until the launch
  # hook times out. Non-fatal: the launch hook's ABANDON default reclaims the
  # instance on timeout regardless.
  complete_lifecycle_action ABANDON || true
  exit 1
fi

echo "=========================================="
echo "Shifter Platform bootstrap complete!"
echo "=========================================="
