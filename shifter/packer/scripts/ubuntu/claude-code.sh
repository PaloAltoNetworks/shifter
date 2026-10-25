#!/bin/bash
# Configure Claude Code for Bedrock. The image never contains the Claude Code
# binary: scenarios declare it as an RAES artifact feature and Shifter delivers
# it at realization (ADR-034-R11, #2463). Only Shifter's own configuration (the
# Bedrock environment and the autostart hook) is baked.
set -euo pipefail

echo "=== Configuring Claude Code for Bedrock ==="
mkdir -p /etc/profile.d
cat > /etc/profile.d/claude-code.sh << 'EOF'
# Claude Code configuration for AWS Bedrock
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=us-east-2
export ANTHROPIC_MODEL=us.anthropic.claude-sonnet-4-6
export ANTHROPIC_SMALL_FAST_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
EOF

# Also set for ubuntu user
cat >> /home/ubuntu/.bashrc << 'EOF'

# Claude Code configuration for AWS Bedrock
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=us-east-2
export ANTHROPIC_MODEL=us.anthropic.claude-sonnet-4-6
export ANTHROPIC_SMALL_FAST_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
EOF

# Root retains Bedrock env for operator debugging; autostart is kali/ubuntu only (#180).
cat >> /root/.bashrc << 'EOF'

# Claude Code configuration for AWS Bedrock
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=us-east-2
export ANTHROPIC_MODEL=us.anthropic.claude-sonnet-4-6
export ANTHROPIC_SMALL_FAST_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
EOF

echo "=== Installing Claude Code autostart hook ==="
# shellcheck source=/usr/local/lib/shifter/claude-autostart-install.sh disable=SC1091
source /usr/local/lib/shifter/claude-autostart-install.sh
install_claude_autostart /home/ubuntu/.bashrc

echo "=== Claude Code setup complete ==="
