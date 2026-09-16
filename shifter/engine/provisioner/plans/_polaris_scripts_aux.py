"""Auxiliary bash script templates for the POLARIS range plan.

Split out of ``_polaris_scripts.py`` (Sonar S104 file-length): the main range
bootstrap script stays there, while the post-bootstrap helpers -- fetching the
smoketest tree, installing the splice watcher, and verifying the bootstrap --
live here. ``polaris_range_bootstrap.py`` imports them back, so the plan's
public surface is unchanged.
"""

# Pulls the latest scenario-dev/polaris/tests/ tree out of S3 and unpacks it
# under /opt/polaris/scenario-dev/polaris/tests/. The polaris-vm AMI bakes
# only the build/ subtree (docker compose stack), not the tests/ subtree,
# so the organizer-facing smoketest harness otherwise isn't available on
# freshly provisioned ranges. This step materialises it on every range so
# `bash /opt/polaris/scenario-dev/polaris/tests/run-all-smoketests.sh`
# works out-of-the-box without any per-range manual upload.
#
# The bucket + prefix are rendered from the provisioner environment. By default
# this uses AGENT_S3_BUCKET because the dev-range-range-instance IAM role is
# already granted GetObject there. A new tarball is uploaded by the operator
# whenever the test harness or an individual smoketest is fixed; the download
# is idempotent so re-runs pick up the latest.
FETCH_POLARIS_TESTS_SCRIPT = """#!/bin/bash
set -euo pipefail

BUCKET="{{ polaris_tests_bucket }}"
KEY="{{ polaris_tests_key }}"
DEST_ROOT="/opt/polaris/scenario-dev/polaris"
TARBALL="/tmp/polaris-tests.tar.gz"

mkdir -p "$DEST_ROOT"

# aws cli is preinstalled on the polaris-vm AMI base. It picks up the
# EC2 instance profile automatically via IMDSv2, so no explicit creds.
aws s3 cp "s3://$BUCKET/$KEY" "$TARBALL" --region us-east-2

if [[ ! -s "$TARBALL" ]]; then
  echo "polaris tests fetch: downloaded tarball is empty" >&2
  exit 1
fi

# Clear any stale tests/ from a previous bootstrap before extracting,
# so removed test files don't linger.
rm -rf "$DEST_ROOT/tests"

tar xzf "$TARBALL" -C "$DEST_ROOT"

if [[ ! -x "$DEST_ROOT/tests/run-all-smoketests.sh" ]]; then
  echo "polaris tests fetch: run-all-smoketests.sh missing after extract" >&2
  ls -la "$DEST_ROOT/tests" >&2 || true
  exit 1
fi

# Make every script in tests/ executable (tar may not preserve +x on a
# subset of *.py files depending on how the tarball was built).
find "$DEST_ROOT/tests" -type f \\( -name '*.sh' -o -name '*.py' \\) -exec chmod +x {} +

echo "polaris tests fetch: tests/ tree materialised at $DEST_ROOT/tests"
ls "$DEST_ROOT/tests/smoketests" | wc -l | xargs -I{} echo "polaris tests fetch: {} smoketest files available"
exit 0
"""

# Installs the splice watcher as a systemd service. The watcher polls
# A5's /api/status for `runaway_complete` and, when the participant
# earns flag 19 (generator meltdown), attaches a14-kali to the
# splice-link docker network so the A14 -> A9 pivot opens. At range
# start A14 is NOT on splice-link (the preceding bootstrap step runs
# `docker network disconnect splice-link a14-kali` to strip the baked
# compose pre-wiring), so until the watcher fires the bunker-ot path
# is sealed.
#
# Both the watcher script and the systemd unit are written from here —
# nothing is read from the baked build/ tree — so pushing provisioner
# code changes propagates to every new range without an AMI rebake.
# Idempotent: safe to re-run on bootstrap retries.
INSTALL_SPLICE_WATCHER_SCRIPT = """#!/bin/bash
set -euo pipefail

WATCHER="/usr/local/bin/polaris-splice-watcher.sh"
UNIT="/etc/systemd/system/polaris-splice-watcher.service"

# Quoted heredoc delimiter prevents host-side shell expansion — the
# watcher's shell vars and command substitutions are interpreted at
# watcher runtime, not now. Uses Go template tokens (docker --format);
# those all carry a leading dot, so the orchestrator's Jinja regex
# (which matches word-chars-only between the double-brace delimiters)
# leaves them untouched. No bare word-only tokens appear inside the
# braces anywhere in this heredoc — those would be matched and
# treated as missing template variables by the renderer.
cat > "$WATCHER" <<'WATCHER_EOF'
#!/bin/bash
# polaris-splice-watcher: poll A5 HMI state; when the generator goes
# into thermal runaway (flag 19 earned), attach a14-kali to the
# splice-link docker network so the participant can reach a9-splice.
set -euo pipefail

# A5 container_name in scenario-dev/polaris/build/docker-compose.yml is
# "a5-scada" — verified empirically. Earlier "a5-scada-generator" default
# was the source of a silent failure at BSides Ottawa (2026-04): the
# watcher polled a non-existent container, never observed
# runaway_complete=true, never attached A14 to splice-link, and
# operators had to manually `docker network connect` per participant.
A5_CONTAINER="${A5_CONTAINER:-a5-scada}"
KALI_CONTAINER="${KALI_CONTAINER:-a14-kali}"
# Compose network name is "<project>_splice-link"; the compose project
# lives at /opt/polaris/scenario-dev/polaris/build so project name is
# "build" by default. Allow env override for local testing.
SPLICE_NETWORK="${SPLICE_NETWORK:-build_splice-link}"
SPLICE_IP="${SPLICE_IP:-172.20.60.140}"
POLL_INTERVAL_S="${POLL_INTERVAL_S:-10}"

poll_runaway_complete() {
  local body
  local py_script='import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:8080/api/status", timeout=5).read().decode())'
  body=$(docker exec "$A5_CONTAINER" python3 -c "$py_script" 2>/dev/null) || return 1
  [[ "$body" == *'"runaway_complete": true'* ]] || [[ "$body" == *'"runaway_complete":true'* ]]
}

is_connected() {
  # Dot-prefixed Go template fields pass through the orchestrator's
  # Jinja regex untouched.
  docker inspect "$KALI_CONTAINER" \
    --format '{{json .NetworkSettings.Networks}}' 2>/dev/null \
    | grep -q "\\"$SPLICE_NETWORK\\""
}

connect_splice() {
  echo "polaris-splice-watcher: connecting $KALI_CONTAINER to $SPLICE_NETWORK ($SPLICE_IP)"
  docker network connect --ip "$SPLICE_IP" "$SPLICE_NETWORK" "$KALI_CONTAINER"
}

echo "polaris-splice-watcher: starting (network=$SPLICE_NETWORK, container=$KALI_CONTAINER)"

while true; do
  if poll_runaway_complete; then
    if ! is_connected; then
      if connect_splice; then
        echo "polaris-splice-watcher: splice established"
      else
        echo "polaris-splice-watcher: connect failed, will retry" >&2
      fi
    fi
  fi
  sleep "$POLL_INTERVAL_S"
done
WATCHER_EOF
chmod +x "$WATCHER"

cat > "$UNIT" <<UNIT_EOF
[Unit]
Description=Polaris splice watcher (attaches a14-kali to splice-link on flag 19)
After=docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=$WATCHER
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT_EOF

systemctl daemon-reload
systemctl enable polaris-splice-watcher.service
systemctl restart polaris-splice-watcher.service

echo "polaris splice watcher: installed and started"
exit 0
"""


# DC. If any check fails, the plan is reported as failed and the range
# provisioner aborts. The dig query runs from inside a14-kali because
# the alpine `bind` package on the dns container ships only the daemon
# (named) — `dig` lives in the separate `bind-tools` package and is not
# installed there. a14-kali has dig + ldap-utils + smbclient pre-baked
# and points its /etc/resolv.conf at the dns container by default, so
# `docker exec a14-kali dig` exercises the real participant resolution
# path end-to-end.
#
# Shared by both providers (checks 1-6). #1377 slice 5 adds AWS-only checks
# 7-11 (metadata firewall, STS refresh, per-range caller identity, Bedrock
# smoke invocation, IMDS denial) as a *separate* provider-selected constant
# (VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS below) built from this shared body, so
# the GCP verify step -- this constant -- never changes by a single byte.
VERIFY_POLARIS_BOOTSTRAP_COMMON = """#!/bin/bash
set -euo pipefail

DC_IP="{{ dc_ip }}"

# 1. a14-kali container is running.
if ! docker ps --format '{{.Names}}' | grep -qx 'a14-kali'; then
  echo "polaris verify: a14-kali is not running" >&2
  exit 1
fi

# 2. dns container is running.
if ! docker ps --format '{{.Names}}' | grep -qx 'dns'; then
  echo "polaris verify: dns is not running" >&2
  exit 1
fi

# 3. dns container resolves dc01.boreas.local to THIS range's DC IP.
#    Query from inside a14-kali because the alpine `bind` package on the
#    dns container does not include dig (it's in the separate `bind-tools`
#    package). a14-kali points at the dns container via docker compose's
#    bridge DNS, so this exercises the real participant lookup path.
resolved=$(docker exec a14-kali dig +short dc01.boreas.local || true)
if [[ "$resolved" != "$DC_IP" ]]; then
  echo "polaris verify: dc01.boreas.local resolved to '$resolved', expected '$DC_IP'" >&2
  exit 1
fi

# 4. a14-kali has the per-instance kali pubkey installed.
if ! docker exec a14-kali test -s /home/kali/.ssh/authorized_keys; then
  echo "polaris verify: a14-kali /home/kali/.ssh/authorized_keys is missing or empty" >&2
  exit 1
fi

# 4a. The shared host helper checks the complete projection contract: regular
# files, numeric ownership, modes, converged SSH config, A14/A9 key-pair match,
# and (when the splice network is open) a real non-interactive SSH connection.
if ! /opt/polaris/libexec/polaris-splice-credential.py host-check --container a14-kali; then
  echo "polaris verify: splice credential contract failed" >&2
  exit 1
fi

# 5. a14-kali is NOT on splice-link at range start (the watcher attaches
#    it only after flag 19 is earned). Inspect the container directly
#    with a dot-prefixed Go template so the orchestrator's Jinja
#    placeholder regex does not collide (see comments above).
a14_nets=$(docker inspect a14-kali --format '{{json .NetworkSettings.Networks}}' 2>/dev/null || true)
if echo "$a14_nets" | grep -q '"[a-z0-9_-]*splice-link"'; then
  echo "polaris verify: a14-kali is already on splice-link at boot (should attach only after flag 19)" >&2
  exit 1
fi

# 6. splice watcher service is active.
if ! systemctl is-active --quiet polaris-splice-watcher.service; then
  echo "polaris verify: polaris-splice-watcher.service is not active" >&2
  systemctl status polaris-splice-watcher.service --no-pager >&2 || true
  exit 1
fi
"""

VERIFY_POLARIS_BOOTSTRAP_SCRIPT = (
    VERIFY_POLARIS_BOOTSTRAP_COMMON
    + """
echo "polaris verify: dc01 -> $resolved, kali key installed, splice gated, watcher active"
exit 0
"""
)
