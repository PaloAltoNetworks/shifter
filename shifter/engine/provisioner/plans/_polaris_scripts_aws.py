"""AWS-specific bash bootstrap-script templates for the POLARIS range plan.

Split out of ``_polaris_scripts.py`` (Sonar S104 file-length): the AWS-only
a14-kali agent-credential scripts (#1377) live here; shared/provider-neutral
scripts stay in ``_polaris_scripts.py``.
"""

from ._polaris_scripts import VERIFY_POLARIS_BOOTSTRAP_COMMON

# AWS-only fragments that POLARIS_RANGE_BOOTSTRAP_SCRIPT substitutes via the
# {{ aws_agent_setup_block }} / {{ aws_agent_compose_block }} template tokens
# (#1377). They are built in Python (not via nested {{ }} tokens) and injected as
# the *value* of a single template token each: _render_script only substitutes
# tokens present in the ORIGINAL template text, so a nested {{ region }} inside an
# injected block would never resolve -- hence the real region / model ids are
# baked in via render_aws_agent_blocks() below. Those values are allowlist-
# validated upstream (config.load_aws_polaris_agent_config, #1377 cycle-2 finding
# 3), so plain substitution into shell/YAML is safe. Because these are plain
# Python strings (not a bash-runtime `if`), GCP -- whose context supplies "" for
# both tokens -- renders byte-for-byte unchanged (see tests/test_bootstrap_plan.py
# TestPolarisAwsAgentSecurity byte-parity assertions).
#
# Durability (#1377 cycle-2 finding 2): everything a14-kali needs to consume the
# per-range STS credential is delivered by read-only bind mounts + the compose
# environment, materialized on the HOST *before* the override is written and the
# container starts. Nothing is written into the container layer, so a
# `docker compose up --force-recreate a14-kali` preserves the whole provider
# configuration, not just the mounted credentials.
_AWS_AGENT_RUN_DIR_SETUP_TEMPLATE = r"""# AWS-only (#1377): materialize all durable a14-kali agent config on the host
# BEFORE the compose override is written and the container starts, so it
# survives docker compose up --force-recreate. Delivered to a14-kali by
# read-only bind mounts + the compose environment (see the compose block),
# never written into the mutable container layer.
mkdir -p /run/shifter-agent
chown root:root /run/shifter-agent
chmod 711 /run/shifter-agent

# credential_process reader: emits the host-refreshed STS JSON the SDK
# consumes. On the mounted dir so a recreate keeps it.
cat > /run/shifter-agent/credential-process.sh <<'READER_EOF'
#!/bin/sh
set -eu
exec cat /run/shifter-agent/credentials.json
READER_EOF
chmod 755 /run/shifter-agent/credential-process.sh
chown root:root /run/shifter-agent/credential-process.sh

# AWS profile pointing at the credential_process reader. a14-kali receives
# AWS_CONFIG_FILE=/run/shifter-agent/aws-config via the compose environment.
# sts_regional_endpoints=regional forces sts.<region> (pinned in extra_hosts)
# over the global sts.amazonaws.com, which a14-kali cannot resolve.
cat > /run/shifter-agent/aws-config <<'AWSCFG_EOF'
[default]
credential_process = /run/shifter-agent/credential-process.sh
region = __AWS_REGION__
sts_regional_endpoints = regional
AWSCFG_EOF
chmod 644 /run/shifter-agent/aws-config
chown root:root /run/shifter-agent/aws-config

# Login-shell env for the participant's interactive Claude Code session.
# docker exec inherits the compose environment, but SSH login shells do not,
# so the Claude/Bedrock exports are ALSO delivered here and bind-mounted to
# /etc/profile.d/claude-bedrock.sh (compose block) so they survive recreate.
cat > /run/shifter-agent/claude-bedrock.sh <<'PROFILE_EOF'
# Managed by polaris_range_bootstrap (#1377) - do not edit manually.
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_SDK_LOAD_CONFIG=1
export AWS_REGION=__AWS_REGION__
export AWS_CONFIG_FILE=/run/shifter-agent/aws-config
export ANTHROPIC_MODEL=__MAIN_MODEL__
export ANTHROPIC_SMALL_FAST_MODEL=__SMALL_MODEL__
PROFILE_EOF
chmod 644 /run/shifter-agent/claude-bedrock.sh
chown root:root /run/shifter-agent/claude-bedrock.sh

# Resolve public AWS service FQDNs (Bedrock for agent inference, STS for the
# per-range agent-role assume/verify) to their VPC-endpoint private IPs host-side
# and publish them to the compose .env, so a14-kali's extra_hosts entries resolve
# the FQDNs on every up/recreate -- durable, unlike an /etc/hosts write into the
# container layer. a14-kali cannot resolve them itself (no IMDS/public egress and
# its scenario DNS does not serve AWS FQDNs).
_ENV_FILE="/opt/polaris/scenario-dev/polaris/build/.env"
touch "$_ENV_FILE"
_pin_endpoint_ip() {  # $1=FQDN  $2=.env var name
  _ip="$(getent hosts "$1" | awk '{print $1; exit}')"
  case "$_ip" in
    10.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*|192.168.*) : ;;
    *) command -v dig >/dev/null 2>&1 && _ip="$(dig +short @169.254.169.253 "$1" | grep -E '^10\.' | head -n1 || true)"
      ;;
  esac
  [ -n "$_ip" ] || { echo "polaris bootstrap: could not resolve $1 to a private IP" >&2; exit 1; }
  grep -v "^$2=" "$_ENV_FILE" > "$_ENV_FILE.tmp" 2>/dev/null || true
  echo "$2=$_ip" >> "$_ENV_FILE.tmp"
  mv "$_ENV_FILE.tmp" "$_ENV_FILE"
}
_pin_endpoint_ip "bedrock-runtime.__AWS_REGION__.amazonaws.com" SHIFTER_BEDROCK_IP
_pin_endpoint_ip "sts.__AWS_REGION__.amazonaws.com" SHIFTER_STS_IP
"""

# Appended after a14-kali's environment in the compose override: Bedrock/
# Claude env, the read-only /run/shifter-agent mount + profile.d shim, and
# the extra_hosts entry for the VPC-endpoint IP the setup block publishes.
_AWS_AGENT_COMPOSE_TEMPLATE = (
    '\n      CLAUDE_CODE_USE_BEDROCK: "1"'
    '\n      AWS_SDK_LOAD_CONFIG: "1"'
    '\n      AWS_REGION: "__AWS_REGION__"'
    '\n      ANTHROPIC_MODEL: "__MAIN_MODEL__"'
    '\n      ANTHROPIC_SMALL_FAST_MODEL: "__SMALL_MODEL__"'
    '\n      AWS_CONFIG_FILE: "/run/shifter-agent/aws-config"'
    "\n    volumes:"
    "\n      - /run/shifter-agent:/run/shifter-agent:ro"
    "\n      - /run/shifter-agent/claude-bedrock.sh:/etc/profile.d/claude-bedrock.sh:ro"
    "\n    extra_hosts:"
    '\n      - "bedrock-runtime.__AWS_REGION__.amazonaws.com:\\${SHIFTER_BEDROCK_IP}"'
    '\n      - "sts.__AWS_REGION__.amazonaws.com:\\${SHIFTER_STS_IP}"'
)


def render_aws_agent_blocks(region: str, main_model: str, small_model: str) -> tuple[str, str]:
    """Return (setup_block, compose_block) with real values baked in.

    ``region`` / ``main_model`` / ``small_model`` are allowlist-validated by
    ``config.load_aws_polaris_agent_config`` before reaching here (#1377 cycle-2
    finding 3), so substituting them into the shell/YAML fragments is safe.
    Building the strings in Python (rather than leaving ``{{ region }}`` tokens
    inside the fragments) is required because these are injected as the value of
    a single template token and ``_render_script`` does not resolve tokens that
    appear only inside an injected value.
    """

    def _fill(template: str) -> str:
        """Substitute the region/model sentinels in one fragment."""
        return (
            template.replace("__AWS_REGION__", region)
            .replace("__MAIN_MODEL__", main_model)
            .replace("__SMALL_MODEL__", small_model)
        )

    return _fill(_AWS_AGENT_RUN_DIR_SETUP_TEMPLATE), _fill(_AWS_AGENT_COMPOSE_TEMPLATE)


# AWS-only (#1377 slice 5). Durable DOCKER-USER rule dropping every forwarded
# container request to IMDS (169.254.169.254/32 + fd00:ec2::254/128; never
# the 169.254.169.253 VPC DNS resolver) -- a14-kali's Bedrock credential comes
# host-side via STS instead (KALI_BEDROCK_SHARD_SCRIPT). Installed by a
# systemd unit plus a docker.service drop-in so it survives dockerd restarts;
# fails closed unless verified present and active.
INSTALL_IMDS_FIREWALL_SCRIPT = """#!/bin/bash
set -euo pipefail

FIREWALL_SCRIPT="/usr/local/bin/shifter-block-imds.sh"
FIREWALL_SERVICE="/etc/systemd/system/shifter-block-imds.service"
DOCKER_DROPIN_DIR="/etc/systemd/system/docker.service.d"
DOCKER_DROPIN="$DOCKER_DROPIN_DIR/99-shifter-block-imds.conf"

# Idempotent: safe to (re-)install and (re-)start on every bootstrap retry.
cat > "$FIREWALL_SCRIPT" <<'FW_EOF'
#!/bin/bash
set -euo pipefail
# Drop forwarded container traffic to IMDS. Scoped to exactly this /32 so
# every other 169.254.169.0/24 address (including the VPC DNS resolver) is
# left completely untouched by this or any other rule here.
if ! iptables -C DOCKER-USER -d 169.254.169.254/32 -j DROP 2>/dev/null; then
  iptables -I DOCKER-USER -d 169.254.169.254/32 -j DROP
fi

# Block the IPv6 IMDS endpoint (fd00:ec2::254) the same way, when the host
# has an ip6tables DOCKER-USER chain at all. Not a skip when IPv6 is absent
# entirely -- there is no IPv6 IMDS surface to block in that case.
if command -v ip6tables >/dev/null 2>&1 && ip6tables -L DOCKER-USER >/dev/null 2>&1; then
  if ! ip6tables -C DOCKER-USER -d fd00:ec2::254/128 -j DROP 2>/dev/null; then
    ip6tables -I DOCKER-USER -d fd00:ec2::254/128 -j DROP
  fi
fi
FW_EOF
chmod 755 "$FIREWALL_SCRIPT"
chown root:root "$FIREWALL_SCRIPT"

# Apply immediately so the rule is live before a14-kali ever starts.
"$FIREWALL_SCRIPT"

# Restore unit: reapplies on every boot. After/Requires/PartOf docker.service
# so it only ever runs once Docker's own DOCKER-USER chain exists, and is
# torn down/rebuilt alongside Docker rather than drifting independently.
cat > "$FIREWALL_SERVICE" <<UNIT_EOF
[Unit]
Description=Shifter IMDS metadata firewall for polaris range containers
After=docker.service
Requires=docker.service
PartOf=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$FIREWALL_SCRIPT

[Install]
WantedBy=multi-user.target
UNIT_EOF

# Docker daemon restart rewrites/flushes its managed chains; an ExecStartPost
# drop-in re-applies the rule every time dockerd (re)starts -- the only way
# to survive `systemctl restart docker` without a one-time bootstrap-only
# mutation.
mkdir -p "$DOCKER_DROPIN_DIR"
cat > "$DOCKER_DROPIN" <<DROPIN_EOF
[Service]
ExecStartPost=$FIREWALL_SCRIPT
DROPIN_EOF

systemctl daemon-reload
systemctl enable --now shifter-block-imds.service

# Fail closed: the range must not proceed unless the rule is actually
# present and the restore unit is enabled and active.
if ! iptables -C DOCKER-USER -d 169.254.169.254/32 -j DROP 2>/dev/null; then
  echo "polaris imds firewall: DOCKER-USER drop rule is not present after install" >&2
  exit 1
fi
if ! systemctl is-enabled --quiet shifter-block-imds.service; then
  echo "polaris imds firewall: shifter-block-imds.service is not enabled" >&2
  exit 1
fi
if ! systemctl is-active --quiet shifter-block-imds.service; then
  echo "polaris imds firewall: shifter-block-imds.service is not active" >&2
  exit 1
fi

echo "polaris imds firewall: DOCKER-USER drop rule installed, restore unit enabled and active"
exit 0
"""

# Configures Claude Code on a14-kali to talk to Bedrock via a per-range
# STS-assumed identity instead of IMDS (#1377 slice 5). A root-owned host
# script assumes the per-range Bedrock agent role using the HOST's own
# instance-profile credentials, atomically writes the response under
# /run/shifter-agent/ (read-only mount into a14-kali), and a systemd timer
# re-runs it before expiry -- a failed first run aborts this step.
KALI_BEDROCK_SHARD_SCRIPT = """#!/bin/bash
set -euo pipefail

ROLE_ARN="{{ role_arn }}"
REGION="{{ region }}"
STS_SESSION_DURATION_SECONDS="{{ sts_session_duration_seconds }}"
REFRESH_WINDOW_SECONDS="{{ refresh_window_seconds }}"
RANGE_ID="{{ range_id }}"
ENVIRONMENT_NAME="{{ environment }}"

if [[ -z "$ROLE_ARN" || -z "$REGION" ]]; then
  echo "polaris kali bedrock shard: role_arn and region are required" >&2
  exit 2
fi

RUN_DIR="/run/shifter-agent"
CONFIG_DIR="/etc/shifter-agent"
CONFIG_FILE="$CONFIG_DIR/agent-role.env"
REFRESH_SCRIPT="/usr/local/bin/shifter-refresh-bedrock-creds.sh"
SESSION_NAME="${ENVIRONMENT_NAME}-range-${RANGE_ID}"

# 1a. Root-owned runtime dir for the STS response (idempotent -- the shared
# compose-rewrite step already creates this, but this step must not depend
# on step ordering across retries). 0711 so a14-kali's non-root user can
# traverse to the credentials file the refresh script writes at 0644; see
# docs/architecture/polaris-aws-agent-credentials-preflight-1377.md
# ("the participant is expected to be able to read ... that is its intended
# identity") -- root-only WRITE is the control that matters here.
umask 077
mkdir -p "$RUN_DIR"
chown root:root "$RUN_DIR"
chmod 711 "$RUN_DIR"

# 1b. Non-secret refresh config (role ARN, region, duration, session name).
# Written via a plain heredoc since none of this is a credential; the
# refresh script below sources it so its own body stays 100% static and
# never needs to be regenerated per range.
mkdir -p "$CONFIG_DIR"
chmod 755 "$CONFIG_DIR"
cat > "$CONFIG_FILE" <<CONFIG_EOF
ROLE_ARN=$ROLE_ARN
REGION=$REGION
DURATION_SECONDS=$STS_SESSION_DURATION_SECONDS
SESSION_NAME=$SESSION_NAME
RUN_DIR=$RUN_DIR
CRED_FILE=$RUN_DIR/credentials.json
CONFIG_EOF
chmod 644 "$CONFIG_FILE"
chown root:root "$CONFIG_FILE"

# 1c. The refresh script itself: static body (quoted heredoc, no bootstrap-
# time substitution) so it never needs rewriting after install. Assumes the
# per-range agent role using the HOST's OWN instance-profile credentials,
# validates the response shape without echoing it, and writes it atomically
# (temp file in the same directory + mv) in the credential_process JSON
# shape. Never traces its own execution.
cat > "$REFRESH_SCRIPT" <<'REFRESH_EOF'
#!/bin/bash
set -euo pipefail
umask 077

CONFIG_FILE="/etc/shifter-agent/agent-role.env"
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "shifter-refresh-bedrock-creds: missing $CONFIG_FILE" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$CONFIG_FILE"
if [[ -z "${ROLE_ARN:-}" || -z "${REGION:-}" || -z "${DURATION_SECONDS:-}" \\
      || -z "${RUN_DIR:-}" || -z "${CRED_FILE:-}" ]]; then
  echo "shifter-refresh-bedrock-creds: agent-role.env is incomplete" >&2
  exit 1
fi

RESPONSE_FILE="$(mktemp "$RUN_DIR/.sts-response.XXXXXX")"
ERR_FILE="$(mktemp)"
chmod 600 "$RESPONSE_FILE" "$ERR_FILE"
cleanup() {
  shred -u "$RESPONSE_FILE" "$ERR_FILE" 2>/dev/null || rm -f "$RESPONSE_FILE" "$ERR_FILE"
}
trap cleanup EXIT

if ! aws sts assume-role \\
    --role-arn "$ROLE_ARN" \\
    --role-session-name "$SESSION_NAME" \\
    --duration-seconds "$DURATION_SECONDS" \\
    --region "$REGION" \\
    --output json > "$RESPONSE_FILE" 2>"$ERR_FILE"; then
  echo "shifter-refresh-bedrock-creds: sts assume-role failed" >&2
  head -c 300 "$ERR_FILE" >&2 || true
  exit 1
fi

TMP_CRED_FILE="$(mktemp "$RUN_DIR/.credentials.json.XXXXXX")"
chmod 644 "$TMP_CRED_FILE"
if ! python3 - "$RESPONSE_FILE" "$TMP_CRED_FILE" <<'PYEOF'
import json
import sys

resp_path, out_path = sys.argv[1], sys.argv[2]
with open(resp_path, encoding="utf-8") as f:
    resp = json.load(f)
creds = resp.get("Credentials") or {}
required = ("AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration")
if any(not creds.get(k) for k in required):
    sys.exit(1)
out = {
    "Version": 1,
    "AccessKeyId": creds["AccessKeyId"],
    "SecretAccessKey": creds["SecretAccessKey"],
    "SessionToken": creds["SessionToken"],
    "Expiration": creds["Expiration"],
}
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f)
PYEOF
then
  echo "shifter-refresh-bedrock-creds: assume-role response failed shape validation" >&2
  rm -f "$TMP_CRED_FILE"
  exit 1
fi

mv "$TMP_CRED_FILE" "$CRED_FILE"
echo "shifter-refresh-bedrock-creds: credentials refreshed"
REFRESH_EOF
chmod 700 "$REFRESH_SCRIPT"
chown root:root "$REFRESH_SCRIPT"

# 1d. Run the refresh once, right now, as a bare statement -- `set -e`
# aborts this whole step (and therefore provisioning) if assume-role fails.
# This is deliberately NOT `"$REFRESH_SCRIPT" || echo warn` -- the old
# hop-limit path warned and continued on failure; this must not.
"$REFRESH_SCRIPT"

# 1e. Systemd timer: re-runs the refresh before the session expires. Period
# is the session duration minus the configured refresh window so there is
# always a live credential file. Also runs shortly after boot, since /run is
# tmpfs and does not survive a reboot.
cat > /etc/systemd/system/shifter-refresh-bedrock-creds.service <<UNIT_EOF
[Unit]
Description=Shifter per-range Bedrock STS credential refresh

[Service]
Type=oneshot
ExecStart=$REFRESH_SCRIPT
UNIT_EOF

REFRESH_PERIOD_SECONDS=$((STS_SESSION_DURATION_SECONDS - REFRESH_WINDOW_SECONDS))
if [[ "$REFRESH_PERIOD_SECONDS" -lt 60 ]]; then
  REFRESH_PERIOD_SECONDS=60
fi
cat > /etc/systemd/system/shifter-refresh-bedrock-creds.timer <<TIMER_EOF
[Unit]
Description=Periodic refresh of the per-range Bedrock STS credential

[Timer]
OnBootSec=30s
OnUnitActiveSec=${REFRESH_PERIOD_SECONDS}s
AccuracySec=10s

[Install]
WantedBy=timers.target
TIMER_EOF

systemctl daemon-reload
systemctl enable --now shifter-refresh-bedrock-creds.timer

# Fail closed: the range must not proceed unless the timer is actually wired
# up to keep refreshing (the .service unit is a oneshot triggered by the
# timer, so it is expected to be "inactive (dead)" between runs -- the timer
# itself is the thing that must be enabled and active).
if ! systemctl is-enabled --quiet shifter-refresh-bedrock-creds.timer; then
  echo "polaris kali bedrock shard: shifter-refresh-bedrock-creds.timer is not enabled" >&2
  exit 1
fi
if ! systemctl is-active --quiet shifter-refresh-bedrock-creds.timer; then
  echo "polaris kali bedrock shard: shifter-refresh-bedrock-creds.timer is not active" >&2
  exit 1
fi

# 2. a14-kali's credential_process reader, AWS profile (AWS_CONFIG_FILE), the
# Claude/Bedrock login env, and the Bedrock VPC-endpoint hosts entry are all
# delivered DURABLY by the shared polaris_range_bootstrap step, NOT written into
# the a14-kali container layer here: the reader / aws-config / profile.d env shim
# are written to the host under /run/shifter-agent and bind-mounted read-only,
# and AWS_CONFIG_FILE + the Bedrock env + the extra_hosts entry (resolved to the
# VPC-endpoint IP published in the compose .env) come from the compose override
# (see AWS_AGENT_RUN_DIR_SETUP_TEMPLATE / AWS_AGENT_COMPOSE_TEMPLATE in this
# module). A docker compose up --force-recreate a14-kali therefore keeps the
# whole provider configuration, not just the mounted credentials (#1377 cycle-2
# finding 2). This step owns only the host-side STS credential lifecycle above.
echo "polaris kali bedrock shard: STS refresh installed (per-range role, host-side credential_process, IMDS blocked)"
"""

# AWS-only (#1377 slice 5). Extends the shared checks with this slice's
# fail-closed controls: metadata firewall present, host STS refresh
# produced credentials, a14-kali's identity resolves to THIS range's agent
# role, a Bedrock invocation succeeds, and IMDS is unreachable.
VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS = (
    VERIFY_POLARIS_BOOTSTRAP_COMMON
    + """
# 7. AWS-only: the DOCKER-USER metadata-drop rule is present.
if ! iptables -C DOCKER-USER -d 169.254.169.254/32 -j DROP 2>/dev/null; then
  echo "polaris verify: DOCKER-USER metadata drop rule is missing" >&2
  exit 1
fi

# 8. AWS-only: the host STS refresh succeeded and a14-kali can see the
#    resulting credentials file through its read-only mount.
if ! docker exec a14-kali test -s /run/shifter-agent/credentials.json; then
  echo "polaris verify: /run/shifter-agent/credentials.json is missing or empty inside a14-kali" >&2
  exit 1
fi

# 9. AWS-only: the per-range agent credentials resolve to THIS range's agent role,
#    checked host-side with the mounted credential_process config (no container aws CLI).
ROLE_ARN="{{ role_arn }}"
AGENT_ROLE_NAME="${ROLE_ARN##*/}"
if [[ -z "$AGENT_ROLE_NAME" ]]; then
  echo "polaris verify: could not derive the agent role name from role_arn" >&2
  exit 1
fi
caller_identity=$(AWS_CONFIG_FILE=/run/shifter-agent/aws-config AWS_SDK_LOAD_CONFIG=1 \\
  aws sts get-caller-identity --output json 2>&1 || true)
if [[ "$caller_identity" != *"$AGENT_ROLE_NAME"* ]]; then
  echo "polaris verify: agent credentials do not resolve to the per-range agent role: ${caller_identity:-<empty>}" >&2
  exit 1
fi

# 10. AWS-only: a minimal Bedrock invocation succeeds through those agent creds.
if ! AWS_CONFIG_FILE=/run/shifter-agent/aws-config AWS_SDK_LOAD_CONFIG=1 \\
    aws bedrock-runtime invoke-model \\
    --model-id "{{ small_model_id }}" \\
    --body '{"anthropic_version":"bedrock-2023-05-31","max_tokens":8,"messages":[{"role":"user","content":"ok"}]}' \\
    --cli-binary-format raw-in-base64-out \\
    --region "{{ region }}" \\
    /tmp/polaris-bedrock-smoke.json >/dev/null 2>&1; then
  echo "polaris verify: Bedrock smoke invocation via agent credentials failed" >&2
  exit 1
fi

# 11. AWS-only: IMDS is unreachable from a14-kali -- the metadata firewall
#     DROPs packets to 169.254.169.254, so a blocked container sees a connection
#     timeout, not an HTTP status. IMDSv2 answers a tokenless GET with 401 even
#     when fully reachable, so "non-2xx == blocked" is a false negative: a
#     participant can still PUT for a token and read the host role's credentials.
#     Probe the IMDSv2 token endpoint the way a participant would (PUT) and treat
#     ANY HTTP response as reachability -- curl exits 0 for 401/403 without
#     --fail; only a connection failure/timeout (curl non-zero) counts as denied.
if docker exec a14-kali curl -s -m 2 -o /dev/null \\
    -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \\
    http://169.254.169.254/latest/api/token 2>/dev/null; then
  echo "polaris verify: IMDS reachable from a14-kali (IMDSv2 token endpoint responded; metadata firewall failed)" >&2
  exit 1
fi

echo "polaris verify: dc01 -> $resolved, kali key installed, splice gated, watcher active, aws agent secured"
exit 0
"""
)
