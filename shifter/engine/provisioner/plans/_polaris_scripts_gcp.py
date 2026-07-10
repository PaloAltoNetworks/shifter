"""GCP-specific bash bootstrap-script templates for the POLARIS range plan.

Split out of ``_polaris_scripts.py`` (Sonar S104 file-length): the AWS scripts
(S3 fetch, Bedrock shard) stay there; the GCE twins (GCS fetch, Vertex shard)
live here. :class:`PolarisRangeBootstrapPlan` selects the provider-appropriate
set. Keeping the large embedded bash split by provider keeps both modules under
the Sonar line budget without changing the plan's public surface.
"""

# GCE twin of FETCH_POLARIS_TESTS_SCRIPT. Pulls the tests/ tree from a GCS
# bucket instead of S3. The range host VM authenticates with its attached
# service account via Application Default Credentials (metadata server), so no
# explicit keys are handled. `gcloud storage` is preferred with a `gsutil`
# fallback; both ship on the polaris-vm GCE image.
FETCH_POLARIS_TESTS_SCRIPT_GCS = """#!/bin/bash
set -euo pipefail

BUCKET="{{ polaris_tests_bucket }}"
KEY="{{ polaris_tests_key }}"
DEST_ROOT="/opt/polaris/scenario-dev/polaris"
TARBALL="/tmp/polaris-tests.tar.gz"

mkdir -p "$DEST_ROOT"

# ADC via the VM service account; no explicit credentials handled here.
if command -v gcloud >/dev/null 2>&1; then
  gcloud storage cp "gs://$BUCKET/$KEY" "$TARBALL"
elif command -v gsutil >/dev/null 2>&1; then
  gsutil cp "gs://$BUCKET/$KEY" "$TARBALL"
else
  echo "polaris tests fetch: neither gcloud nor gsutil is installed on the range host" >&2
  exit 1
fi

if [[ ! -s "$TARBALL" ]]; then
  echo "polaris tests fetch: downloaded tarball is empty" >&2
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
ANTHROPIC_MODEL="{{ anthropic_model }}"
ANTHROPIC_SMALL_FAST_MODEL="{{ anthropic_small_fast_model }}"
SECRET_ID="shifter-range-${RANGE_ID}-vertex-key"

if [[ -z "$VERTEX_PROJECT_ID" || -z "$VERTEX_REGION" ]]; then
  echo "polaris kali vertex shard: vertex_project_id and vertex_region are required" >&2
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
chmod 600 "$KEY_FILE"
# The per-range secret lives in the VM's own (range-cell) project. Resolve it
# explicitly from the metadata server and pass --project: this step runs as root
# (via sudo) and gcloud in that context does not reliably pick up a default
# project, and — unlike the tarball fetch, which carries a gs:// URL — this
# command has nothing else to infer the project from, so an unset project made
# the access fail with an error that looked like a permission problem.
META_URL="http://metadata.google.internal/computeMetadata/v1/project/project-id"
PROJ="$(curl -s -H 'Metadata-Flavor: Google' "$META_URL")"
ERRF=/tmp/vertex-secret-err
if ! gcloud secrets versions access latest --secret="$SECRET_ID" --project="$PROJ" >"$KEY_FILE" 2>"$ERRF"; then
  echo "polaris kali vertex shard: could not read Vertex key secret $SECRET_ID in project $PROJ" >&2
  cat "$ERRF" >&2 || true
  rm -f "$KEY_FILE" "$ERRF"
  exit 2
fi
docker exec a14-kali mkdir -p /etc/vertex
docker cp "$KEY_FILE" a14-kali:/etc/vertex/key.json
# Own the key by the kali user (the agent runs as kali, not root) so
# GOOGLE_APPLICATION_CREDENTIALS is readable; keep it private to that user.
docker exec a14-kali chown kali:kali /etc/vertex /etc/vertex/key.json
docker exec a14-kali chmod 600 /etc/vertex/key.json
shred -u "$KEY_FILE" 2>/dev/null || rm -f "$KEY_FILE"

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

echo "polaris kali vertex shard: config applied (per-range key, metadata blocked)"
"""
