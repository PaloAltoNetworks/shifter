#!/bin/bash
# Regression tests for shifter_platform/entrypoint-lib.sh.
#
# Covers the fail-closed contract introduced for issue #52:
# `fetch_runtime_secret` must propagate its python subshell's exit code
# instead of silently returning 0 with empty stdout. Without this, a
# Secrets Manager Decrypt failure (e.g., the dev portal CMK KMS-grant
# bug) would leave required env vars like DC_DOMAIN_PASSWORD empty and
# the container would run in a broken-but-up state instead of aborting
# at startup.
#
# Run with:
#   ./shifter/shifter_platform/tests/test_entrypoint_lib.sh
#
# Pattern mirrors shifter/packer/tests/test_scripts.sh.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(dirname "$SCRIPT_DIR")"
LIB="$PLATFORM_DIR/entrypoint-lib.sh"

FAILED=0
PASSED=0
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log_pass() { local msg="$1"; echo -e "${GREEN}✓${NC} ${msg}"; ((PASSED++)); return 0; }
log_fail() { local msg="$1"; echo -e "${RED}✗${NC} ${msg}"; ((FAILED++)); return 0; }

echo "=== entrypoint-lib.sh fail-closed tests ==="

# ---------------------------------------------------------------------------
# Test 1: fetch_runtime_secret propagates non-zero exit when its python
# subshell fails. This is the direct regression for issue #52.
# ---------------------------------------------------------------------------
if [[ ! -f "$LIB" ]]; then
    log_fail "entrypoint-lib.sh not found at $LIB"
else
    TMPBIN=$(mktemp -d)
    cat > "$TMPBIN/python" <<'PYSTUB'
#!/bin/bash
# Stub: exits non-zero so fetch_runtime_secret's subshell fails.
exit 7
PYSTUB
    chmod +x "$TMPBIN/python"

    PATH="$TMPBIN:$PATH" bash -c "
        source '$LIB'
        fetch_runtime_secret arn:aws:secretsmanager:us-east-2:0:secret:test
    "
    rc=$?

    if [[ "$rc" -ne 0 ]]; then
        log_pass "fetch_runtime_secret returns non-zero when python fails (got rc=$rc)"
    else
        log_fail "fetch_runtime_secret returned 0 despite python exit 7 — silent swallow regression!"
    fi

    rm -rf "$TMPBIN"
fi

# ---------------------------------------------------------------------------
# Test 2: A script using `set -euo pipefail` + `VAR=$(fetch_runtime_secret …)`
# aborts when the fetch fails. This is how the entrypoint actually consumes
# the function and is the contract callers rely on.
# ---------------------------------------------------------------------------
if [[ -f "$LIB" ]]; then
    TMPBIN=$(mktemp -d)
    cat > "$TMPBIN/python" <<'PYSTUB'
#!/bin/bash
exit 7
PYSTUB
    chmod +x "$TMPBIN/python"

    set +e
    PATH="$TMPBIN:$PATH" bash -c "
        set -euo pipefail
        source '$LIB'
        VAR=\$(fetch_runtime_secret arn:aws:secretsmanager:us-east-2:0:secret:test)
        echo \"reached after fetch with VAR=\$VAR\"
    " 2>/dev/null
    rc=$?
    set -e

    if [[ "$rc" -ne 0 ]]; then
        log_pass "set -e + VAR=\$(fetch_runtime_secret …) aborts on failure (got rc=$rc)"
    else
        log_fail "set -e + VAR=\$(fetch_runtime_secret …) continued after failure — outer script will run with empty VAR"
    fi

    rm -rf "$TMPBIN"
fi

# ---------------------------------------------------------------------------
# Test 3 (regression-shape): document that the LEGACY `export VAR=$(...)`
# pattern does NOT abort under `set -e`, which is why the production
# entrypoint had to split assignment from export. If a future refactor
# regresses to the legacy shape, the entrypoint would silently export
# an empty required env var (the original issue #52 failure mode); this
# test fails loudly if anyone removes the split.
# ---------------------------------------------------------------------------
if [[ -f "$LIB" ]]; then
    TMPBIN=$(mktemp -d)
    cat > "$TMPBIN/python" <<'PYSTUB'
#!/bin/bash
exit 7
PYSTUB
    chmod +x "$TMPBIN/python"

    PATH="$TMPBIN:$PATH" bash -c "
        set -euo pipefail
        source '$LIB'
        export LEGACY_VAR=\$(fetch_runtime_secret arn:aws:secretsmanager:us-east-2:0:secret:test)
        echo \"continued with LEGACY_VAR=\$LEGACY_VAR\"
    " 2>/dev/null
    rc=$?

    if [[ "$rc" -eq 0 ]]; then
        log_pass "legacy 'export VAR=\$(...)' pattern masks failure under set -e (documents why entrypoint must split assignment from export)"
    else
        log_fail "expected legacy shape to mask failure (rc=0) but got rc=$rc — bash semantics changed; revisit the split-assignment pattern in entrypoint.sh"
    fi

    rm -rf "$TMPBIN"
fi

# ---------------------------------------------------------------------------
# Test 4 (production-shape pin): the production entrypoint.sh MUST NOT
# wrap a `fetch_runtime_secret` (or piped python -c JSON parse) call
# inside `export VAR=$(...)`. That shape always returns 0 (export is
# itself a no-op for success) and would mask the helper's non-zero exit
# code, silently re-introducing the issue #52 failure mode. The split
# pattern is `VAR=$(...)` then `export VAR` on the next line, and only
# that shape lets `set -e` propagate.
# ---------------------------------------------------------------------------
ENTRYPOINT="$PLATFORM_DIR/entrypoint.sh"
if [[ ! -f "$ENTRYPOINT" ]]; then
    log_fail "entrypoint.sh not found at $ENTRYPOINT"
else
    # Grep for the forbidden patterns. Match `export <NAME>=$(...)` and
    # `export <NAME>=${...$(...)...}` where the substitution wraps a
    # fetch_runtime_secret call OR a python -c (the two patterns that
    # could swallow secret-fetch / JSON-parse failures). The `-E`
    # alternation keeps both classes in one grep pass; `-q` suppresses
    # output.
    if grep -qE 'export[[:space:]]+[A-Za-z_][A-Za-z0-9_]*=\$?\{?[^}]*\$\(.*(fetch_runtime_secret|python[[:space:]]*-c)' "$ENTRYPOINT"; then
        log_fail "entrypoint.sh contains an 'export VAR=\$(...)' pattern around fetch_runtime_secret or python -c — this masks fetch/parse failures under set -e (issue #52 regression). Split into 'VAR=\$(...)' then 'export VAR'."
        grep -nE 'export[[:space:]]+[A-Za-z_][A-Za-z0-9_]*=\$?\{?[^}]*\$\(.*(fetch_runtime_secret|python[[:space:]]*-c)' "$ENTRYPOINT" | head -5
    else
        log_pass "entrypoint.sh secret-hydration lines use split-assign-then-export (no 'export VAR=\$(...)' wrappers around fetch_runtime_secret or python -c)"
    fi
fi

# ---------------------------------------------------------------------------
# Test 5: When python succeeds, fetch_runtime_secret returns 0 and emits
# the secret string on stdout. Sanity check that the happy path still
# works after the fail-closed change.
# ---------------------------------------------------------------------------
if [[ -f "$LIB" ]]; then
    TMPBIN=$(mktemp -d)
    cat > "$TMPBIN/python" <<'PYSTUB'
#!/bin/bash
# Stub: prints a fake secret payload and exits cleanly. Mirrors the
# real python subshell's stdout contract.
echo '{"username":"dbuser","password":"shh"}'
exit 0
PYSTUB
    chmod +x "$TMPBIN/python"

    OUTPUT=$(
        PATH="$TMPBIN:$PATH" bash -c "
            source '$LIB'
            fetch_runtime_secret arn:aws:secretsmanager:us-east-2:0:secret:test
        "
    )
    rc=$?

    if [[ "$rc" -eq 0 && "$OUTPUT" == '{"username":"dbuser","password":"shh"}' ]]; then
        log_pass "fetch_runtime_secret returns 0 and emits stdout on success"
    else
        log_fail "happy-path regression: rc=$rc output=$OUTPUT"
    fi

    rm -rf "$TMPBIN"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Results: $PASSED passed, $FAILED failed ==="
if [[ "$FAILED" -gt 0 ]]; then
    exit 1
fi
exit 0
