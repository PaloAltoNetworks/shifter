#!/bin/bash
# Configure Claude Code for Shifter
# Usage: source scripts/config-claude.sh

export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=us-east-2
export AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE
#export ANTHROPIC_MODEL='us.anthropic.claude-sonnet-4-5-20250929-v1:0'
export ANTHROPIC_MODEL='us.anthropic.claude-opus-4-5-20251101-v1:0'
export ANTHROPIC_SMALL_FAST_MODEL='us.anthropic.claude-3-5-haiku-20241022-v1:0'
