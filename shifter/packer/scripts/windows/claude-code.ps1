# Install and configure Claude Code for Bedrock
# Sets npm global prefix to system path for all users
$ErrorActionPreference = "Stop"

Write-Host "=== Installing Claude Code ==="

# Refresh environment to ensure npm is available
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# Find npm - could be in different locations depending on install method
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    # Try common locations
    $nodePath = "C:\Program Files\nodejs"
    if (Test-Path "$nodePath\npm.cmd") {
        $npmCmd = "$nodePath\npm.cmd"
    } else {
        Write-Error "npm not found. Node.js installation may have failed."
        exit 1
    }
} else {
    $npmCmd = $npmCmd.Source
    $nodePath = Split-Path -Parent $npmCmd
}

Write-Host "Using npm at: $npmCmd"

# ------------------------------------------------------------------------------
# Configure npm global prefix
# ------------------------------------------------------------------------------
Write-Host "=== Configuring npm global prefix ==="

# Set npm prefix to nodejs directory so global packages are in system PATH
# This ensures Claude Code is available to all users
& $npmCmd config set prefix "$nodePath" --global

Write-Host "npm global prefix set to $nodePath"

# ------------------------------------------------------------------------------
# Install Claude Code
# ------------------------------------------------------------------------------
Write-Host "=== Installing Claude Code globally ==="

& $npmCmd install -g @anthropic-ai/claude-code

Write-Host "Claude Code installed"

# ------------------------------------------------------------------------------
# Configure environment variables for Bedrock
# ------------------------------------------------------------------------------
Write-Host "=== Configuring Claude Code for AWS Bedrock ==="

# Set Machine-level environment variables (persist across reboots and users)
[System.Environment]::SetEnvironmentVariable("CLAUDE_CODE_USE_BEDROCK", "1", "Machine")
[System.Environment]::SetEnvironmentVariable("AWS_REGION", "us-east-2", "Machine")
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_SMALL_FAST_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "Machine")

# Also set for current session
$env:CLAUDE_CODE_USE_BEDROCK = "1"
$env:AWS_REGION = "us-east-2"
$env:ANTHROPIC_SMALL_FAST_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

Write-Host "Environment variables configured:"
Write-Host "  CLAUDE_CODE_USE_BEDROCK=1"
Write-Host "  AWS_REGION=us-east-2"
Write-Host "  ANTHROPIC_SMALL_FAST_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0"

Write-Host "=== Claude Code installation complete ==="
