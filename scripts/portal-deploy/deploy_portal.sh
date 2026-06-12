#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-2}"
PS_PREFIX=""
WORKER_HEALTH_MONITOR_B64=""
WORKER_HEALTH_SERVICE_B64=""
WORKER_HEALTH_TIMER_B64=""
WORKER_HEALTH_NAME_PREFIX=""
WORKER_HEALTH_BIN_PATH="/usr/local/bin/shifter-worker-health.sh"
WORKER_HEALTH_SERVICE_PATH="/etc/systemd/system/shifter-worker-health.service"
WORKER_HEALTH_TIMER_PATH="/etc/systemd/system/shifter-worker-health.timer"
WORKER_HEALTH_ENV_PATH="/etc/shifter-worker-health.env"
DOCKER_ENV=()

usage() {
  cat <<'EOF'
Usage: deploy_portal.sh --ps-prefix PREFIX --worker-health-monitor-b64 B64 --worker-health-service-b64 B64 --worker-health-timer-b64 B64 --worker-health-name-prefix PREFIX [options]

Required:
  --ps-prefix PREFIX
  --worker-health-monitor-b64 B64
  --worker-health-service-b64 B64
  --worker-health-timer-b64 B64
  --worker-health-name-prefix PREFIX

Options:
  --aws-region REGION
  --worker-health-bin-path PATH
  --worker-health-service-path PATH
  --worker-health-timer-path PATH
  --worker-health-env-path PATH
  --help
EOF
}

die_usage() {
  echo "deploy_portal.sh: $*" >&2
  usage >&2
  exit 2
}

require_value() {
  local option="$1"
  local value="${2:-}"
  if [[ -z "$value" ]]; then
    die_usage "${option} requires a value"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help)
        usage
        exit 0
        ;;
      --aws-region)
        require_value "$1" "${2:-}"
        AWS_REGION="$2"
        shift 2
        ;;
      --ps-prefix)
        require_value "$1" "${2:-}"
        PS_PREFIX="$2"
        shift 2
        ;;
      --worker-health-monitor-b64)
        require_value "$1" "${2:-}"
        WORKER_HEALTH_MONITOR_B64="$2"
        shift 2
        ;;
      --worker-health-service-b64)
        require_value "$1" "${2:-}"
        WORKER_HEALTH_SERVICE_B64="$2"
        shift 2
        ;;
      --worker-health-timer-b64)
        require_value "$1" "${2:-}"
        WORKER_HEALTH_TIMER_B64="$2"
        shift 2
        ;;
      --worker-health-name-prefix)
        require_value "$1" "${2:-}"
        WORKER_HEALTH_NAME_PREFIX="$2"
        shift 2
        ;;
      --worker-health-bin-path)
        require_value "$1" "${2:-}"
        WORKER_HEALTH_BIN_PATH="$2"
        shift 2
        ;;
      --worker-health-service-path)
        require_value "$1" "${2:-}"
        WORKER_HEALTH_SERVICE_PATH="$2"
        shift 2
        ;;
      --worker-health-timer-path)
        require_value "$1" "${2:-}"
        WORKER_HEALTH_TIMER_PATH="$2"
        shift 2
        ;;
      --worker-health-env-path)
        require_value "$1" "${2:-}"
        WORKER_HEALTH_ENV_PATH="$2"
        shift 2
        ;;
      *)
        die_usage "unknown argument: $1"
        ;;
    esac
  done

  [[ -n "$PS_PREFIX" ]] || die_usage "--ps-prefix is required"
  [[ -n "$WORKER_HEALTH_MONITOR_B64" ]] || die_usage "--worker-health-monitor-b64 is required"
  [[ -n "$WORKER_HEALTH_SERVICE_B64" ]] || die_usage "--worker-health-service-b64 is required"
  [[ -n "$WORKER_HEALTH_TIMER_B64" ]] || die_usage "--worker-health-timer-b64 is required"
  [[ -n "$WORKER_HEALTH_NAME_PREFIX" ]] || die_usage "--worker-health-name-prefix is required"
}

get_param() {
  aws ssm get-parameter \
    --name "$1" \
    --with-decryption \
    --query 'Parameter.Value' \
    --output text \
    --region "$AWS_REGION"
}

get_optional_param() {
  get_param "$1" 2>/dev/null || true
}

validate_bootstrap_email_list() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" && ! "$value" =~ ^[A-Za-z0-9._%+@,-]+$ ]]; then
    echo "Invalid ${name}: expected a comma-separated email list" >&2
    exit 1
  fi
}

append_env() {
  local name="$1"
  local value="$2"
  DOCKER_ENV+=("-e" "${name}=${value}")
}

append_env_if_set() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" ]]; then
    append_env "$name" "$value"
  fi
}

install_b64_file() {
  local payload_b64="$1"
  local path="$2"
  local mode="$3"

  mkdir -p "$(dirname "$path")"
  printf '%s' "$payload_b64" | base64 -d > "$path"
  chmod "$mode" "$path"
}

install_worker_health() {
  echo "Installing worker-container health supervisor..."
  install_b64_file "$WORKER_HEALTH_MONITOR_B64" "$WORKER_HEALTH_BIN_PATH" "0755"
  install_b64_file "$WORKER_HEALTH_SERVICE_B64" "$WORKER_HEALTH_SERVICE_PATH" "0644"
  install_b64_file "$WORKER_HEALTH_TIMER_B64" "$WORKER_HEALTH_TIMER_PATH" "0644"
  mkdir -p "$(dirname "$WORKER_HEALTH_ENV_PATH")"
  printf 'WH_NAME_PREFIX=%s\n' "$WORKER_HEALTH_NAME_PREFIX" > "$WORKER_HEALTH_ENV_PATH"
  systemctl daemon-reload
  systemctl enable --now shifter-worker-health.timer
}

run_containers() {
  local image="$1"
  shift
  local -a common_env=("$@")
  local -a worker_health_base=(
    --health-interval 30s
    --health-timeout 5s
    --health-start-period 90s
    --health-retries 2
  )

  docker pull "$image"
  docker stop portal worker-cms worker-engine worker-mc ctf-scheduler 2>/dev/null || true
  docker rm portal worker-cms worker-engine worker-mc ctf-scheduler 2>/dev/null || true
  docker run -d --name portal --restart unless-stopped -p 8000:8000 "${common_env[@]}" "$image"
  docker run -d --name worker-cms --restart unless-stopped "${worker_health_base[@]}" \
    "--health-cmd=find /tmp/worker-cms-heartbeat -mmin -2 | grep -q ." \
    "${common_env[@]}" "$image" python manage.py run_worker --queue cms
  docker run -d --name worker-engine --restart unless-stopped "${worker_health_base[@]}" \
    "--health-cmd=find /tmp/worker-engine-heartbeat -mmin -2 | grep -q ." \
    "${common_env[@]}" "$image" python manage.py run_worker --queue engine
  docker run -d --name worker-mc --restart unless-stopped "${worker_health_base[@]}" \
    "--health-cmd=find /tmp/worker-mc-heartbeat -mmin -2 | grep -q ." \
    "${common_env[@]}" "$image" python manage.py run_worker --queue mc
  docker run -d --name ctf-scheduler --restart unless-stopped "${worker_health_base[@]}" \
    "--health-cmd=find /tmp/ctf-scheduler-heartbeat -mmin -2 | grep -q ." \
    "${common_env[@]}" "$image" python manage.py run_ctf_scheduler
  docker ps
}

main() {
  parse_args "$@"

  local image_tag
  local ecr_registry
  local ecr_repository
  local domain_name
  local s3_bucket
  local db_secret_arn
  local app_secret_arn
  local cognito_secret_arn
  local guacamole_secret_arn
  local dc_domain_password_secret_arn
  local guacamole_base_url
  local guacamole_api_base_url
  local engine_ecs_cluster_arn
  local engine_task_definition_arn
  local engine_ecs_security_group_id
  local engine_private_subnet_ids
  local sqs_cms_url
  local sqs_engine_url
  local sqs_mc_url
  local redis_endpoint
  local channel_layer_backend
  local email_backend
  local ctf_from_email
  local platform_bootstrap_staff_emails
  local platform_bootstrap_superuser_emails

  image_tag=$(get_param "$PS_PREFIX/image-tag")
  ecr_registry=$(get_param "$PS_PREFIX/ecr-registry")
  ecr_repository=$(get_param "$PS_PREFIX/ecr-repository")
  domain_name=$(get_param "$PS_PREFIX/domain-name")
  s3_bucket=$(get_param "$PS_PREFIX/s3-bucket")
  db_secret_arn=$(get_param "$PS_PREFIX/db-secret-arn")
  app_secret_arn=$(get_param "$PS_PREFIX/app-secret-arn")
  cognito_secret_arn=$(get_param "$PS_PREFIX/cognito-secret-arn")
  guacamole_secret_arn=$(get_optional_param "$PS_PREFIX/guacamole-secret-arn")
  dc_domain_password_secret_arn=$(get_optional_param "$PS_PREFIX/dc-domain-password-secret-arn")
  guacamole_base_url=$(get_optional_param "$PS_PREFIX/guacamole-base-url")
  guacamole_api_base_url=$(get_optional_param "$PS_PREFIX/guacamole-api-base-url")
  engine_ecs_cluster_arn=$(get_param "$PS_PREFIX/engine-ecs-cluster-arn")
  engine_task_definition_arn=$(get_param "$PS_PREFIX/engine-task-definition-arn")
  engine_ecs_security_group_id=$(get_param "$PS_PREFIX/engine-ecs-security-group-id")
  engine_private_subnet_ids=$(get_param "$PS_PREFIX/engine-private-subnet-ids")
  sqs_cms_url=$(get_param "$PS_PREFIX/sqs-cms-url")
  sqs_engine_url=$(get_param "$PS_PREFIX/sqs-engine-url")
  sqs_mc_url=$(get_param "$PS_PREFIX/sqs-mc-url")
  redis_endpoint=$(get_optional_param "$PS_PREFIX/redis-endpoint")
  channel_layer_backend=$(get_optional_param "$PS_PREFIX/channel-layer-backend")
  email_backend=$(get_optional_param "$PS_PREFIX/email-backend")
  ctf_from_email=$(get_optional_param "$PS_PREFIX/ctf-from-email")
  platform_bootstrap_staff_emails=$(get_optional_param "$PS_PREFIX/platform-bootstrap-staff-emails")
  platform_bootstrap_superuser_emails=$(get_optional_param "$PS_PREFIX/platform-bootstrap-superuser-emails")
  validate_bootstrap_email_list "PLATFORM_BOOTSTRAP_STAFF_EMAILS" "$platform_bootstrap_staff_emails"
  validate_bootstrap_email_list "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS" "$platform_bootstrap_superuser_emails"

  local image="${ecr_registry}/${ecr_repository}:${image_tag}"
  echo "Deploying image: $image"

  DOCKER_ENV=()
  append_env AWS_REGION "$AWS_REGION"
  append_env AWS_S3_BUCKET_NAME "$s3_bucket"
  append_env DB_SECRET_ARN "$db_secret_arn"
  append_env APP_SECRET_ARN "$app_secret_arn"
  append_env COGNITO_SECRET_ARN "$cognito_secret_arn"
  append_env_if_set GUACAMOLE_SECRET_ARN "$guacamole_secret_arn"
  append_env_if_set GUACAMOLE_BASE_URL "$guacamole_base_url"
  append_env_if_set GUACAMOLE_API_BASE_URL "$guacamole_api_base_url"
  append_env_if_set DC_DOMAIN_PASSWORD_SECRET_ARN "$dc_domain_password_secret_arn"

  if [[ "$PS_PREFIX" == *"/dev/"* ]]; then
    append_env DJANGO_ALLOWED_HOSTS "${domain_name},localhost,127.0.0.1"
  else
    append_env DJANGO_ALLOWED_HOSTS "$domain_name"
  fi
  append_env DJANGO_CSRF_TRUSTED_ORIGINS "https://${domain_name}"
  append_env SITE_URL "https://${domain_name}"
  append_env ENGINE_ECS_CLUSTER_ARN "$engine_ecs_cluster_arn"
  append_env ENGINE_TASK_DEFINITION_ARN "$engine_task_definition_arn"
  append_env ENGINE_ECS_SECURITY_GROUP_ID "$engine_ecs_security_group_id"
  append_env ENGINE_PRIVATE_SUBNET_IDS "$engine_private_subnet_ids"
  append_env SQS_CMS_URL "$sqs_cms_url"
  append_env SQS_ENGINE_URL "$sqs_engine_url"
  append_env SQS_MC_URL "$sqs_mc_url"
  append_env_if_set REDIS_HOST "$redis_endpoint"
  append_env_if_set CHANNEL_LAYER_BACKEND "$channel_layer_backend"
  append_env_if_set EMAIL_BACKEND "$email_backend"
  append_env_if_set CTF_FROM_EMAIL "$ctf_from_email"
  append_env_if_set PLATFORM_BOOTSTRAP_STAFF_EMAILS "$platform_bootstrap_staff_emails"
  append_env_if_set PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS "$platform_bootstrap_superuser_emails"

  run_containers "$image" "${DOCKER_ENV[@]}"
  install_worker_health
  echo "Deployment complete!"
}

main "$@"
