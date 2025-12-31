# Install and configure Claude Code for Bedrock
# Sets npm global prefix to system path for all users
$ErrorActionPreference = "Stop"

Write-Host "=== Installing Claude Code ==="

$nodePath = "C:\Program Files\nodejs"

# Refresh environment to ensure npm is available
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# ------------------------------------------------------------------------------
# Configure npm global prefix
# ------------------------------------------------------------------------------
Write-Host "=== Configuring npm global prefix ==="

# Set npm prefix to nodejs directory so global packages are in system PATH
# This ensures Claude Code is available to all users
& "$nodePath\npm.cmd" config set prefix "$nodePath" --global

Write-Host "npm global prefix set to $nodePath"

# ------------------------------------------------------------------------------
# Install Claude Code
# ------------------------------------------------------------------------------
Write-Host "=== Installing Claude Code globally ==="

& "$nodePath\npm.cmd" install -g @anthropic-ai/claude-code

Write-Host "Claude Code installed"

# ------------------------------------------------------------------------------
# Configure environment variables for Bedrock
# ------------------------------------------------------------------------------
Write-Host "=== Configuring Claude Code for AWS Bedrock ==="

# Set Machine-level environment variables (persist across reboots and users)
[System.Environment]::SetEnvironmentVariable("CLAUDE_CODE_USE_BEDROCK", "1", "Machine")
[System.Environment]::SetEnvironmentVariable("AWS_REGION", "us-east-2", "Machine")

# Also set for current session
$env:CLAUDE_CODE_USE_BEDROCK = "1"
$env:AWS_REGION = "us-east-2"

Write-Host "Environment variables configured:"
Write-Host "  CLAUDE_CODE_USE_BEDROCK=1"
Write-Host "  AWS_REGION=us-east-2"

Write-Host "=== Claude Code installation complete ==="
