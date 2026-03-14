#!/bin/bash
# Configure Claude Code for Shifter
# Usage: source scripts/config-claude.sh

# Load profile from .env
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$REPO_ROOT/.env" ]]; then
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
fi

export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=us-east-2
export AWS_PROFILE="${PANW_SHIFTER_DEV_PROFILE:?PANW_SHIFTER_DEV_PROFILE not set. Check .env file.}"
export ANTHROPIC_MODEL='anthropic.claude-sonnet-4-5-20250929-v1:0'
#export ANTHROPIC_MODEL='us.anthropic.claude-opus-4-5-20251101-v1:0'
export ANTHROPIC_SMALL_FAST_MODEL='anthropic.claude-haiku-4-5-20251001-v1:0'
