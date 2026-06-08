#!/usr/bin/env bash
# NORTHSTORM range network isolation smoketest.
#
# Verifies that the docker-compose topology enforces the design's
# network boundaries: every attack path the design says MUST work,
# works; every path the design says MUST NOT work, fails.
#
# Runs from the range host. Uses `docker exec` into each source container and
# python3 sockets to probe TCP reachability — python3 is present on every relevant container
# (alpine, debian, kali) which is not true for bash /dev/tcp.
#
# Usage:
#     bash tests/isolation-smoketest.sh
#
# Exits 0 on full pass, 1 on any failure.

set -u

# A2 DC IP. Resolve `dc01.boreas.local` from inside the dns container so the
# test works in any account / VPC layout where the Windows DC is not pinned to
# a legacy range address.
A2_DC_IP="${A2_DC_IP:-}"
if [[ -z "$A2_DC_IP" ]]; then
    A2_DC_IP="$(docker exec dns dig +short @127.0.0.1 dc01.boreas.local 2>/dev/null | head -n1)"
fi
if [[ -z "$A2_DC_IP" ]]; then
    A2_DC_IP="10.1.100.11"  # legacy fallback
    echo "[isolation] WARN: dc01.boreas.local did not resolve via dns container — falling back to $A2_DC_IP" >&2
fi
echo "[isolation] A2 DC IP: $A2_DC_IP"

FAIL=0
PASS_COUNT=0
pass() { PASS_COUNT=$((PASS_COUNT + 1)); echo "  [PASS] $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  [FAIL] $1"; }

# Return 0 if src can TCP connect to host:port within 2s, else 1.
can_reach() {
    local src="$1" host="$2" port="$3"
    docker exec "$src" python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('$host', $port))
    sys.exit(0)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1
}

must_reach() {
    local src="$1" host="$2" port="$3" label="$4"
    if can_reach "$src" "$host" "$port"; then
        pass "$src -> $label ($host:$port) reachable"
    else
        fail "$src -> $label ($host:$port) UNREACHABLE (design says must work)"
    fi
}

must_not_reach() {
    local src="$1" host="$2" port="$3" label="$4"
    if can_reach "$src" "$host" "$port"; then
        fail "$src -> $label ($host:$port) REACHABLE (design says must be isolated)"
    else
        pass "$src -> $label ($host:$port) isolated (expected)"
    fi
}

echo "NORTHSTORM network isolation smoketest"
echo "Topology: shared/corporate/scada/lab/bunker-ot bridges + A2 VM at $A2_DC_IP"

# =============================================================================
# A14 Kali (shared + corporate)
# Design: can reach A0, A1, A3, A4, A7, A2, DNS. Cannot reach lab, scada, or
# bunker-ot directly.
# =============================================================================
echo
echo "=== a14-kali (shared+corporate) ==="
echo "--- permitted: shared + corporate + A2 external VM ---"
must_reach a14-kali 172.20.0.10  80   "A0 website"
must_reach a14-kali 172.20.0.2   53   "DNS"
must_reach a14-kali 172.20.10.20 143  "A1 mail IMAP"
must_reach a14-kali 172.20.10.30 80   "A3 intranet"
must_reach a14-kali 172.20.10.40 445  "A4 SMB"
must_reach a14-kali "$A2_DC_IP" 389  "A2 LDAP (Windows DC in range VPC)"

echo
echo "--- permitted: A15 (new) and A16 (new) pivot hosts reachable from corporate ---"
must_reach a14-kali 172.20.10.50 22  "A15 ops-eng SSH (corporate face)"
must_reach a14-kali 172.20.10.50 80  "A15 Ops Telemetry dashboard"
must_reach a14-kali 172.20.10.60 22  "A16 research-analyst SSH (corporate face)"
must_reach a14-kali 172.20.10.60 8080 "A16 Research Dashboard"
# splice-link: A14 has a direct link to A9-splice (pre-wired in dev range
# to represent the post-collective-gate splice installation).
must_reach a14-kali 172.20.60.5  22  "A9 splice via splice-link (post-gate, dev-pre-wired)"

echo
echo "--- forbidden: scada / lab / bunker-ot (direct) ---"
must_not_reach a14-kali 172.20.40.10 502  "A5 SCADA Modbus"
must_not_reach a14-kali 172.20.40.10 8080 "A5 SCADA HMI"
must_not_reach a14-kali 172.20.30.10 22   "A6 engineering SSH"
must_not_reach a14-kali 172.20.30.30 5432 "A8 research DB"
must_not_reach a14-kali 172.20.30.20 3000 "A7 Gitea (lab) — must go through A16"
must_not_reach a14-kali 172.20.50.10 502  "A10 tail Modbus"
must_not_reach a14-kali 172.20.50.11 502  "A11 leg Modbus"
must_not_reach a14-kali 172.20.50.12 502  "A12 arms Modbus"
must_not_reach a14-kali 172.20.50.50 9100 "A13 brain"

# =============================================================================
# A3 Intranet (corporate ONLY after A15/A16 refactor)
# A3 used to be the scada+lab pivot; that role is now split between A15
# and A16. A3 is a plain corporate-facing wiki.
# =============================================================================
echo
echo "=== a3-intranet (corporate only) ==="
echo "--- permitted: corporate ---"
must_reach a3-intranet 172.20.10.20 143  "A1 mail IMAP (corporate)"
must_reach a3-intranet 172.20.10.40 445  "A4 SMB (corporate)"

echo
echo "--- forbidden: shared + scada + lab + bunker-ot ---"
must_not_reach a3-intranet 172.20.0.10  80   "A0 website (shared)"
must_not_reach a3-intranet 172.20.40.10 502  "A5 SCADA Modbus (scada) — was pivot, now A15"
must_not_reach a3-intranet 172.20.40.10 8080 "A5 SCADA HMI (scada) — was pivot, now A15"
must_not_reach a3-intranet 172.20.30.10 22   "A6 engineering SSH (lab) — was pivot, now A16"
must_not_reach a3-intranet 172.20.30.30 5432 "A8 research DB (lab) — was pivot, now A16"
must_not_reach a3-intranet 172.20.50.5  22   "A9 splice (bunker-ot)"
must_not_reach a3-intranet 172.20.50.10 502  "A10 tail (bunker-ot)"
must_not_reach a3-intranet 172.20.50.50 9100 "A13 brain (bunker-ot)"

# =============================================================================
# A15 Ops Engineer Workstation (corporate + scada) — the NEW scada pivot
# =============================================================================
echo
echo "=== a15-ops-eng (corporate+scada) - SCADA PIVOT ==="
echo "--- permitted: corporate + scada ---"
must_reach a15-ops-eng 172.20.10.20 143  "A1 mail IMAP (corporate)"
must_reach a15-ops-eng 172.20.10.40 445  "A4 SMB (corporate)"
must_reach a15-ops-eng 172.20.40.10 502  "A5 SCADA Modbus"
must_reach a15-ops-eng 172.20.40.10 8080 "A5 SCADA HMI"

echo
echo "--- forbidden: shared + lab + bunker-ot ---"
must_not_reach a15-ops-eng 172.20.0.10  80   "A0 website (shared)"
must_not_reach a15-ops-eng 172.20.30.10 22   "A6 engineering SSH (lab)"
must_not_reach a15-ops-eng 172.20.30.30 5432 "A8 research DB (lab)"
must_not_reach a15-ops-eng 172.20.50.5  22   "A9 splice (bunker-ot)"
must_not_reach a15-ops-eng 172.20.50.50 9100 "A13 brain (bunker-ot)"

# =============================================================================
# A16 Research Analyst Workstation (corporate + lab) — the NEW lab pivot
# =============================================================================
echo
echo "=== a16-research-analyst (corporate+lab) - LAB PIVOT ==="
echo "--- permitted: corporate + lab ---"
must_reach a16-research-analyst 172.20.10.20 143  "A1 mail IMAP (corporate)"
must_reach a16-research-analyst 172.20.10.40 445  "A4 SMB (corporate)"
must_reach a16-research-analyst 172.20.30.10 22   "A6 engineering SSH (lab)"
must_reach a16-research-analyst 172.20.30.30 5432 "A8 research DB (lab)"
must_reach a16-research-analyst 172.20.30.20 3000 "A7 Gitea (lab) — A16 is the on-ramp"

echo
echo "--- forbidden: shared + scada + bunker-ot ---"
must_not_reach a16-research-analyst 172.20.0.10  80   "A0 website (shared)"
must_not_reach a16-research-analyst 172.20.40.10 502  "A5 SCADA Modbus (scada)"
must_not_reach a16-research-analyst 172.20.40.10 8080 "A5 SCADA HMI (scada)"
must_not_reach a16-research-analyst 172.20.50.5  22   "A9 splice (bunker-ot)"
must_not_reach a16-research-analyst 172.20.50.50 9100 "A13 brain (bunker-ot)"

# =============================================================================
# A7 Gitea (lab only — was shared+lab, shared stripped so Kali must pivot)
# =============================================================================
echo
echo "=== a7-gitea (lab only) ==="
echo "--- permitted: lab ---"
must_reach a7-gitea 172.20.30.10 22   "A6 engineering SSH (lab)"
must_reach a7-gitea 172.20.30.30 5432 "A8 research DB (lab)"
must_reach a7-gitea 172.20.30.2  53   "DNS (lab)"

echo
echo "--- forbidden: shared + corporate + scada + bunker-ot ---"
must_not_reach a7-gitea 172.20.0.10  80   "A0 website (shared) — shared interface stripped"
must_not_reach a7-gitea 172.20.10.20 143  "A1 mail (corporate)"
must_not_reach a7-gitea 172.20.10.40 445  "A4 SMB (corporate)"
must_not_reach a7-gitea 172.20.40.10 502  "A5 SCADA (scada)"
must_not_reach a7-gitea 172.20.50.50 9100 "A13 brain (bunker-ot)"

# =============================================================================
# A1 mail (corporate only)
# =============================================================================
echo
echo "=== a1-mail (corporate only) ==="
must_reach     a1-mail 172.20.10.30 80   "A3 intranet (corporate)"
must_reach     a1-mail 172.20.10.40 445  "A4 SMB (corporate)"
must_not_reach a1-mail 172.20.0.10  80   "A0 website (shared)"
must_not_reach a1-mail 172.20.40.10 502  "A5 SCADA (scada)"
must_not_reach a1-mail 172.20.30.10 22   "A6 engineering SSH (lab)"
must_not_reach a1-mail 172.20.50.50 9100 "A13 brain (bunker-ot)"

# =============================================================================
# A4 fileshare (corporate only)
# =============================================================================
echo
echo "=== a4-fileshare (corporate only) ==="
must_reach     a4-fileshare 172.20.10.30 80   "A3 intranet (corporate)"
must_reach     a4-fileshare 172.20.10.20 143  "A1 mail IMAP (corporate)"
must_not_reach a4-fileshare 172.20.0.10  80   "A0 website (shared)"
must_not_reach a4-fileshare 172.20.40.10 502  "A5 SCADA (scada)"
must_not_reach a4-fileshare 172.20.30.30 5432 "A8 research DB (lab)"
must_not_reach a4-fileshare 172.20.50.11 502  "A11 leg (bunker-ot)"

# =============================================================================
# A6 engineering workstation (lab only)
# =============================================================================
echo
echo "=== a6-workstation (lab only) ==="
must_reach     a6-workstation 172.20.30.30 5432 "A8 research DB (lab)"
must_reach     a6-workstation 172.20.30.20 3000 "A7 Gitea via lab (lab)"
must_not_reach a6-workstation 172.20.0.10  80   "A0 website (shared)"
must_not_reach a6-workstation 172.20.10.40 445  "A4 SMB (corporate)"
must_not_reach a6-workstation 172.20.40.10 502  "A5 SCADA (scada)"
must_not_reach a6-workstation 172.20.50.50 9100 "A13 brain (bunker-ot)"

# =============================================================================
# A5 SCADA (scada only) — completely isolated except from A3
# =============================================================================
echo
echo "=== a5-scada (scada only) ==="
must_not_reach a5-scada 172.20.0.10  80   "A0 website (shared)"
must_not_reach a5-scada 172.20.10.40 445  "A4 SMB (corporate)"
must_not_reach a5-scada 172.20.30.30 5432 "A8 research DB (lab)"
must_not_reach a5-scada 172.20.50.50 9100 "A13 brain (bunker-ot)"

# =============================================================================
# A9 splice landing (bunker-ot only) — the only Bunker entry point
# =============================================================================
echo
echo "=== a9-splice (bunker-ot only) ==="
echo "--- permitted: intra-bunker ---"
must_reach a9-splice 172.20.50.10 502  "A10 tail Modbus"
must_reach a9-splice 172.20.50.11 502  "A11 leg Modbus"
must_reach a9-splice 172.20.50.12 502  "A12 arms Modbus"
must_reach a9-splice 172.20.50.50 9100 "A13 brain"

echo
echo "--- forbidden: everything else ---"
must_not_reach a9-splice 172.20.0.10  80   "A0 website (shared)"
must_not_reach a9-splice 172.20.10.40 445  "A4 SMB (corporate)"
must_not_reach a9-splice 172.20.40.10 502  "A5 SCADA (scada)"
must_not_reach a9-splice 172.20.30.30 5432 "A8 research DB (lab)"

# =============================================================================
# A13 brain (bunker-ot only) — can only talk to bunker
# =============================================================================
echo
echo "=== a13-brain (bunker-ot only) ==="
must_not_reach a13-brain 172.20.0.10  80   "A0 website (shared)"
must_not_reach a13-brain 172.20.10.40 445  "A4 SMB (corporate)"
must_not_reach a13-brain 172.20.40.10 502  "A5 SCADA (scada)"
must_not_reach a13-brain 172.20.30.30 5432 "A8 research DB (lab)"

echo
echo "=================================================="
echo "  PASS: $PASS_COUNT  FAIL: $FAIL"
echo "=================================================="
if (( FAIL == 0 )); then
    echo "NORTHSTORM isolation smoketest: PASS"
    exit 0
else
    echo "NORTHSTORM isolation smoketest: FAIL"
    exit 1
fi
