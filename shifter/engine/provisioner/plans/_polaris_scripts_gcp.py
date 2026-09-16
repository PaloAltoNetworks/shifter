"""GCP-specific bash bootstrap-script templates for the POLARIS range plan.

Split out of ``_polaris_scripts.py`` (Sonar S104 file-length): the AWS scripts
(S3 fetch, Bedrock shard) stay there; the GCE twins (GCS fetch, Vertex shard)
live here. :class:`PolarisRangeBootstrapPlan` selects the provider-appropriate
set. Keeping the large embedded bash split by provider keeps both modules under
the Sonar line budget without changing the plan's public surface.
"""

# GCP-only Compose fragment injected into the shared range bootstrap before
# a14-kali is created. Docker owns /etc/hosts and regenerates it on restart, so
# direct in-container writes are not durable. extra_hosts keeps the restricted
# OAuth and Vertex routes present across ordinary container restarts.
GCP_AGENT_COMPOSE_BLOCK = (
    "\n    volumes:"
    "\n      - /opt/polaris/libexec/polaris-splice-credential.py:/usr/local/libexec/polaris-splice-credential.py:ro"
    "\n    extra_hosts:"
    '\n      - "oauth2.googleapis.com:199.36.153.8"'
    '\n      - "aiplatform.googleapis.com:199.36.153.8"'
    '\n      - "us-central1-aiplatform.googleapis.com:199.36.153.8"'
)


# GCE twin of FETCH_POLARIS_TESTS_SCRIPT. Pulls the tests/ tree from a
# provisioner-minted, short-lived, generation-bound V4 signed download URL
# (agent_assets.get_polaris_tests_presigned_url) instead of using the range-host
# SA's ADC. The range host is participant-controllable, so it holds NO Cloud
# Storage identity: a project-level objectViewer let a rooted guest read across
# tenants (#1644). `curl -sSfL` keeps the URL out of step stdout; nothing here
# handles credentials or reaches the metadata server.
FETCH_POLARIS_TESTS_SCRIPT_GCS = """#!/bin/bash
set -euo pipefail

PRESIGNED_URL="{{ polaris_tests_url }}"
DEST_ROOT="/opt/polaris/scenario-dev/polaris"
TARBALL="/tmp/polaris-tests.tar.gz"
# The signed URL is minted before the guest channel opens and expires after
# 900s (agent_assets._POLARIS_TESTS_URL_EXPIRY_SECONDS); the polaris_fetch_tests
# SetupStep caps this whole script at 120s. Keep the total connect+transfer+
# backoff budget well inside both so a retry never operates on an already-expired
# capability: 3 attempts * 30s max-time + (5s + 10s) backoff = ~105s worst case.
max_retries=3
retry_delay_seconds=5

mkdir -p "$DEST_ROOT"

last_error=""
for attempt in $(seq 1 "$max_retries"); do
  if curl -sSfL --connect-timeout 15 --max-time 30 -o "$TARBALL" "$PRESIGNED_URL"; then
    break
  fi
  last_error="curl failed on attempt $attempt"
  if [[ "$attempt" -lt "$max_retries" ]]; then
    delay=$((retry_delay_seconds * (2 ** (attempt - 1))))
    echo "polaris tests fetch: download attempt $attempt failed, retrying in ${delay}s" >&2
    rm -f "$TARBALL"
    sleep "$delay"
  fi
done

if [[ ! -s "$TARBALL" ]]; then
  echo "polaris tests fetch: tarball was not downloaded (${last_error:-empty file})" >&2
  exit 1
fi

# Clear any stale tests/ from a previous bootstrap before extracting.
rm -rf "$DEST_ROOT/tests"

tar xzf "$TARBALL" -C "$DEST_ROOT"

if [[ ! -x "$DEST_ROOT/tests/run-all-smoketests.sh" ]]; then
  echo "polaris tests fetch: run-all-smoketests.sh missing after extract" >&2
  ls -la "$DEST_ROOT/tests" >&2 || true
  exit 1
fi

find "$DEST_ROOT/tests" -type f \\( -name '*.sh' -o -name '*.py' \\) -exec chmod +x {} +

echo "polaris tests fetch: tests/ tree materialised at $DEST_ROOT/tests"
ls "$DEST_ROOT/tests/smoketests" | wc -l | xargs -I{} echo "polaris tests fetch: {} smoketest files available"
exit 0
"""


# GCE twin of KALI_BEDROCK_SHARD_SCRIPT. Configures Claude Code inside the
# a14-kali container to talk to Vertex AI instead of AWS Bedrock, using a
# per-range Vertex-only service-account key (minted by the range-cell backend,
# stored in Secret Manager) injected as a key file.
#
# Security boundary (issue #1342 codex security review): a14-kali is
# participant-facing, so it MUST NOT reach the GCE metadata server. If it could,
# a participant with shell in the container could mint the broader range-host SA
# token. This step blocks every container from 169.254.169.254 and gives
# a14-kali only the per-range Vertex key (scoped to Vertex, revoked with the
# range). The host keeps metadata access for gcloud (DOCKER-USER filters
# forwarded container traffic only). The key is fetched host-side and never
# transits process argv or logs.
KALI_VERTEX_SHARD_SCRIPT = """#!/bin/bash
set -euo pipefail

RANGE_ID="{{ range_id }}"
VERTEX_PROJECT_ID="{{ vertex_project_id }}"
VERTEX_REGION="{{ vertex_region }}"
VERTEX_SECRET_PROJECT_ID="{{ vertex_secret_project_id }}"
VERTEX_SECRET_ID="{{ vertex_secret_id }}"
ANTHROPIC_MODEL="{{ anthropic_model }}"
ANTHROPIC_SMALL_FAST_MODEL="{{ anthropic_small_fast_model }}"

if [[ -z "$VERTEX_PROJECT_ID" || -z "$VERTEX_REGION" ||
      -z "$VERTEX_SECRET_PROJECT_ID" || -z "$VERTEX_SECRET_ID" ]]; then
  echo "polaris kali vertex shard: Vertex API and secret location context are required" >&2
  exit 2
fi

# 1. Block containers from the metadata server (participant exfil path). The
# host itself is unaffected (DOCKER-USER filters forwarded traffic only).
if ! iptables -C DOCKER-USER -d 169.254.169.254/32 -j DROP 2>/dev/null; then
  iptables -I DOCKER-USER -d 169.254.169.254/32 -j DROP
fi

# 2. Fetch the per-range Vertex key from Secret Manager (host SA has
# secretAccessor) and inject it into a14-kali as a key file. No key material in
# argv/logs.
KEY_FILE="$(mktemp)"
ERRF="$(mktemp)"
chmod 600 "$KEY_FILE"
cleanup_vertex_key() {
  shred -u "$KEY_FILE" 2>/dev/null || rm -f "$KEY_FILE"
  rm -f "$ERRF"
}
trap cleanup_vertex_key EXIT
if ! gcloud secrets versions access latest \
    --secret="$VERTEX_SECRET_ID" \
    --project="$VERTEX_SECRET_PROJECT_ID" >"$KEY_FILE" 2>"$ERRF"; then
  echo "polaris kali vertex shard: could not read the scoped Vertex credential" >&2
  rm -f "$KEY_FILE" "$ERRF"
  exit 2
fi
rm -f "$ERRF"
docker exec a14-kali mkdir -p /etc/vertex
docker cp "$KEY_FILE" a14-kali:/etc/vertex/key.json
# Own the key by the kali user (the agent runs as kali, not root) so
# GOOGLE_APPLICATION_CREDENTIALS is readable; keep it private to that user.
docker exec a14-kali chown kali:kali /etc/vertex /etc/vertex/key.json
docker exec a14-kali chmod 600 /etc/vertex/key.json
cleanup_vertex_key
trap - EXIT

# 3. Point Claude Code at Vertex using the injected key (ADC via key file, not
# the metadata server).
PROFILE_FILE="$(mktemp)"
chmod 600 "$PROFILE_FILE"
cat > "$PROFILE_FILE" <<PROFILE_EOF
# Managed by polaris_range_bootstrap KaliVertexShard step - do not edit manually.
export CLAUDE_CODE_USE_VERTEX=1
export CLOUD_ML_REGION=$VERTEX_REGION
export ANTHROPIC_VERTEX_PROJECT_ID=$VERTEX_PROJECT_ID
export GOOGLE_APPLICATION_CREDENTIALS=/etc/vertex/key.json
export ANTHROPIC_MODEL=$ANTHROPIC_MODEL
export ANTHROPIC_SMALL_FAST_MODEL=$ANTHROPIC_SMALL_FAST_MODEL
PROFILE_EOF
docker cp "$PROFILE_FILE" a14-kali:/etc/profile.d/claude-vertex.sh
docker exec a14-kali chmod 644 /etc/profile.d/claude-vertex.sh
rm -f "$PROFILE_FILE"

# Polaris intentionally denies general internet DNS/egress. Route only the
# Google OAuth and Vertex endpoints over Private Google Access so Claude Code
# can exchange its scoped service-account credential and call Vertex without
# opening participant internet access. The global API hostname is required by
# Sonnet 4.6; keep the regional hostname for explicit operator overrides.
PRIVATE_GOOGLE_API_VIP=199.36.153.8
for api_host in \
  oauth2.googleapis.com \
  aiplatform.googleapis.com \
  "${VERTEX_REGION}-aiplatform.googleapis.com"; do
  docker exec a14-kali sh -c \
    "grep -v '[[:space:]]${api_host}$' /etc/hosts > /tmp/hosts.shifter || true; \
     cat /tmp/hosts.shifter > /etc/hosts; \
     printf '%s %s\\n' '$PRIVATE_GOOGLE_API_VIP' '$api_host' >> /etc/hosts; \
     rm -f /tmp/hosts.shifter"
  resolved=$(docker exec a14-kali getent ahostsv4 "$api_host" | awk 'NR==1 {print $1}')
  if [[ "$resolved" != "$PRIVATE_GOOGLE_API_VIP" ]]; then
    echo "polaris kali vertex shard: $api_host resolved to $resolved, expected Private Google Access VIP" >&2
    exit 2
  fi
done

echo "polaris kali vertex shard: config applied (per-range key, metadata blocked)"
"""
