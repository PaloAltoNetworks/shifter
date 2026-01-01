#!/bin/bash
# Install and configure Claude Code for Bedrock
set -euo pipefail

echo "=== Installing Claude Code ==="
npm install -g @anthropic-ai/claude-code

echo "=== Configuring Claude Code for Bedrock ==="
mkdir -p /etc/profile.d
cat > /etc/profile.d/claude-code.sh << 'EOF'
# Claude Code configuration for AWS Bedrock
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=us-east-2
EOF

# Also set for root
cat >> /root/.bashrc << 'EOF'

# Claude Code configuration for AWS Bedrock
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=us-east-2
EOF

echo "=== Claude Code setup complete ==="
