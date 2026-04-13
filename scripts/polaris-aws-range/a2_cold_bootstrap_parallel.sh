#!/usr/bin/env bash
# Fan-out wrapper for a2_cold_bootstrap.sh — runs one cold bootstrap per
# A2 DC instance id in parallel, with one log file per range and an
# aggregate success/failure report at the end.
#
# Usage:
#
#   ./a2_cold_bootstrap_parallel.sh i-xxxxx i-yyyyy i-zzzzz
#
# or (no args) read range_indices + a2 instance ids from `terraform output`:
#
#   ./a2_cold_bootstrap_parallel.sh
#
# Environment overrides (same as a2_cold_bootstrap.sh):
#
#   AWS_PROFILE (default: panw-shifter-dev-workstation)
#   AWS_REGION  (default: us-east-2)
#   POLARIS_BOOTSTRAP_LOG_DIR (default: /tmp/polaris-bootstrap-<epoch>)
#
# Each per-instance run writes to $LOG_DIR/<instance-id>.log. On exit the
# wrapper prints a one-line-per-instance summary (SUCCESS / FAILED) and
# exits non-zero if any child failed.
#
# Important: a2_cold_bootstrap.sh is idempotent and the SSM commands it
# issues are per-instance, so running N in parallel from one host has no
# cross-range interference — each has its own /tmp file, its own SSM
# command ids, and its own transcript on the target Windows box.

set -uo pipefail

AWS_PROFILE="${AWS_PROFILE:-panw-shifter-dev-workstation}"
AWS_REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE AWS_REGION

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHILD_SCRIPT="${SCRIPT_DIR}/a2_cold_bootstrap.sh"

if [[ ! -x "$CHILD_SCRIPT" ]]; then
    echo "missing $CHILD_SCRIPT" >&2
    exit 1
fi

declare -a TARGETS=()
if (( $# > 0 )); then
    TARGETS=("$@")
else
    # Pull a2 instance ids from the refactored TF outputs (map keyed by
    # range index). Requires terraform + a current state file.
    if ! which terraform >/dev/null 2>&1; then
        echo "no targets passed and terraform not on PATH" >&2
        exit 1
    fi
    mapfile -t TARGETS < <(
        terraform -chdir="$SCRIPT_DIR" output -json range_a2_instance_ids 2>/dev/null \
            | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(v) for v in d.values()]'
    )
    if (( ${#TARGETS[@]} == 0 )); then
        echo "terraform output range_a2_instance_ids is empty" >&2
        exit 1
    fi
fi

LOG_DIR="${POLARIS_BOOTSTRAP_LOG_DIR:-/tmp/polaris-bootstrap-$(date +%s)}"
mkdir -p "$LOG_DIR"

ts() { date -u +%FT%TZ; }
log() { echo "[$(ts)] $*"; }

log "=== a2 cold bootstrap fan-out ==="
log "targets: ${TARGETS[*]}"
log "log dir: $LOG_DIR"

declare -a PIDS=()
declare -A PID_TO_TARGET=()
for target in "${TARGETS[@]}"; do
    logfile="${LOG_DIR}/${target}.log"
    log "launching bootstrap for ${target} -> ${logfile}"
    (
        "$CHILD_SCRIPT" "$target" > "$logfile" 2>&1
    ) &
    pid=$!
    PIDS+=("$pid")
    PID_TO_TARGET["$pid"]="$target"
done

log "waiting for ${#PIDS[@]} bootstrap child(ren)..."

declare -A RESULTS=()
for pid in "${PIDS[@]}"; do
    target="${PID_TO_TARGET[$pid]}"
    if wait "$pid"; then
        RESULTS["$target"]="SUCCESS"
        log "  ${target}: SUCCESS"
    else
        RESULTS["$target"]="FAILED"
        log "  ${target}: FAILED (see ${LOG_DIR}/${target}.log)"
    fi
done

log "=== summary ==="
rc=0
for target in "${TARGETS[@]}"; do
    status="${RESULTS[$target]:-UNKNOWN}"
    printf '  %-22s %s\n' "$target" "$status"
    if [[ "$status" != "SUCCESS" ]]; then
        rc=1
    fi
done

exit "$rc"
