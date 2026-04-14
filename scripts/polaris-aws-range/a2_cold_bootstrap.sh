#!/usr/bin/env bash
# POLARIS A2 cold bootstrap — runs after `terraform apply` to take a fresh
# Windows Server 2022 EC2 through the full path:
#   minimal user_data (firewall off, admin pw set, RDP on, SSM agent up)
#     -> install AD DS + DNS features
#     -> rename computer to dc01
#     -> Install-ADDSForest (BOREAS.LOCAL, reboot)
#     -> a2_setup.ps1 (OUs, 17 users, nested Project-L, SPNs, DCSync ACL,
#        badgelogs + admin_flag shares, Project-L info attribute, RC4 pin)
#
# Idempotent and re-runnable. Operator calls this with the A2 instance id
# from `terraform output`:
#
#   ./scripts/polaris-aws-range/a2_cold_bootstrap.sh i-xxxxxxxxxxxxxxxxx
#
# Requires: aws cli with panw-shifter-dev-workstation profile access to SSM.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-panw-shifter-dev-workstation}"
AWS_REGION="${AWS_REGION:-us-east-2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
A2_ID="${1:-}"

if [[ -z "$A2_ID" ]]; then
    A2_ID="$(terraform -chdir="${SCRIPT_DIR}" output -raw a2_dc_instance_id 2>/dev/null || true)"
fi

if [[ -z "$A2_ID" ]]; then
    echo "usage: $0 <a2-instance-id>" >&2
    echo "  (or run from a directory where \`terraform output a2_dc_instance_id\` resolves)" >&2
    exit 1
fi

ts() { date -u +%FT%TZ; }
log() { echo "[$(ts)] $*"; }

aws_ssm() {
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"
}

wait_for_ssm() {
    local target="$1"
    local deadline=$((SECONDS + 600))
    while (( SECONDS < deadline )); do
        local ping
        ping="$(aws_ssm ssm describe-instance-information \
            --filters "Key=InstanceIds,Values=${target}" \
            --query 'InstanceInformationList[0].PingStatus' \
            --output text 2>/dev/null || echo None)"
        if [[ "$ping" == "Online" ]]; then
            return 0
        fi
        sleep 5
    done
    echo "timeout waiting for SSM agent on ${target}" >&2
    return 1
}

run_powershell_file() {
    local target="$1" local_file="$2" description="$3" timeout="${4:-1800}"
    local b64
    b64="$(base64 -w0 "$local_file")"
    log "${description}: sending ${local_file} (${#b64} base64 bytes) -> ${target}"

    # Build the SSM send-command parameters via python so the base64 blob +
    # PowerShell dollar-sign variable names survive JSON + shell quoting
    # cleanly. The printf-based escape dance was unreliable.
    local params_json
    params_json="$(mktemp /tmp/a2_ssm_params.XXXXXX.json)"
    python3 - "$b64" "$params_json" <<'PY'
import json, sys
b64, out_path = sys.argv[1], sys.argv[2]
ps = (
    f"$b64 = '{b64}';"
    "[System.IO.File]::WriteAllBytes('C:\\polaris-wrapper.ps1',"
    "[Convert]::FromBase64String($b64));"
    "powershell.exe -NoProfile -ExecutionPolicy Bypass "
    "-File C:\\polaris-wrapper.ps1"
)
with open(out_path, "w") as f:
    json.dump({"commands": [ps]}, f)
PY

    local command_id
    command_id="$(aws_ssm ssm send-command \
        --instance-ids "$target" \
        --document-name "AWS-RunPowerShellScript" \
        --parameters "file://${params_json}" \
        --timeout-seconds "$timeout" \
        --query 'Command.CommandId' --output text)"
    rm -f "$params_json"

    log "${description}: command_id=${command_id}, polling..."

    local deadline=$((SECONDS + timeout))
    while (( SECONDS < deadline )); do
        local status
        status="$(aws_ssm ssm get-command-invocation \
            --command-id "$command_id" --instance-id "$target" \
            --query 'Status' --output text 2>/dev/null || echo Pending)"
        case "$status" in
            Success)
                log "${description}: SUCCESS"
                aws_ssm ssm get-command-invocation \
                    --command-id "$command_id" --instance-id "$target" \
                    --query 'StandardOutputContent' --output text | tail -30
                return 0
                ;;
            Failed|Cancelled|TimedOut)
                log "${description}: ${status}"
                aws_ssm ssm get-command-invocation \
                    --command-id "$command_id" --instance-id "$target" \
                    --query '[StandardOutputContent,StandardErrorContent]' --output text | tail -50
                return 1
                ;;
            *)
                sleep 10
                ;;
        esac
    done
    log "${description}: wall-clock timeout"
    return 1
}

# --- Phase 1: wait for fresh Windows to report into SSM ---------------------
log "=== A2 cold bootstrap for ${A2_ID} ==="
log "phase 1/4: waiting for SSM agent to come online"
wait_for_ssm "$A2_ID"
log "SSM agent online on ${A2_ID}"

# --- Phase 2: Install-ADDSForest wrapper ------------------------------------
# The wrapper installs AD-Domain-Services + DNS features, renames the
# computer to dc01, writes a2_setup.ps1 to disk, registers a SYSTEM
# scheduled task that runs it at next boot, then calls Install-ADDSForest
# which reboots the box.
#
# We assemble the wrapper on the fly by concatenating two local files:
#   - a2_install_adds_wrapper.sh.in   (outer scaffolding)
#   - a2_setup.ps1                     (post-promo setup, embedded as here-string)
# into a single combined.ps1 that lives in /tmp on this machine only.
log "phase 2/4: build combined install-ADDS wrapper"

WRAPPER_TMP="$(mktemp /tmp/a2_combined.XXXXXX.ps1)"
SETUP_PS1="${SCRIPT_DIR}/a2_setup.ps1"
if [[ ! -f "$SETUP_PS1" ]]; then
    echo "missing ${SETUP_PS1}" >&2
    exit 1
fi

# Escape the setup script for embedding in a PowerShell here-string: the
# @' ... '@ form takes the body literally, so as long as the body does not
# contain the exact sequence `'@` followed by a newline it is safe. The
# committed a2_setup.ps1 does not contain that sequence.
cat > "$WRAPPER_TMP" <<'WRAPPER_EOF'
$ErrorActionPreference = "Stop"
Start-Transcript -Path "C:\polaris-install-adds.log" -Append -Force
Write-Host "=== POLARIS A2 install-adds $(Get-Date -Format o) ==="

Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False
net user Administrator "CortexSavesTheDay!" | Out-Null

if (-not (Get-WindowsFeature -Name AD-Domain-Services).Installed) {
    Write-Host "Installing AD-Domain-Services..."
    Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools | Out-Null
}
if (-not (Get-WindowsFeature -Name DNS).Installed) {
    Write-Host "Installing DNS..."
    Install-WindowsFeature -Name DNS -IncludeManagementTools | Out-Null
}

$setupScript = @'
__A2_SETUP_CONTENT__
'@
$setupLocal = "C:\polaris-a2-setup.ps1"
Set-Content -Path $setupLocal -Value $setupScript -Encoding UTF8
Write-Host "Wrote $setupLocal"

$taskName = "PolarisA2Setup"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$setupLocal`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
Write-Host "Scheduled task '$taskName' registered"

if ($env:COMPUTERNAME -ne "DC01") {
    Rename-Computer -NewName "dc01" -Force
    Write-Host "Computer rename queued (dc01)"
}

Import-Module ADDSDeployment
$secureDsrm = ConvertTo-SecureString "DsrmR3store!2026" -AsPlainText -Force

Write-Host "Install-ADDSForest BOREAS.LOCAL (this reboots)..."
Install-ADDSForest `
    -DomainName "boreas.local" `
    -DomainNetbiosName "BOREAS" `
    -ForestMode "WinThreshold" `
    -DomainMode "WinThreshold" `
    -InstallDns `
    -DatabasePath "C:\Windows\NTDS" `
    -LogPath "C:\Windows\NTDS" `
    -SysvolPath "C:\Windows\SYSVOL" `
    -SafeModeAdministratorPassword $secureDsrm `
    -CreateDnsDelegation:$false `
    -NoRebootOnCompletion:$false `
    -Force:$true
Stop-Transcript
WRAPPER_EOF

# Splice a2_setup.ps1 content into the __A2_SETUP_CONTENT__ marker using a
# python one-liner (awk + sed choke on the special characters in the ps1).
python3 - "$WRAPPER_TMP" "$SETUP_PS1" <<'PY'
import sys
wrapper_path, setup_path = sys.argv[1], sys.argv[2]
with open(setup_path) as f: setup = f.read()
with open(wrapper_path) as f: wrapper = f.read()
with open(wrapper_path, "w") as f: f.write(wrapper.replace("__A2_SETUP_CONTENT__", setup))
PY

# Install-ADDSForest expects the rename to be finalized before promotion
# can start. Because Rename-Computer needs a reboot, we run the wrapper
# twice: first to rename + schedule + install features (which will fail
# Install-ADDSForest with "Name change pending"), then reboot, then re-run
# to complete the promotion. This matches the manual cold-bootstrap flow
# I proved in session.
log "phase 2/4: first wrapper run — queues rename, installs features, fails Install-ADDSForest with 'name change pending'"
set +e
run_powershell_file "$A2_ID" "$WRAPPER_TMP" "install-adds (rename queue)" 1200
set -e

log "phase 2/4: reboot to apply computer rename"
aws_ssm ssm send-command --instance-ids "$A2_ID" \
    --document-name "AWS-RunPowerShellScript" \
    --parameters 'commands=["Restart-Computer -Force"]' \
    --query 'Command.CommandId' --output text >/dev/null

sleep 60
wait_for_ssm "$A2_ID"
log "SSM agent back online after rename reboot"

# --- Phase 3: Install-ADDSForest retry --------------------------------------
# Use a slim promote-only script for the retry rather than the full
# wrapper (features are already installed, scheduled task is already
# registered, no need to re-do any of that).
log "phase 3/4: Install-ADDSForest BOREAS.LOCAL"
PROMOTE_TMP="$(mktemp /tmp/a2_promote.XXXXXX.ps1)"
cat > "$PROMOTE_TMP" <<'PROMOTE_EOF'
$ErrorActionPreference = "Stop"
Start-Transcript -Path "C:\polaris-promote.log" -Append -Force
Write-Host "=== POLARIS A2 promote $(Get-Date -Format o) ==="
Write-Host "Hostname: $env:COMPUTERNAME"

Import-Module ADDSDeployment
$secureDsrm = ConvertTo-SecureString "DsrmR3store!2026" -AsPlainText -Force

Install-ADDSForest `
    -DomainName "boreas.local" `
    -DomainNetbiosName "BOREAS" `
    -ForestMode "WinThreshold" `
    -DomainMode "WinThreshold" `
    -InstallDns `
    -DatabasePath "C:\Windows\NTDS" `
    -LogPath "C:\Windows\NTDS" `
    -SysvolPath "C:\Windows\SYSVOL" `
    -SafeModeAdministratorPassword $secureDsrm `
    -CreateDnsDelegation:$false `
    -NoRebootOnCompletion:$false `
    -Force:$true
Stop-Transcript
PROMOTE_EOF

run_powershell_file "$A2_ID" "$PROMOTE_TMP" "Install-ADDSForest" 1800

log "phase 3/4: wait for DC reboot + AD services"
sleep 30
wait_for_ssm "$A2_ID"

# --- Phase 4: a2_setup.ps1 ---------------------------------------------------
# Scheduled task SHOULD have run it at boot, but re-run explicitly so we
# have a clean stdout trace and can gate the test on its exit code. The
# script is idempotent.
log "phase 4/4: idempotent a2_setup.ps1 against running DC"
run_powershell_file "$A2_ID" "$SETUP_PS1" "a2_setup.ps1" 900

log "=== A2 cold bootstrap complete ==="
