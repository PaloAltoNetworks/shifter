"""Shell script templates for the TechVault range bootstrap.

The TechVault golden AMI already ships the full ``techvault-operational``
docker compose stack (auto-starting on boot via each container's
``restart: unless-stopped`` policy) plus Claude Code and the APTL MCP
servers on the ``ubuntu`` host seat. The only per-range agent step is
writing the Bedrock credential shard so Claude Code on the host resolves
model access through the instance role.

Unlike POLARIS (``_polaris_scripts.py``), the Claude seat here is the EC2
host itself, not a container, so the shard writes ``/etc/profile.d`` on the
host directly (no ``docker cp`` into a container) and no IMDS hop-limit bump
is needed. AWS Bedrock only for now; the GCP/Vertex plane is tracked
separately (issue #1446).
"""

# Writes /etc/profile.d/claude-bedrock.sh on the host. Same-account mode:
# no static AWS creds; Claude Code inherits the EC2 instance profile via
# IMDS. Login shells (the RDP desktop's VS Code integrated terminal is one)
# source /etc/profile.d, so `claude` in that terminal picks these up.
TECHVAULT_BEDROCK_SHARD_SCRIPT = """#!/bin/bash
set -euo pipefail
ANTHROPIC_MODEL="{{ anthropic_model }}"
ANTHROPIC_SMALL_FAST_MODEL="{{ anthropic_small_fast_model }}"
AWS_REGION="{{ aws_region }}"

PROFILE_FILE=/etc/profile.d/claude-bedrock.sh
cat > "$PROFILE_FILE" <<EOF
# TechVault range agent: Claude Code via AWS Bedrock (EC2 instance role).
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=${AWS_REGION}
export ANTHROPIC_MODEL=${ANTHROPIC_MODEL}
export ANTHROPIC_SMALL_FAST_MODEL=${ANTHROPIC_SMALL_FAST_MODEL}
EOF
chmod 644 "$PROFILE_FILE"
echo "techvault bedrock shard: wrote $PROFILE_FILE (model=$ANTHROPIC_MODEL region=$AWS_REGION)"
"""

VERIFY_TECHVAULT_BOOTSTRAP_SCRIPT = """#!/bin/bash
set -euo pipefail
if ! test -s /etc/profile.d/claude-bedrock.sh; then
  echo "techvault verify: /etc/profile.d/claude-bedrock.sh is missing or empty" >&2
  exit 1
fi
if ! grep -q CLAUDE_CODE_USE_BEDROCK /etc/profile.d/claude-bedrock.sh; then
  echo "techvault verify: CLAUDE_CODE_USE_BEDROCK not set in claude-bedrock.sh" >&2
  exit 1
fi
if ! command -v claude >/dev/null 2>&1; then
  echo "techvault verify: claude CLI not on PATH" >&2
  exit 1
fi
echo "techvault verify: bedrock shard present and claude CLI available"
"""
