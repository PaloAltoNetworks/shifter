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
#   * a real OIDC authorization-code login (against a local Cognito-shaped
#     provider double) drives /login -> authorize -> /oidc/callback, provisions
#     the first-login user + profile, and establishes the session used below (#988);
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
# Bound for log-line assertions against `docker logs` (the line is already
# emitted; this only absorbs docker log-delivery lag behind the readiness probe).
SMOKE_LOG_ASSERT_TIMEOUT="${SMOKE_LOG_ASSERT_TIMEOUT:-20}"

PG_IMAGE="${SMOKE_PG_IMAGE:-postgres:16}"
REDIS_IMAGE="${SMOKE_REDIS_IMAGE:-redis:7.4.9}"
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
IDP=shifter-smoke-idp

# --- Local Cognito-shaped OIDC provider double (#988) -----------------------
# Drives the *real* login flow (/login -> authorize -> /oidc/callback ->
# provision -> session) instead of minting a session directly. Auth-domain and
# issuer are distinct Cognito bases, modeled as distinct path prefixes on this
# one local service. Plain HTTP on the private smoke network: the token/JWKS/
# UserInfo backchannel never leaves it, so OIDC_VERIFY_SSL stays at its
# production default and no security posture is weakened for the smoke.
IDP_PORT="${SMOKE_IDP_PORT:-8080}"
STUB_CLIENT_ID=stack-smoke-client
STUB_CLIENT_SECRET=stack-smoke-secret
STUB_AUTH_DOMAIN="http://${IDP}:${IDP_PORT}/auth"
STUB_ISSUER_URL="http://${IDP}:${IDP_PORT}/issuer"
STUB_JWKS_PATH="/issuer/.well-known/jwks.json"
# mozilla-django-oidc builds the redirect URI from the request host + forwarded
# scheme; the login probe addresses the portal as https://${WEB}:8000, so this
# is the exact callback the double must accept.
STUB_REDIRECT_URI="https://${WEB}:8000/oidc/callback/"
# Fixed synthetic identity the double mints (matches stub_idp.py defaults).
STUB_SUBJECT=stack-smoke-oidc-subject
STUB_EMAIL=stack-smoke-oidc@example.test

# Worker / scheduler set: one "name|heartbeat_file|command" entry per line.
# Default mirrors the production monitored set minimally: one SQS worker (proves
# the cloud-queue abstraction against the local double) plus the CTF scheduler.
read -r -d '' SMOKE_WORKER_SPECS_DEFAULT <<'SPECS' || true
worker-cms|/tmp/worker-cms-heartbeat|python manage.py run_worker --queue cms --wait-time 1
ctf-scheduler|/tmp/ctf-scheduler-heartbeat|python manage.py run_ctf_scheduler --poll-interval 1
ctf-communication-worker|/tmp/ctf-communication-worker-heartbeat|python manage.py drain_ctf_communication_deliveries --loop --interval 1
guacamole-bootstrap-prune|/tmp/guacamole-bootstrap-prune-heartbeat|python manage.py run_guacamole_bootstrap_prune --poll-interval 1
raes-operation-record-prune|/tmp/raes-operation-record-prune-heartbeat|python manage.py run_raes_operation_record_prune --poll-interval 1
SPECS
SMOKE_WORKER_SPECS="${SMOKE_WORKER_SPECS:-$SMOKE_WORKER_SPECS_DEFAULT}"

declare -a WORKER_CONTAINERS=()
# Mode-0600 temp files holding the captured session key; removed in cleanup.
declare -a SESSION_FILES=()

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
    for c in "$MIGRATE" "$WEB" "$IDP" ${WORKER_CONTAINERS[@]+"${WORKER_CONTAINERS[@]}"}; do
      # Redact OIDC authorization-code-flow secrets that can surface in gunicorn
      # request lines / IdP logs (auth code, state, nonce, tokens, session key,
      # client secret) before emitting the bounded log tail (#988).
      docker logs --tail 40 "$c" 2>&1 \
        | sed -E 's/(code|state|nonce|access_token|id_token|sessionid|client_secret)=[^[:space:]&"]*/\1=REDACTED/g' \
        | sed "s/^/[$c] /" || true
    done
  fi
  docker rm -f \
    "$WEB" "$MIGRATE" "$PG" "$REDIS" "$ELASTICMQ" "$IDP" \
    ${WORKER_CONTAINERS[@]+"${WORKER_CONTAINERS[@]}"} >/dev/null 2>&1 || true
  docker network rm "$SMOKE_NETWORK" >/dev/null 2>&1 || true
  rm -f ${SESSION_FILES[@]+"${SESSION_FILES[@]}"} >/dev/null 2>&1 || true
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
  # entrypoint.sh emits "Skipping migrations" before it execs the server, so a
  # running, healthy container has already logged it. But docker log delivery
  # for that early line can lag the readiness probe on a busy runner, so a
  # single-shot `docker logs | grep` the instant /health flips to 200 is racy.
  # Poll (bounded, like wait_for): a genuine SKIP_MIGRATIONS break makes the
  # entrypoint log "Running migrations" instead, so the line never appears and
  # this still fails; only the delivery race is absorbed.
  local deadline=$((SECONDS + SMOKE_LOG_ASSERT_TIMEOUT))
  while (( SECONDS < deadline )); do
    if docker logs "$container" 2>&1 | grep -q "Skipping migrations"; then
      return 0
    fi
    sleep 1
  done
  fail "${container} did not skip migrations (SKIP_MIGRATIONS contract broken)"
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

assert_oidc_user_absent() {
  # First-login provisioning is only *proven* if the account does not pre-exist:
  # a stale row would let a broken provisioning path pass silently (#988).
  if ! docker exec -e "EXPECT_EMAIL=${STUB_EMAIL}" "$WEB" python manage.py shell -c '
import os, sys
from django.contrib.auth import get_user_model
if get_user_model().objects.filter(email__iexact=os.environ["EXPECT_EMAIL"]).exists():
    print("OIDC login user exists before the flow ran (stale state)", file=sys.stderr)
    sys.exit(1)
'; then
    fail "OIDC login user already exists before login (cannot prove first-login provisioning)"
  fi
}

assert_oidc_user_provisioned() {
  # Prove the callback provisioned exactly one user + one UserProfile bound to
  # the verified (issuer, subject) — not a directly written setup row (#988).
  if ! docker exec \
    -e "EXPECT_EMAIL=${STUB_EMAIL}" \
    -e "EXPECT_SUB=${STUB_SUBJECT}" \
    -e "EXPECT_ISS=${STUB_ISSUER_URL}" \
    "$WEB" python manage.py shell -c '
import os, sys
from django.contrib.auth import get_user_model
from management.models import UserProfile
users = list(get_user_model().objects.filter(email__iexact=os.environ["EXPECT_EMAIL"]))
if len(users) != 1:
    print(f"expected exactly one OIDC user, found {len(users)}", file=sys.stderr)
    sys.exit(1)
profile = getattr(users[0], "profile", None)
if profile is None:
    print("provisioned OIDC user has no UserProfile", file=sys.stderr)
    sys.exit(1)
if profile.cognito_sub != os.environ["EXPECT_SUB"] or profile.issuer != os.environ["EXPECT_ISS"]:
    print("UserProfile is not bound to the verified (issuer, subject)", file=sys.stderr)
    sys.exit(1)
if UserProfile.objects.filter(cognito_sub=os.environ["EXPECT_SUB"]).count() != 1:
    print("verified subject is bound to more than one profile", file=sys.stderr)
    sys.exit(1)
'; then
    fail "first-login OIDC provisioning did not produce the expected user + bound profile"
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

# Local OIDC provider double (#988). Runs the stub under the built portal image's
# interpreter (reusing its in-image PyJWT/cryptography); the script is bind-
# mounted read-only and needs no cloud access.
log "Starting the local OIDC provider double"
docker run -d --name "$IDP" --network "$SMOKE_NETWORK" \
  -v "${SCRIPT_DIR}:/smoke:ro" --entrypoint python \
  "$SMOKE_IMAGE" /smoke/stub_idp.py \
  --host 0.0.0.0 --port "$IDP_PORT" \
  --issuer "$STUB_ISSUER_URL" --auth-domain "$STUB_AUTH_DOMAIN" \
  --client-id "$STUB_CLIENT_ID" --client-secret "$STUB_CLIENT_SECRET" \
  --redirect-uri "$STUB_REDIRECT_URI" \
  --subject "$STUB_SUBJECT" --email "$STUB_EMAIL" >/dev/null

wait_for 60 "postgres" docker exec "$PG" pg_isready -U "$DB_USER" -d "$DB_NAME"
wait_for 60 "redis" docker exec "$REDIS" redis-cli ping
wait_for 30 "oidc provider double (JWKS)" docker exec "$IDP" \
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${IDP_PORT}${STUB_JWKS_PATH}', timeout=2)"

# Common runtime env: enough to satisfy production settings import and the real
# entrypoint without any cloud access. Mirrors deploy_portal.sh env names.
declare -a common_env=(
  -e ENVIRONMENT=production
  # Production settings now resolve + validate the active cloud backend at import
  # (config._runtime_env.resolve_cloud_provider, PLAT-2005) and fail closed when
  # CLOUD_PROVIDER is absent, exactly as a real deploy must set it. The smoke boots
  # the AWS-shaped runtime (ElasticMQ/SQS, boto3 endpoint), so it mirrors the AWS
  # deploy by supplying the backend identity explicitly.
  -e CLOUD_PROVIDER=aws
  -e "DB_HOST=${PG}" -e DB_PORT=5432 -e "DB_NAME=${DB_NAME}" -e "DB_USER=${DB_USER}" -e "DB_PASSWORD=${DB_PASSWORD}"
  -e "DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}"
  -e "FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY}"
  -e "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,${WEB}"
  # Point the real OIDC backend at the local Cognito-shaped provider double
  # (#988) so the built image exercises the real authorization-code flow rather
  # than a directly minted session. Auth-domain and issuer stay distinct bases.
  -e "OIDC_RP_CLIENT_ID=${STUB_CLIENT_ID}"
  -e "OIDC_RP_CLIENT_SECRET=${STUB_CLIENT_SECRET}"
  -e "OIDC_ISSUER_URL=${STUB_ISSUER_URL}"
  -e "OIDC_AUTH_DOMAIN=${STUB_AUTH_DOMAIN}"
  # Production settings require EMAIL_BACKEND to be explicit (config/_email.py);
  # real deploys pass it from rendered config. The smoke sends no mail, so use
  # the console backend (the same value config/_email.py uses as its dev default)
  # to satisfy the production import without any ESP/SES dependency.
  -e EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
  -e "REDIS_HOST=${REDIS}" -e REDIS_PORT=6379
  -e CHANNEL_LAYER_BACKEND=redis
  # The shared notification websocket (SMOKE_WS_PATH) is parked by default
  # (#941); enable it here so the ws_handshake probe has a routed consumer to
  # accept through the real ASGI stack. This exercises the enabled path in the
  # built image, not the production default.
  -e WEBSOCKET_NOTIFICATIONS_ENABLED=true
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

log "Establishing an authenticated session via the real OIDC login flow"
# Replaces the #922 direct-session mint with the real authorization-code flow
# against the local IdP double, so a regression in OIDC config, the callback,
# first-login provisioning, or session establishment fails the smoke. Prove the
# account does not exist yet: first-login provisioning must be what creates it
# (a stale row would be a false pass).
assert_oidc_user_absent

# Drive /login/ -> authorize -> /oidc/callback/ from inside the network, so the
# probe reaches both the portal and the IdP by name and follows the redirect
# chain like a browser. Only the session key reaches stdout; write it to a
# mode-0600 file whose *path* (never the value) is handed to the probes.
session_file="$(mktemp)"
chmod 600 "$session_file"
SESSION_FILES+=("$session_file")
session_key="$(
  docker run --rm --network "$SMOKE_NETWORK" \
    -v "${SCRIPT_DIR}:/smoke:ro" --entrypoint python \
    "$SMOKE_IMAGE" /smoke/oidc_login.py \
    --portal-origin "https://${WEB}:8000" \
    --portal-transport "http://${WEB}:8000" \
    --protected-path /dashboard/
)"
[[ -n "$session_key" ]] || fail "real OIDC login flow did not establish a session"
printf '%s' "$session_key" > "$session_file"

# Prove first-login provisioning resulted from the callback: exactly one Django
# user + one UserProfile bound to the verified (issuer, subject).
assert_oidc_user_provisioned
note "First-login provisioning verified (one user + bound profile)"

log "Proving authenticated websocket handshake through the real ASGI stack"
# Reuses the callback-established session (no directly minted fallback).
uv run --with 'websockets==12.0' python "${SCRIPT_DIR}/ws_handshake.py" \
  --url "ws://127.0.0.1:${SMOKE_WEB_PORT}/${SMOKE_WS_PATH}" \
  --session-file "$session_file" \
  --origin "http://localhost"

log "Asserting authenticated page renders and static assets resolve"
# Reuses the same callback-established session. Catches the June container-runtime
# class (missing terminal sourcemaps / static assets) the source-tree tests miss.
python3 "${SCRIPT_DIR}/page_smoke.py" \
  --base "http://127.0.0.1:${SMOKE_WEB_PORT}" \
  --session-file "$session_file" \
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

log "Stack smoke PASSED: built image boots, /health 200, real OIDC login + first-login provisioning, websocket OPEN, worker heartbeats present"
