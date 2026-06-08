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
# Requires: aws cli with profile access to SSM. For aws-dev use
# AWS_PROFILE=aws-dev AWS_REGION=us-east-2.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-aws-dev}"
AWS_REGION="${AWS_REGION:-us-east-2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
A2_ID="${1:-}"

readonly SSM_PS_DOC="AWS-RunPowerShellScript"
readonly SSM_QUERY_COMMAND_ID="Command.CommandId"
readonly SSM_QUERY_STDOUT="StandardOutputContent"

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
    # Robust drop-then-back semantics. The naive "PingStatus == Online"
    # check returns true immediately when called between issuing a reboot
    # and the agent actually dropping — at that moment the SSM API still
    # reports Online from the prior session. Phase 2 then runs against
    # an unrebooted box and silently no-ops.
    #
    # Strategy: capture LastPingDateTime up front. If it's stale by >60s
    # we know the box has rebooted (agent stopped pinging). Once the
    # timestamp moves AND age <30s, the agent is genuinely back.
    local target="$1"
    local deadline=$((SECONDS + 900))
    local prev_last=""
    local saw_stale=0

    while (( SECONDS < deadline )); do
        local ping last age
        ping="$(aws_ssm ssm describe-instance-information \
            --filters "Key=InstanceIds,Values=${target}" \
            --query 'InstanceInformationList[0].PingStatus' \
            --output text 2>/dev/null || echo None)"
        last="$(aws_ssm ssm describe-instance-information \
            --filters "Key=InstanceIds,Values=${target}" \
            --query 'InstanceInformationList[0].LastPingDateTime' \
            --output text 2>/dev/null || echo None)"

        if [[ "$ping" != "Online" ]]; then
            saw_stale=1
            sleep 6
            continue
        fi

        if [[ -n "$last" && "$last" != "None" ]]; then
            age=$(( $(date +%s) - $(date -d "$last" +%s) ))
            # Treat a ping that hasn't moved in 60+s as effectively stale —
            # box is rebooting, the API just hasn't transitioned to
            # ConnectionLost yet.
            if [[ "$age" -gt 60 ]]; then
                saw_stale=1
                sleep 6
                continue
            fi
            # Genuinely fresh + online. If we saw a stale state at any
            # point, this is the post-reboot recovery — return.
            # If we never saw stale (caller invoked wait_for_ssm without
            # an outstanding reboot), still return — bootstrap entry path.
            if [[ "$age" -lt 30 && ( ( -n "$prev_last" && "$prev_last" != "$last" ) || "$saw_stale" -eq 0 ) ]]; then
                return 0
            fi
            prev_last="$last"
        fi
        sleep 6
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
    # Force the wrapper file to be written as UTF-8 with BOM so PowerShell
    # parses any non-ASCII characters in the script correctly. Without
    # this, Windows PowerShell 5.1 reads the file with the active code
    # page (Windows-1252 in en-US) and multi-byte UTF-8 sequences (em-dash,
    # etc.) decode to garbage that breaks string parsing.
    "$bytes = [System.IO.File]::ReadAllBytes('C:\\polaris-wrapper.ps1');"
    "$bom = [byte[]](0xEF,0xBB,0xBF);"
    "if ($bytes.Length -lt 3 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) {"
    "  [System.IO.File]::WriteAllBytes('C:\\polaris-wrapper.ps1', $bom + $bytes)"
    "};"
    # Run the wrapper and propagate its exit code to the SSM host so a
    # wrapper that calls `exit 1` lands in SSM as Failed. Without
    # `exit $LASTEXITCODE` the SSM host's own exit code is 0 regardless
    # of what the child powershell.exe returned.
    "& powershell.exe -NoProfile -ExecutionPolicy Bypass "
    "-File C:\\polaris-wrapper.ps1;"
    "exit $LASTEXITCODE"
)
with open(out_path, "w") as f:
    json.dump({"commands": [ps]}, f)
PY

    local command_id
    command_id="$(aws_ssm ssm send-command \
        --instance-ids "$target" \
        --document-name "$SSM_PS_DOC" \
        --parameters "file://${params_json}" \
        --timeout-seconds "$timeout" \
        --query "$SSM_QUERY_COMMAND_ID" --output text)"
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
                    --query "$SSM_QUERY_STDOUT" --output text | tail -30
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

# --- Phase 1.5: preflight DISM restorehealth + reboot -----------------------
# The stock Windows Server 2022 base AMI ships with DISM-tracked pending
# sysprep / CBS operations that block Install-WindowsFeature with:
#   DISMAPI_Error__Failed_Reboot_Required
#   "operation cannot be completed, because the server requires a restart"
# These pending operations survive a plain `Restart-Computer -Force` —
# verified empirically on ami-010cf865d5fe320f1 (us-east-2 2026-05-03):
# even after one explicit reboot, Install-WindowsFeature still failed
# with the same error.
#
# `dism /online /cleanup-image /restorehealth` flushes the pending state
# (it walks the component store, repairs corruption, and clears stuck
# pending operations). Followed by a reboot, this puts the DC in a clean
# state where Install-WindowsFeature actually succeeds.
#
# Phase 2's first wrapper run runs under `set +e` because Install-ADDSForest
# is *expected* to fail with "name change pending" after Rename-Computer
# queues — but that tolerance also masks the pending-reboot failure
# silently. Phase 1.5 prevents that silent failure mode.
#
# Idempotent: on an already-clean DC, restorehealth is fast (no work) and
# the reboot adds ~90s; on a freshly-launched DC it clears the pending
# state and lets feature install take effect. Total cost ~3-5 min for
# reliable bring-up.
log "phase 1.5/4: DISM restorehealth + reboot to clear pending sysprep state"
RESTORE_CMD_ID="$(aws_ssm ssm send-command --instance-ids "$A2_ID" \
    --document-name "$SSM_PS_DOC" \
    --parameters 'commands=["dism.exe /online /cleanup-image /restorehealth /english 2>&1 | Select-Object -Last 5; shutdown /r /t 5 /f /d p:0:0"]' \
    --timeout-seconds 1200 \
    --query "$SSM_QUERY_COMMAND_ID" --output text)"
log "phase 1.5/4: DISM cmd ${RESTORE_CMD_ID}, polling..."
deadline=$((SECONDS + 1200))
while (( SECONDS < deadline )); do
    status="$(aws_ssm ssm get-command-invocation \
        --command-id "$RESTORE_CMD_ID" --instance-id "$A2_ID" \
        --query 'Status' --output text 2>/dev/null || echo Pending)"
    case "$status" in
        Success|Failed|Cancelled|TimedOut|DeliveryTimedOut)
            log "phase 1.5/4: DISM cmd status=${status}"
            break
            ;;
        *)
            sleep 15
            ;;
    esac
done
sleep 45
wait_for_ssm "$A2_ID"
log "SSM agent back after DISM restorehealth + reboot"

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

# Track wrapper progress so the bash side can detect silent failures.
# Each step writes a marker on success; the wrapper exits 1 if any
# `Install-WindowsFeature` failed to actually install the feature.
# Earlier this section was tolerant to errors (Install-ADDSForest is
# *expected* to fail with "name change pending" when invoked in the
# same script as Rename-Computer — that's by design and the bash side
# retries it). But that same tolerance silently swallowed a real
# DISMAPI_Error__Failed_Reboot_Required from Install-WindowsFeature,
# leaving the box "unpromoted" while bash reported SUCCESS. Phase 1.5
# (DISM restorehealth) clears the pending state before this runs; the
# explicit `.Installed` check below catches any remaining miss.
$markerDir = "C:\polaris-markers"
New-Item -ItemType Directory -Force -Path $markerDir | Out-Null

Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False
net user Administrator "CortexSavesTheDay!" | Out-Null
New-Item -ItemType File -Force -Path "$markerDir\01-firewall-admin-pw" | Out-Null

try {
    if (-not (Get-WindowsFeature -Name AD-Domain-Services).Installed) {
        Write-Host "Installing AD-Domain-Services..."
        $r = Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools -ErrorAction Stop
        Write-Host "  Install-WindowsFeature AD-DS Success=$($r.Success) RestartNeeded=$($r.RestartNeeded)"
    }
    if (-not (Get-WindowsFeature -Name DNS).Installed) {
        Write-Host "Installing DNS..."
        $r = Install-WindowsFeature -Name DNS -IncludeManagementTools -ErrorAction Stop
        Write-Host "  Install-WindowsFeature DNS Success=$($r.Success) RestartNeeded=$($r.RestartNeeded)"
    }
} catch {
    Write-Host "FATAL: Install-WindowsFeature failed: $($_.Exception.Message)"
    Stop-Transcript
    exit 1
}
# Verify post-install — Install-WindowsFeature can return a soft-failure
# Result object even when -ErrorAction Stop is set.
if (-not (Get-WindowsFeature -Name AD-Domain-Services).Installed) {
    Write-Host "FATAL: AD-Domain-Services feature still not Installed after Install-WindowsFeature"
    Stop-Transcript
    exit 1
}
if (-not (Get-WindowsFeature -Name DNS).Installed) {
    Write-Host "FATAL: DNS feature still not Installed after Install-WindowsFeature"
    Stop-Transcript
    exit 1
}
New-Item -ItemType File -Force -Path "$markerDir\02-features-installed" | Out-Null

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
New-Item -ItemType File -Force -Path "$markerDir\03-task-scheduled" | Out-Null

if ($env:COMPUTERNAME -ne "DC01") {
    Rename-Computer -NewName "dc01" -Force
    Write-Host "Computer rename queued (dc01)"
}

# Install-ADDSForest is *expected* to fail in this first wrapper run with
# "Verification of prerequisites for Domain Controller promotion failed.
# Name change pending. A reboot is required." That's by design — bash
# detects the rename-pending failure, reboots, then runs a slim
# promote-only script. So we do NOT propagate the Install-ADDSForest
# error code; we just let the script fall through to Stop-Transcript.
try {
    Import-Module ADDSDeployment
    $secureDsrm = ConvertTo-SecureString "DsrmR3store!2026" -AsPlainText -Force
    Write-Host "Install-ADDSForest BOREAS.LOCAL (expected to fail with name-change-pending; bash retries after reboot)..."
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
    # If we got here without the box rebooting, promotion actually
    # succeeded (rare path: name was already DC01 from a prior run).
    New-Item -ItemType File -Force -Path "$markerDir\04-promoted-first-pass" | Out-Null
} catch {
    if ($_.Exception.Message -match "Name change pending") {
        Write-Host "Install-ADDSForest deferred to retry after reboot (name change pending - expected)"
    } else {
        Write-Host "WARNING: Install-ADDSForest failed with unexpected error: $($_.Exception.Message)"
        # Still don't exit 1 — bash will retry. But the unexpected error
        # is logged for forensics.
    }
}
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
WRAPPER_EXIT=$?
set -e

# After wrapper, validate that the feature-install step actually ran by
# checking the on-host marker. The wrapper itself exits non-zero if
# Install-WindowsFeature fails, but the bash side's `set +e` was tolerant
# specifically because Install-ADDSForest is expected to fail with
# rename-pending. The marker disambiguates: features-installed marker
# present = wrapper got past install (good), absent = real bug.
log "phase 2/4: validating wrapper progress markers"
MARKER_CMD_ID="$(aws_ssm ssm send-command --instance-ids "$A2_ID" \
    --document-name "$SSM_PS_DOC" \
    --parameters 'commands=["Test-Path C:\\polaris-markers\\02-features-installed; Test-Path C:\\polaris-markers\\03-task-scheduled"]' \
    --query "$SSM_QUERY_COMMAND_ID" --output text)"
sleep 6
marker_out="$(aws_ssm ssm get-command-invocation \
    --command-id "$MARKER_CMD_ID" --instance-id "$A2_ID" \
    --query "$SSM_QUERY_STDOUT" --output text 2>/dev/null || echo missing)"
log "phase 2/4: markers: ${marker_out//$'\n'/ }"
if [[ "$marker_out" != *"True"*"True"* ]]; then
    log "[FATAL] phase 2 features-installed and/or task-scheduled markers missing — wrapper run silently failed"
    log "[FATAL] wrapper SSM exit code was: $WRAPPER_EXIT"
    log "[FATAL] dumping install-adds.log:"
    DUMP_CMD_ID="$(aws_ssm ssm send-command --instance-ids "$A2_ID" \
        --document-name "$SSM_PS_DOC" \
        --parameters 'commands=["Get-Content C:\\polaris-install-adds.log -Tail 80"]' \
        --query "$SSM_QUERY_COMMAND_ID" --output text)"
    sleep 5
    aws_ssm ssm get-command-invocation \
        --command-id "$DUMP_CMD_ID" --instance-id "$A2_ID" \
        --query "$SSM_QUERY_STDOUT" --output text 2>&1 | tail -80
    exit 1
fi

log "phase 2/4: reboot to apply computer rename"
aws_ssm ssm send-command --instance-ids "$A2_ID" \
    --document-name "$SSM_PS_DOC" \
    --parameters 'commands=["Restart-Computer -Force"]' \
    --query "$SSM_QUERY_COMMAND_ID" --output text >/dev/null

sleep 60
wait_for_ssm "$A2_ID"
log "SSM agent back online after rename reboot"

# --- Phase 3: Install-ADDSForest retry --------------------------------------
# Use a slim promote-only script for the retry rather than the full
# wrapper (features are already installed, scheduled task is already
# registered, no need to re-do any of that). First assert the hostname
# rename took — if it didn't, Install-ADDSForest would fail again with
# rename pending and we'd silently wedge.
log "phase 3/4: assert hostname == DC01 before promote"
# shellcheck disable=SC2016  # $env:COMPUTERNAME is PowerShell, not bash
NAME_CMD_ID="$(aws_ssm ssm send-command --instance-ids "$A2_ID" \
    --document-name "$SSM_PS_DOC" \
    --parameters 'commands=["$env:COMPUTERNAME"]' \
    --query "$SSM_QUERY_COMMAND_ID" --output text)"
sleep 5
hostname_now="$(aws_ssm ssm get-command-invocation \
    --command-id "$NAME_CMD_ID" --instance-id "$A2_ID" \
    --query "$SSM_QUERY_STDOUT" --output text 2>/dev/null | tr -d '[:space:]')"
log "phase 3/4: hostname=${hostname_now}"
if [[ "$hostname_now" != "DC01" ]]; then
    log "[FATAL] hostname is '${hostname_now}', expected 'DC01' — rename reboot didn't take. Cannot promote."
    exit 1
fi

log "phase 3/4: Install-ADDSForest BOREAS.LOCAL"
PROMOTE_TMP="$(mktemp /tmp/a2_promote.XXXXXX.ps1)"
cat > "$PROMOTE_TMP" <<'PROMOTE_EOF'
$ErrorActionPreference = "Continue"
Start-Transcript -Path "C:\polaris-promote.log" -Append -Force
Write-Host "=== POLARIS A2 promote $(Get-Date -Format o) ==="
Write-Host "Hostname: $env:COMPUTERNAME"

# Marker — bash side checks for this after reboot
$markerDir = "C:\polaris-markers"
New-Item -ItemType Directory -Force -Path $markerDir | Out-Null

try {
    Import-Module ADDSDeployment -ErrorAction Stop
    $secureDsrm = ConvertTo-SecureString "DsrmR3store!2026" -AsPlainText -Force
    Write-Host "Install-ADDSForest BOREAS.LOCAL (this reboots on completion)..."
    # Install-ADDSForest will reboot the box; SSM will report the
    # parent script as Failed/DeliveryTimedOut because the connection
    # drops. That's expected. Bash detects via wait_for_ssm.
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
    # Unreachable on success because the reboot kills us
    Write-Host "WARNING: Install-ADDSForest returned without reboot - investigate"
    New-Item -ItemType File -Force -Path "$markerDir\05-promote-no-reboot" | Out-Null
} catch {
    Write-Host "FATAL: Install-ADDSForest threw: $($_.Exception.Message)"
    New-Item -ItemType File -Force -Path "$markerDir\05-promote-failed" | Out-Null
    Stop-Transcript
    exit 1
}
Stop-Transcript
PROMOTE_EOF

set +e
# SSM Failed/DeliveryTimedOut here is expected — Install-ADDSForest
# reboots the box, killing the SSM connection. Real success is
# verified via the AD-services poll + Get-ADUser count below.
run_powershell_file "$A2_ID" "$PROMOTE_TMP" "Install-ADDSForest" 1800 || true
set -e

log "phase 3/4: wait for DC reboot + AD services to come online"
sleep 30
wait_for_ssm "$A2_ID"

# After Install-ADDSForest reboot, AD services take 60-180s to start.
# Poll for ADWS to be Running before declaring promote successful.
log "phase 3/4: polling for AD services"
deadline=$((SECONDS + 600))
ad_ready=0
while (( SECONDS < deadline )); do
    # shellcheck disable=SC2016  # PowerShell expressions, not bash
    AD_CMD_ID="$(aws_ssm ssm send-command --instance-ids "$A2_ID" \
        --document-name "$SSM_PS_DOC" \
        --parameters 'commands=["(Get-Service ADWS,KDC,NTDS | Where-Object {$_.Status -ne \"Running\"} | Measure-Object).Count"]' \
        --query "$SSM_QUERY_COMMAND_ID" --output text)"
    sleep 5
    ad_status="$(aws_ssm ssm get-command-invocation \
        --command-id "$AD_CMD_ID" --instance-id "$A2_ID" \
        --query "$SSM_QUERY_STDOUT" --output text 2>/dev/null | tr -d '[:space:]')"
    if [[ "$ad_status" == "0" ]]; then
        log "phase 3/4: AD services running (ADWS+KDC+NTDS)"
        ad_ready=1
        break
    fi
    log "phase 3/4: still waiting for AD services (not-running count=${ad_status:-?})"
    sleep 15
done
if (( ad_ready == 0 )); then
    log "[FATAL] AD services did not start within 10 minutes after Install-ADDSForest reboot"
    log "[FATAL] dumping promote.log:"
    DUMP_CMD_ID="$(aws_ssm ssm send-command --instance-ids "$A2_ID" \
        --document-name "$SSM_PS_DOC" \
        --parameters 'commands=["Get-Content C:\\polaris-promote.log -Tail 40 -ErrorAction SilentlyContinue"]' \
        --query "$SSM_QUERY_COMMAND_ID" --output text)"
    sleep 5
    aws_ssm ssm get-command-invocation \
        --command-id "$DUMP_CMD_ID" --instance-id "$A2_ID" \
        --query "$SSM_QUERY_STDOUT" --output text 2>&1 | tail -40
    exit 1
fi

# --- Phase 4: a2_setup.ps1 ---------------------------------------------------
# Scheduled task SHOULD have run it at boot, but re-run explicitly so we
# have a clean stdout trace and can gate the test on its exit code. The
# script is idempotent.
log "phase 4/4: idempotent a2_setup.ps1 against running DC"
run_powershell_file "$A2_ID" "$SETUP_PS1" "a2_setup.ps1" 900

# Verify a2_setup actually populated the domain by counting users.
# shellcheck disable=SC2016  # PowerShell expression
SETUP_CMD_ID="$(aws_ssm ssm send-command --instance-ids "$A2_ID" \
    --document-name "$SSM_PS_DOC" \
    --parameters 'commands=["try { (Get-ADUser -Filter * | Measure-Object).Count } catch { 0 }"]' \
    --query "$SSM_QUERY_COMMAND_ID" --output text)"
sleep 5
user_count="$(aws_ssm ssm get-command-invocation \
    --command-id "$SETUP_CMD_ID" --instance-id "$A2_ID" \
    --query "$SSM_QUERY_STDOUT" --output text 2>/dev/null | tr -d '[:space:]')"
log "phase 4/4: domain user count=${user_count}"
# 17 = 15 a2_setup users + Administrator + Guest + krbtgt = 18; tolerate >=15
if [[ -z "$user_count" ]] || (( user_count < 15 )); then
    log "[FATAL] a2_setup.ps1 didn't populate domain users (count=${user_count:-?}, expected >=15)"
    exit 1
fi

log "=== A2 cold bootstrap complete (DC promoted, ${user_count} domain users) ==="
