#!/bin/bash
# Post-provision supervisor for BSides Ottawa Polaris event.
#
# Waits for orchestrate_provisioning.py to exit, then runs the two
# post-provision scripts in sequence:
#
#   1. apply_splice_watcher.py  — disconnects a14-kali from splice-link
#      and installs the runaway_complete watcher systemd unit.
#   2. apply_kali_bedrock_shard.py — bumps IMDSv2 hop limit, writes
#      /etc/profile.d/claude-bedrock.sh with shard env vars, adds
#      /etc/hosts entry for the Bedrock VPCE, smoke-tests claude -p.
#
# Writes a progress markdown doc at scripts/polaris-aws-range/
# postprovision_status.md and a full log at /tmp/postprovision.log so
# you can tail either while this runs unattended.
#
# Usage:
#   ./scripts/polaris-aws-range/run_postprovision.sh
#
# Env overrides:
#   AWS_PROFILE=<profile> (default panw-shifter-dev-workstation)
#   AWS_REGION=<region>   (default us-east-2)
set -uo pipefail

PROFILE="${AWS_PROFILE:-panw-shifter-dev-workstation}"
REGION="${AWS_REGION:-us-east-2}"
# apply_splice_watcher.py uses the default boto3 chain; export so it picks up our profile.
export AWS_PROFILE="$PROFILE"
export AWS_REGION="$REGION"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG=/tmp/postprovision.log
STATUS_MD="$SCRIPT_DIR/postprovision_status.md"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
now_edt() { TZ=America/New_York date +'%H:%M %Z'; }

rewrite_status() {
    {
        echo "# Post-provision supervisor status"
        echo
        echo "Last updated: $(now) / $(now_edt)"
        echo
        echo "## State"
        echo
        echo "- Orchestrator wait: $ORCH_STATE"
        echo "- Splice watcher:    $SPLICE_STATE"
        echo "- Bedrock shard:     $BEDROCK_STATE"
        echo
        echo "## Logs"
        echo
        echo "- supervisor: /tmp/postprovision.log"
        echo "- orchestrator: /tmp/orchestrator.log"
        echo "- this file: $STATUS_MD"
    } > "$STATUS_MD"
}

ORCH_STATE="waiting"
SPLICE_STATE="pending"
BEDROCK_STATE="pending"

{
    echo "=== supervisor start: $(now) / $(now_edt) ==="
    echo "profile=$PROFILE region=$REGION"
} > "$LOG"
rewrite_status

# -----------------------------------------------------------------------------
# Phase 1: wait for orchestrator to finish
# -----------------------------------------------------------------------------
echo "supervisor: waiting for orchestrator..." >> "$LOG"
while pgrep -f 'orchestrate_provisioning.py' >/dev/null 2>&1; do
    sleep 30
done
ORCH_STATE="done at $(now) / $(now_edt)"
echo "supervisor: orchestrator exited at $(now)" >> "$LOG"
rewrite_status

# -----------------------------------------------------------------------------
# Phase 2: splice watcher
# -----------------------------------------------------------------------------
SPLICE_STATE="running (started $(now_edt))"
rewrite_status
{
    echo ""
    echo "=== [$(now)] splice watcher: start ==="
} >> "$LOG"
python3 "$SCRIPT_DIR/apply_splice_watcher.py" \
    --region "$REGION" --yes >> "$LOG" 2>&1
SW_RC=$?
echo "=== [$(now)] splice watcher: exit=$SW_RC ===" >> "$LOG"
if [[ $SW_RC -eq 0 ]]; then
    SPLICE_STATE="ok (done $(now_edt))"
else
    SPLICE_STATE="FAILED rc=$SW_RC (see /tmp/postprovision.log)"
fi
rewrite_status

# Continue to bedrock shard even if splice failed — they're orthogonal.

# -----------------------------------------------------------------------------
# Phase 3: bedrock shard
# -----------------------------------------------------------------------------
BEDROCK_STATE="running (started $(now_edt))"
rewrite_status
{
    echo ""
    echo "=== [$(now)] bedrock shard: start ==="
} >> "$LOG"
python3 "$SCRIPT_DIR/apply_kali_bedrock_shard.py" \
    --profile "$PROFILE" --region "$REGION" --yes >> "$LOG" 2>&1
BS_RC=$?
echo "=== [$(now)] bedrock shard: exit=$BS_RC ===" >> "$LOG"
if [[ $BS_RC -eq 0 ]]; then
    BEDROCK_STATE="ok (done $(now_edt))"
else
    BEDROCK_STATE="FAILED rc=$BS_RC (see /tmp/postprovision.log)"
fi
rewrite_status

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo "" >> "$LOG"
echo "=== [$(now)] supervisor done. splice=$SW_RC bedrock=$BS_RC ===" >> "$LOG"
exit $(( SW_RC | BS_RC ))
