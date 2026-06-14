#!/usr/bin/env bash
# Built-image stack smoke (issue #922).
#
# Boots the *production* portal image under its *real* entrypoint.sh against
# local Postgres / Redis / ElasticMQ test doubles and asserts the runtime
# contracts that the source-tree pytest estate cannot see:
#
#   * the image builds (deps + compilemessages + collectstatic as appuser);
#   * entrypoint.sh waits for the DB, runs migrations exactly once, and execs
#     the production Gunicorn/Uvicorn ASGI command as the non-root appuser;
#   * /health returns 200 from the real dependency-aware django-health-check
#     registry (DB + cache + storage + redis channel layer);
#   * an authenticated websocket handshake completes through the real ASGI
#     stack (AllowedHostsOriginValidator + AuthMiddlewareStack + a routed
#     consumer);
#   * the SQS worker and CTF scheduler boot from the same image and produce
#     their /tmp heartbeat files.
#
# Reverting the June-7 /home/appuser fix (or an equivalent entrypoint
# regression) fails this script because every assertion exercises the real
# container, not "the container is running".
#
# Runs on hosted runners with NO cloud credentials: the only AWS surface is a
# local ElasticMQ double reached via AWS_ENDPOINT_URL with dummy creds.
#
# Reusable harness: the scalar knobs below are env-overridable, and the
# worker/scheduler set is a single SMOKE_WORKER_SPECS list, so future variations
# (different websocket route, scheduler-only, post-lock-bump rerun) are a
# parameter change, not a second copy of this block. See README.md.
set -euo pipefail

# --- Parameters (env-overridable) ------------------------------------------
SMOKE_NETWORK="${SMOKE_NETWORK:-shifter-stack-smoke}"
SMOKE_IMAGE="${SMOKE_IMAGE:-shifter-portal:stack-smoke}"
SMOKE_BUILD="${SMOKE_BUILD:-1}"
SMOKE_DOCKERFILE="${SMOKE_DOCKERFILE:-shifter/shifter_platform/Dockerfile}"
SMOKE_CONTEXT="${SMOKE_CONTEXT:-shifter}"
SMOKE_WEB_PORT="${SMOKE_WEB_PORT:-18000}"
SMOKE_HEALTH_PATH="${SMOKE_HEALTH_PATH:-/health/}"
SMOKE_WS_PATH="${SMOKE_WS_PATH:-ws/notifications/}"
# Authenticated, range-independent pages whose render + static assets are
# asserted off the built image (the #923 TEST-3 range-independent subset).
SMOKE_PAGES="${SMOKE_PAGES:-/dashboard/ /mission-control/ /mission-control/terminal/ /mission-control/settings/ /mission-control/help/}"
SMOKE_BOOT_TIMEOUT="${SMOKE_BOOT_TIMEOUT:-180}"
SMOKE_HEARTBEAT_TIMEOUT="${SMOKE_HEARTBEAT_TIMEOUT:-120}"

PG_IMAGE="${SMOKE_PG_IMAGE:-postgres:16}"
REDIS_IMAGE="${SMOKE_REDIS_IMAGE:-redis:7}"
ELASTICMQ_IMAGE="${SMOKE_ELASTICMQ_IMAGE:-softwaremill/elasticmq-native:1.6.11}"

# Ephemeral, non-production smoke values only.
DB_NAME=shifter
DB_USER=smoke
DB_PASSWORD=smoke

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Container names (stable, so teardown is deterministic).
WEB=shifter-smoke-web
PG=shifter-smoke-postgres
REDIS=shifter-smoke-redis
ELASTICMQ=shifter-smoke-elasticmq
MIGRATE=shifter-smoke-migrate

# Worker / scheduler set: one "name|heartbeat_file|command" entry per line.
# Default mirrors the production monitored set minimally: one SQS worker (proves
# the cloud-queue abstraction against the local double) plus the CTF scheduler.
read -r -d '' SMOKE_WORKER_SPECS_DEFAULT <<'SPECS' || true
worker-cms|/tmp/worker-cms-heartbeat|python manage.py run_worker --queue cms --wait-time 1
ctf-scheduler|/tmp/ctf-scheduler-heartbeat|python manage.py run_ctf_scheduler --poll-interval 1
SPECS
SMOKE_WORKER_SPECS="${SMOKE_WORKER_SPECS:-$SMOKE_WORKER_SPECS_DEFAULT}"

declare -a WORKER_CONTAINERS=()

log() { printf '\n=== %s\n' "$*"; }
note() { printf -- '--- %s\n' "$*"; }
fail() {
  printf '::error::stack-smoke: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    log "FAILURE (exit ${rc}) - bounded container diagnostics"
    local c
    for c in "$MIGRATE" "$WEB" ${WORKER_CONTAINERS[@]+"${WORKER_CONTAINERS[@]}"}; do
      docker logs --tail 40 "$c" 2>&1 | sed "s/^/[$c] /" || true
    done
  fi
  docker rm -f \
    "$WEB" "$MIGRATE" "$PG" "$REDIS" "$ELASTICMQ" \
    ${WORKER_CONTAINERS[@]+"${WORKER_CONTAINERS[@]}"} >/dev/null 2>&1 || true
  docker network rm "$SMOKE_NETWORK" >/dev/null 2>&1 || true
  return $rc
}
trap cleanup EXIT

# --- helpers ----------------------------------------------------------------

gen_secret() { python3 -c 'import secrets; print(secrets.token_urlsafe(48))'; }
gen_fernet_key() { python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'; }

wait_for() {
  # wait_for <timeout_s> <description> <command...>
  local timeout="$1" desc="$2"
  shift 2
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  fail "timed out after ${timeout}s waiting for ${desc}"
}

http_status() {
  curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 \
    "http://127.0.0.1:${SMOKE_WEB_PORT}${SMOKE_HEALTH_PATH}" 2>/dev/null
}
health_200() { [[ "$(http_status || true)" == "200" ]]; }

assert_skipped_migrations() {
  local container="$1"
  if ! docker logs "$container" 2>&1 | grep -q "Skipping migrations"; then
    fail "${container} did not skip migrations (SKIP_MIGRATIONS contract broken)"
  fi
}

assert_home_writable() {
  # Directly pins the June-7 home-directory regression class (#922): the
  # production image must run as the non-root image user with a writable HOME
  # and the terraform/pulumi runtime cache dirs the Dockerfile creates under it.
  # Reverting that Dockerfile fix (or running as a user without a writable home)
  # makes this fail. The boot/health path alone does not exercise HOME, so this
  # is an explicit check against the running container's real user.
  local container="$1"
  if ! docker exec "$container" sh -c 'test -w "$HOME" && test -w "$HOME/.terraform.d/plugin-cache" && test -w "$HOME/.pulumi"'; then
    fail "${container}: HOME is not writable by the image user (home-directory regression)"
  fi
}

# --- main -------------------------------------------------------------------

command -v docker >/dev/null 2>&1 || fail "docker is required"

log "Generating ephemeral smoke secrets"
DJANGO_SECRET_KEY="$(gen_secret)"
FIELD_ENCRYPTION_KEY="$(gen_fernet_key)"

if [[ "$SMOKE_BUILD" == "1" ]]; then
  log "Building production portal image (${SMOKE_IMAGE})"
  docker build -f "${REPO_ROOT}/${SMOKE_DOCKERFILE}" -t "$SMOKE_IMAGE" "${REPO_ROOT}/${SMOKE_CONTEXT}"
else
  note "SMOKE_BUILD=0 - using pre-built ${SMOKE_IMAGE}"
fi

log "Creating private docker network and dependency doubles"
docker network create "$SMOKE_NETWORK" >/dev/null

docker run -d --name "$PG" --network "$SMOKE_NETWORK" \
  -e POSTGRES_DB="$DB_NAME" -e POSTGRES_USER="$DB_USER" -e POSTGRES_PASSWORD="$DB_PASSWORD" \
  "$PG_IMAGE" >/dev/null

docker run -d --name "$REDIS" --network "$SMOKE_NETWORK" "$REDIS_IMAGE" >/dev/null

docker run -d --name "$ELASTICMQ" --network "$SMOKE_NETWORK" \
  -v "${SCRIPT_DIR}/elasticmq.conf:/opt/elasticmq.conf:ro" \
  "$ELASTICMQ_IMAGE" >/dev/null

wait_for 60 "postgres" docker exec "$PG" pg_isready -U "$DB_USER" -d "$DB_NAME"
wait_for 60 "redis" docker exec "$REDIS" redis-cli ping

# Common runtime env: enough to satisfy production settings import and the real
# entrypoint without any cloud access. Mirrors deploy_portal.sh env names.
declare -a common_env=(
  -e "DB_HOST=${PG}" -e DB_PORT=5432 -e "DB_NAME=${DB_NAME}" -e "DB_USER=${DB_USER}" -e "DB_PASSWORD=${DB_PASSWORD}"
  -e "DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}"
  -e "FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY}"
  -e "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,${WEB}"
  -e OIDC_RP_CLIENT_ID=stack-smoke-client
  -e OIDC_ISSUER_URL=https://issuer.example.test
  -e OIDC_AUTH_DOMAIN=https://auth.example.test
  -e "REDIS_HOST=${REDIS}" -e REDIS_PORT=6379
  -e CHANNEL_LAYER_BACKEND=redis
  -e "AWS_ENDPOINT_URL=http://${ELASTICMQ}:9324"
  -e AWS_ACCESS_KEY_ID=stack-smoke -e AWS_SECRET_ACCESS_KEY=stack-smoke -e AWS_DEFAULT_REGION=us-east-2
  -e "SQS_CMS_URL=http://${ELASTICMQ}:9324/000000000000/cms"
)

# Migrate exactly once, in a dedicated one-shot, exactly as the production
# deploy does (deploy_portal.sh run_migrations). Every long-running container
# below then boots with SKIP_MIGRATIONS=1.
log "Running database migrations once (dedicated one-shot)"
docker run --rm --name "$MIGRATE" --network "$SMOKE_NETWORK" \
  "${common_env[@]}" -e SKIP_MIGRATIONS=1 \
  "$SMOKE_IMAGE" python manage.py migrate --noinput

log "Booting web container through the real entrypoint"
docker run -d --name "$WEB" --network "$SMOKE_NETWORK" \
  -p "127.0.0.1:${SMOKE_WEB_PORT}:8000" \
  "${common_env[@]}" -e SKIP_MIGRATIONS=1 \
  "$SMOKE_IMAGE" >/dev/null

note "Waiting for ${SMOKE_HEALTH_PATH} to return 200"
wait_for "$SMOKE_BOOT_TIMEOUT" "portal readiness (${SMOKE_HEALTH_PATH} 200)" health_200
note "Readiness 200 OK"
assert_skipped_migrations "$WEB"
assert_home_writable "$WEB"
note "HOME writable as the image's non-root user"

log "Proving authenticated websocket handshake through the real ASGI stack"
# Create a throwaway authenticated session in the smoke database via the running
# container (no app change, no /dev-login). The key is captured from stdout only.
session_key="$(
  docker exec "$WEB" python manage.py shell -c '
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
User = get_user_model()
user, created = User.objects.get_or_create(username="stack-smoke")
if created:
    user.set_unusable_password()
    user.save()
store = SessionStore()
store["_auth_user_id"] = str(user.pk)
store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
store["_auth_user_hash"] = user.get_session_auth_hash()
store.create()
print(store.session_key)
' 2>/dev/null | tail -n 1
)"
[[ -n "$session_key" ]] || fail "could not create a smoke session for the websocket probe"

uv run --with 'websockets==12.0' python "${SCRIPT_DIR}/ws_handshake.py" \
  --url "ws://127.0.0.1:${SMOKE_WEB_PORT}/${SMOKE_WS_PATH}" \
  --session "$session_key" \
  --origin "http://localhost"

log "Asserting authenticated page renders and static assets resolve"
# Reuses the same smoke session. Catches the June container-runtime class
# (missing terminal sourcemaps / static assets) the source-tree tests miss.
python3 "${SCRIPT_DIR}/page_smoke.py" \
  --base "http://127.0.0.1:${SMOKE_WEB_PORT}" \
  --session "$session_key" \
  --paths "$SMOKE_PAGES"

log "Booting worker / scheduler containers and asserting heartbeats"
while IFS='|' read -r wname hbfile wcmd; do
  [[ -z "$wname" ]] && continue
  cname="shifter-smoke-${wname}"
  WORKER_CONTAINERS+=("$cname")
  # wcmd is an intentional word-split command line, e.g.
  # "python manage.py run_worker --queue cms --wait-time 1".
  # shellcheck disable=SC2086
  docker run -d --name "$cname" --network "$SMOKE_NETWORK" \
    "${common_env[@]}" -e SKIP_MIGRATIONS=1 \
    "$SMOKE_IMAGE" $wcmd >/dev/null
  note "Waiting for ${wname} heartbeat ${hbfile}"
  wait_for "$SMOKE_HEARTBEAT_TIMEOUT" "${wname} heartbeat ${hbfile}" \
    docker exec "$cname" test -f "$hbfile"
  assert_skipped_migrations "$cname"
  note "${wname} heartbeat present"
done <<< "$SMOKE_WORKER_SPECS"

log "Stack smoke PASSED: built image boots, /health 200, websocket OPEN, worker heartbeats present"
