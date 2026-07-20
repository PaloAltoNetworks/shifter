"""Bash bootstrap-script templates for the POLARIS range plan.

Extracted from ``polaris_range_bootstrap.py`` (Sonar S104). These are the SSM
RunCommand script bodies that :class:`PolarisRangeBootstrapPlan` injects as its
setup steps; keeping the large embedded bash in its own module keeps the plan
module under the Sonar line budget. The plan module imports them back, so its
public surface is unchanged.
"""

# Bash run on the polaris VM Ubuntu host via SSM. Rewrites the bake-time
# docker-compose.override.yml with this range's DC IP + per-instance kali
# pubkey, then force-recreates the dns + a14-kali containers so their
# entrypoints pick up the new env vars and re-render their internal state.
POLARIS_RANGE_BOOTSTRAP_SCRIPT = """#!/bin/bash
set -euo pipefail

DC_IP="{{ dc_ip }}"
KALI_PUBKEY="{{ public_key }}"

if [[ -z "$DC_IP" ]]; then
  echo "polaris bootstrap: DC_IP is empty, refusing to rewrite override" >&2
  exit 1
fi
if [[ -z "$KALI_PUBKEY" ]]; then
  echo "polaris bootstrap: KALI_PUBKEY is empty, refusing to rewrite override" >&2
  exit 1
fi
{{ aws_agent_setup_block }}
cd /opt/polaris/scenario-dev/polaris/build

# Per-range Ed25519 keypair for the A9 splice-relay credential gate
# (#707). The private half is staged on a14-kali via the entrypoint
# (`KALI_SPLICE_PRIVATE_KEY_B64`, base64 so the value stays single-line
# inside the compose override); the public half is installed into
# a9-splice's /root/.ssh/authorized_keys via A9_AUTHORIZED_KEY. A9's
# sshd has PasswordAuthentication off (Dockerfile change), so this key
# is the only path to the Bunker OT controllers. Per-range generation
# means an exfil from one participant's a14-kali cannot be used to
# attack another range — even though ranges are network-isolated, the
# key is treated as scenario credential material with least exposure.
SPLICE_KEY_DIR="$(mktemp -d)"
chmod 700 "$SPLICE_KEY_DIR"
ssh-keygen -t ed25519 -N "" -C "splice-relay@$(date -u +%Y%m%dT%H%M%SZ)" \
    -f "$SPLICE_KEY_DIR/splice_relay" -q
SPLICE_PRIVATE_KEY_B64="$(base64 -w0 < "$SPLICE_KEY_DIR/splice_relay")"
SPLICE_PUBLIC_KEY="$(cat "$SPLICE_KEY_DIR/splice_relay.pub")"
shred -u "$SPLICE_KEY_DIR/splice_relay" "$SPLICE_KEY_DIR/splice_relay.pub" 2>/dev/null \
    || rm -f "$SPLICE_KEY_DIR/splice_relay" "$SPLICE_KEY_DIR/splice_relay.pub"
rmdir "$SPLICE_KEY_DIR"

# Atomic rewrite via tmp + mv so docker compose never sees a partial file.
cat > docker-compose.override.yml.new <<COMPOSE_EOF
services:
  a14-kali:
    ports:
      - "22:22"
      - "3389:3389"
    environment:
      KALI_AUTHORIZED_KEY: "$KALI_PUBKEY"
      KALI_SPLICE_PRIVATE_KEY_B64: "$SPLICE_PRIVATE_KEY_B64"{{ aws_agent_compose_block }}
  a9-splice:
    environment:
      A9_AUTHORIZED_KEY: "$SPLICE_PUBLIC_KEY"
  dns:
    environment:
      DC01_IP: "$DC_IP"
COMPOSE_EOF
mv docker-compose.override.yml.new docker-compose.override.yml

# Force-recreate only the containers whose env vars changed. The other
# 14 stay running undisturbed. a9-splice was added in #707 because the
# A9 entrypoint now consumes A9_AUTHORIZED_KEY.
docker compose up -d --force-recreate dns a14-kali a9-splice

# The baked compose attaches a14-kali to splice-link at container start
# (legacy pre-gate wiring). Strip that here — the splice landing is gated
# on flag 19 via the polaris-splice-watcher systemd service, which will
# reattach a14-kali once A5 reports runaway_complete. Docker compose
# prefixes network names with the project name (here: "build"), so the
# actual name is "build_splice-link"; discover by suffix to stay robust
# against project-name changes. Non-fatal if already disconnected.
splice_net_name=$(docker network ls --format '{{.Name}}' | grep -E '(^|_)splice-link$' | head -n1 || true)
if [[ -n "$splice_net_name" ]]; then
  docker network disconnect "$splice_net_name" a14-kali 2>/dev/null || true
fi

# Wait up to 60s for the three recreated containers to be Up before
# declaring success.
# `docker ps --format` uses Go template syntax (e.g. .Names, .Status)
# inside double-brace delimiters. The orchestrator's render pass uses a
# regex that requires word characters between the delimiters, so Go
# template tokens with a leading dot pass through untouched. (Don't
# describe Jinja-style placeholders inline in this comment — the
# renderer would see them too and demand a substitution variable.)
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  ps_out=$(docker ps --format '{{.Names}} {{.Status}}' || true)
  a14_up=$(echo "$ps_out" | grep -c '^a14-kali .*Up' || true)
  dns_up=$(echo "$ps_out" | grep -c '^dns .*Up' || true)
  a9_up=$(echo "$ps_out" | grep -c '^a9-splice .*Up' || true)
  if [[ "$a14_up" == "1" && "$dns_up" == "1" && "$a9_up" == "1" ]]; then
    echo "polaris bootstrap: a14-kali + dns + a9-splice up after attempt $attempt"
    break
  fi
  sleep 5
done

# Verify the kali container actually has the per-instance pubkey written
# (the a14 entrypoint reads $KALI_AUTHORIZED_KEY and writes the file).
for attempt in 1 2 3 4 5; do
  if docker exec a14-kali test -s /home/kali/.ssh/authorized_keys 2>/dev/null; then
    echo "polaris bootstrap: kali authorized_keys present"
    break
  fi
  sleep 3
done

# Verify the splice key staging (#707): private key on a14-kali, public
# key in a9-splice. The Bunker chain depends on both.
for attempt in 1 2 3 4 5; do
  splice_priv_ok=0
  splice_pub_ok=0
  docker exec a14-kali test -s /home/kali/.ssh/splice_relay 2>/dev/null && splice_priv_ok=1
  docker exec a9-splice test -s /root/.ssh/authorized_keys 2>/dev/null && splice_pub_ok=1
  if [[ "$splice_priv_ok" == "1" && "$splice_pub_ok" == "1" ]]; then
    echo "polaris bootstrap: splice key staged on a14-kali and a9-splice"
    break
  fi
  sleep 3
done

echo "polaris bootstrap: complete"
exit 0
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

# 4a. Splice-relay credential gate (#707): private key staged on a14-kali
#     and matching pubkey installed on a9-splice. Without both halves the
#     Bunker chain (flags 31-36) is unreachable post-splice. Mode is also
#     checked on the private key — wrong perms invite client refusal at
#     ssh-time, which masquerades as the original P0 symptom.
if ! docker exec a14-kali test -s /home/kali/.ssh/splice_relay; then
  echo "polaris verify: splice_relay private key missing on a14-kali" >&2
  exit 1
fi
splice_mode=$(docker exec a14-kali stat -c '%a' /home/kali/.ssh/splice_relay 2>/dev/null || echo "")
if [[ "$splice_mode" != "600" ]]; then
  echo "polaris verify: splice_relay private key has wrong mode '$splice_mode' (expected 600)" >&2
  exit 1
fi
if ! docker exec a9-splice test -s /root/.ssh/authorized_keys; then
  echo "polaris verify: a9-splice /root/.ssh/authorized_keys is missing or empty" >&2
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
