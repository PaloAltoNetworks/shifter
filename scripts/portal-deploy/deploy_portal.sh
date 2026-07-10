#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-2}"
PS_PREFIX=""
WORKER_HEALTH_MONITOR_B64=""
WORKER_HEALTH_SERVICE_B64=""
WORKER_HEALTH_TIMER_B64=""
WORKER_HEALTH_NAME_PREFIX=""
MIGRATE_ONLY=false
WORKER_HEALTH_BIN_PATH="/usr/local/bin/shifter-worker-health.sh"
WORKER_HEALTH_SERVICE_PATH="/etc/systemd/system/shifter-worker-health.service"
WORKER_HEALTH_TIMER_PATH="/etc/systemd/system/shifter-worker-health.timer"
WORKER_HEALTH_ENV_PATH="/etc/shifter-worker-health.env"
DOCKER_ENV=()

usage() {
  cat <<'EOF'
Usage: deploy_portal.sh --ps-prefix PREFIX [options]

Required:
  --ps-prefix PREFIX

Required unless --migrate-only is set:
  --worker-health-monitor-b64 B64
  --worker-health-service-b64 B64
  --worker-health-timer-b64 B64
  --worker-health-name-prefix PREFIX

Options:
  --aws-region REGION
  --migrate-only
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
      --migrate-only)
        MIGRATE_ONLY=true
        shift
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
  if [[ "$MIGRATE_ONLY" != "true" ]]; then
    [[ -n "$WORKER_HEALTH_MONITOR_B64" ]] || die_usage "--worker-health-monitor-b64 is required"
    [[ -n "$WORKER_HEALTH_SERVICE_B64" ]] || die_usage "--worker-health-service-b64 is required"
    [[ -n "$WORKER_HEALTH_TIMER_B64" ]] || die_usage "--worker-health-timer-b64 is required"
    [[ -n "$WORKER_HEALTH_NAME_PREFIX" ]] || die_usage "--worker-health-name-prefix is required"
  fi
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

# Portal runtime capacity knobs (#930) are non-secret integers fed from SSM into
# the container env. They are interpolated into `docker run` argv, so a
# non-integer value is rejected before any container call to keep the argv
# injection-safe. Empty is always allowed (the parameter is unset and the image
# default applies).
#
# validate_uint accepts 0 because the app treats a <= 0 TERMINAL_* cap as
# "disabled" (a deliberate break-glass; tfvars validation keeps deployed values
# positive). validate_positive_int additionally rejects 0, for knobs like the
# worker count where 0 is never valid.
validate_uint() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" && ! "$value" =~ ^[0-9]+$ ]]; then
    echo "Invalid ${name}: expected a non-negative integer" >&2
    exit 1
  fi
}

validate_positive_int() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" && ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid ${name}: expected a positive integer" >&2
    exit 1
  fi
}

validate_bool() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" && "$value" != "true" && "$value" != "false" ]]; then
    echo "Invalid ${name}: expected 'true' or 'false'" >&2
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
      echo "Invalid image digest: expected sha256:<hex>" >&2
      exit 1
    fi
    printf '%s/%s@%s\n' "$registry" "$repository" "$digest"
    return
  fi

  printf '%s/%s:%s\n' "$registry" "$repository" "$tag"
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

run_migrations() {
  local image="$1"
  shift
  local -a common_env=("$@")

  echo "Running database migrations..."
  docker pull "$image"
  # DB_IAM_AUTH_RUNTIME=false keeps this one-off migrate on the password-
  # authenticated master user (schema owner). The image entrypoint otherwise
  # switches the connection to the rds_iam runtime user (portal_runtime) before
  # exec'ing this command, which is wrong for migrations: that user is *created*
  # by a migration (mission_control 0041) and holds only DML grants, so on a
  # fresh database it does not exist yet and the connect fails with
  # "password authentication failed for user portal_runtime". Migrations must
  # run as the master; the runtime containers below still switch to IAM auth.
  docker run --rm "${common_env[@]}" -e SKIP_MIGRATIONS=1 -e DB_IAM_AUTH_RUNTIME=false "$image" python manage.py migrate --noinput
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

  # Give containers time to shut down gracefully before SIGKILL. The portal's
  # Gunicorn graceful-timeout is 30s (PORTAL_WEB_GRACEFUL_TIMEOUT); the Docker
  # stop timeout must exceed it so long-lived terminal/WebSocket connections
  # drain instead of being severed by the default 10s SIGTERM-to-SIGKILL window
  # (issue #931). DOCKER_STOP_TIMEOUT must stay below the ASG termination drain.
  local stop_timeout="${DOCKER_STOP_TIMEOUT:-35}"
  docker pull "$image"
  docker stop --time "$stop_timeout" portal worker-cms worker-engine worker-mc worker-outbox-drainer worker-reconciler ctf-scheduler guacamole-bootstrap-prune aces-operation-record-prune 2>/dev/null || true
  # Force-remove so a redeploy is idempotent. `docker stop` above does the
  # graceful drain (#931); a plain `docker rm` then fails for any container
  # still running (e.g. one the stop did not fully stop / a restart-policy
  # race), the failure is swallowed by `|| true`, and the subsequent
  # `docker run --name <x>` aborts with "name already in use". `-f` removes
  # regardless of state so the new containers always get their names.
  docker rm -f portal worker-cms worker-engine worker-mc worker-outbox-drainer worker-reconciler ctf-scheduler guacamole-bootstrap-prune aces-operation-record-prune 2>/dev/null || true
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
  docker run -d --name worker-outbox-drainer --restart unless-stopped "${worker_health_base[@]}" \
    "--health-cmd=find /tmp/worker-outbox-drainer-heartbeat -mmin -2 | grep -q ." \
    "${common_env[@]}" "$image" python manage.py drain_range_event_outbox --loop --interval 10
  docker run -d --name worker-reconciler --restart unless-stopped "${worker_health_base[@]}" \
    "--health-cmd=find /tmp/worker-reconciler-heartbeat -mmin -2 | grep -q ." \
    "${common_env[@]}" "$image" python manage.py reconcile_range_events --loop --interval 60
  docker run -d --name ctf-scheduler --restart unless-stopped "${worker_health_base[@]}" \
    "--health-cmd=find /tmp/ctf-scheduler-heartbeat -mmin -2 | grep -q ." \
    "${common_env[@]}" "$image" python manage.py run_ctf_scheduler
  docker run -d --name guacamole-bootstrap-prune --restart unless-stopped "${worker_health_base[@]}" \
    "--health-cmd=find /tmp/guacamole-bootstrap-prune-heartbeat -mmin -2 | grep -q ." \
    "${common_env[@]}" "$image" python manage.py run_guacamole_bootstrap_prune
  docker run -d --name aces-operation-record-prune --restart unless-stopped "${worker_health_base[@]}" \
    "--health-cmd=find /tmp/aces-operation-record-prune-heartbeat -mmin -2 | grep -q ." \
    "${common_env[@]}" "$image" python manage.py run_aces_operation_record_prune
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
  local redis_secret_arn
  local redis_tls
  local redis_ca_mode
  local email_backend
  local ctf_from_email
  local platform_bootstrap_staff_emails
  local platform_bootstrap_superuser_emails
  local image_digest
  local portal_web_workers
  local terminal_max_sessions
  local terminal_max_sessions_per_user
  local terminal_idle_timeout_seconds
  local terminal_max_session_seconds
  local terminal_read_poll_seconds
  local portal_capacity_metrics_enabled
  local portal_worker_soft_concurrency
  local range_events_topic_id
  local environment

  environment=$(get_param "$PS_PREFIX/environment")
  image_digest=$(get_optional_param "$PS_PREFIX/image-digest")
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
  # Redis AUTH + in-transit encryption (#938). Mirrors user_data.sh: emit the
  # secret reference + non-secret flags; entrypoint.sh hydrates the token.
  redis_secret_arn=$(get_optional_param "$PS_PREFIX/redis-secret-arn")
  redis_tls=$(get_optional_param "$PS_PREFIX/redis-tls")
  redis_ca_mode=$(get_optional_param "$PS_PREFIX/redis-ca-mode")
  email_backend=$(get_optional_param "$PS_PREFIX/email-backend")
  ctf_from_email=$(get_optional_param "$PS_PREFIX/ctf-from-email")
  if [[ -z "$email_backend" ]]; then
    email_backend="django.core.mail.backends.console.EmailBackend"
  fi
  platform_bootstrap_staff_emails=$(get_optional_param "$PS_PREFIX/platform-bootstrap-staff-emails")
  platform_bootstrap_superuser_emails=$(get_optional_param "$PS_PREFIX/platform-bootstrap-superuser-emails")
  validate_bootstrap_email_list "PLATFORM_BOOTSTRAP_STAFF_EMAILS" "$platform_bootstrap_staff_emails"
  validate_bootstrap_email_list "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS" "$platform_bootstrap_superuser_emails"

  # Portal runtime capacity tunables (#930). Each is process-local: the
  # per-instance ceiling is PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS. Read the
  # same parameter names user_data.sh reads, validate as integers before they
  # reach docker argv, and only emit when set (image default applies otherwise).
  portal_web_workers=$(get_optional_param "$PS_PREFIX/portal-web-workers")
  terminal_max_sessions=$(get_optional_param "$PS_PREFIX/terminal-max-sessions")
  terminal_max_sessions_per_user=$(get_optional_param "$PS_PREFIX/terminal-max-sessions-per-user")
  terminal_idle_timeout_seconds=$(get_optional_param "$PS_PREFIX/terminal-idle-timeout-seconds")
  terminal_max_session_seconds=$(get_optional_param "$PS_PREFIX/terminal-max-session-seconds")
  terminal_read_poll_seconds=$(get_optional_param "$PS_PREFIX/terminal-read-poll-seconds")
  validate_positive_int "PORTAL_WEB_WORKERS" "$portal_web_workers"
  validate_uint "TERMINAL_MAX_SESSIONS" "$terminal_max_sessions"
  validate_uint "TERMINAL_MAX_SESSIONS_PER_USER" "$terminal_max_sessions_per_user"
  validate_uint "TERMINAL_IDLE_TIMEOUT_SECONDS" "$terminal_idle_timeout_seconds"
  validate_uint "TERMINAL_MAX_SESSION_SECONDS" "$terminal_max_session_seconds"
  validate_uint "TERMINAL_READ_POLL_SECONDS" "$terminal_read_poll_seconds"

  # Portal web capacity metrics (#940). Same parameter names user_data.sh reads;
  # validated before docker argv. The NamePrefix dimension reuses the portal name
  # prefix this script already receives (--worker-health-name-prefix) so an
  # enabled emitter is always labelled and matches the CloudWatch alarms.
  portal_capacity_metrics_enabled=$(get_optional_param "$PS_PREFIX/portal-capacity-metrics-enabled")
  portal_worker_soft_concurrency=$(get_optional_param "$PS_PREFIX/portal-worker-soft-concurrency")
  validate_bool "PORTAL_CAPACITY_METRICS_ENABLED" "$portal_capacity_metrics_enabled"
  validate_positive_int "PORTAL_WORKER_SOFT_CONCURRENCY" "$portal_worker_soft_concurrency"

  # Range event outbox topic ID (#476). Required by the outbox drainer; passed
  # as a non-secret env var (topic ARN, not a credential).
  range_events_topic_id=$(get_optional_param "$PS_PREFIX/range-events-topic-id")

  local image
  image=$(image_ref "$ecr_registry" "$ecr_repository" "$image_digest" "$image_tag")
  echo "Deploying image: $image"

  DOCKER_ENV=()
  append_env ENVIRONMENT "$environment"
  append_env AWS_REGION "$AWS_REGION"
  append_env AWS_S3_BUCKET_NAME "$s3_bucket"
  append_env DB_SECRET_ARN "$db_secret_arn"
  append_env APP_SECRET_ARN "$app_secret_arn"
  append_env COGNITO_SECRET_ARN "$cognito_secret_arn"
  append_env_if_set GUACAMOLE_SECRET_ARN "$guacamole_secret_arn"
  append_env_if_set GUACAMOLE_BASE_URL "$guacamole_base_url"
  append_env_if_set GUACAMOLE_API_BASE_URL "$guacamole_api_base_url"
  append_env_if_set DC_DOMAIN_PASSWORD_SECRET_ARN "$dc_domain_password_secret_arn"

  # localhost / 127.0.0.1 must be in ALLOWED_HOSTS in EVERY environment: the
  # path-scoped HealthCheckMiddleware (#477) rewrites the Host of /health
  # probes to "localhost" so AWS ALB / Docker health checks (which arrive
  # with the LB internal IP or localhost as Host) are admitted. Without them
  # the portal target group health check fails closed (DisallowedHost -> 400
  # -> unhealthy -> 504). The bypass is scoped to /health, so these are not
  # accepted application hosts on any other path. Matches
  # scripts/gcp/render_runtime_env.py (the canonical GCP renderer).
  append_env DJANGO_ALLOWED_HOSTS "${domain_name},localhost,127.0.0.1"
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
  append_env_if_set REDIS_SECRET_ID "$redis_secret_arn"
  append_env_if_set REDIS_TLS "$redis_tls"
  append_env_if_set REDIS_CA_MODE "$redis_ca_mode"
  append_env EMAIL_BACKEND "$email_backend"
  append_env_if_set CTF_FROM_EMAIL "$ctf_from_email"
  append_env_if_set PLATFORM_BOOTSTRAP_STAFF_EMAILS "$platform_bootstrap_staff_emails"
  append_env_if_set PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS "$platform_bootstrap_superuser_emails"
  append_env_if_set PORTAL_WEB_WORKERS "$portal_web_workers"
  append_env_if_set TERMINAL_MAX_SESSIONS "$terminal_max_sessions"
  append_env_if_set TERMINAL_MAX_SESSIONS_PER_USER "$terminal_max_sessions_per_user"
  append_env_if_set TERMINAL_IDLE_TIMEOUT_SECONDS "$terminal_idle_timeout_seconds"
  append_env_if_set TERMINAL_MAX_SESSION_SECONDS "$terminal_max_session_seconds"
  append_env_if_set TERMINAL_READ_POLL_SECONDS "$terminal_read_poll_seconds"
  append_env PORTAL_CAPACITY_NAME_PREFIX "$WORKER_HEALTH_NAME_PREFIX"
  append_env_if_set PORTAL_CAPACITY_METRICS_ENABLED "$portal_capacity_metrics_enabled"
  append_env_if_set PORTAL_WORKER_SOFT_CONCURRENCY "$portal_worker_soft_concurrency"
  append_env_if_set RANGE_EVENTS_TOPIC_ID "$range_events_topic_id"

  run_migrations "$image" "${DOCKER_ENV[@]}"
  if [[ "$MIGRATE_ONLY" == "true" ]]; then
    echo "Migration complete!"
    return
  fi

  append_env SKIP_MIGRATIONS "1"
  run_containers "$image" "${DOCKER_ENV[@]}"
  install_worker_health
  echo "Deployment complete!"
}

main "$@"
