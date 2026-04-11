#!/bin/bash
# Test A6 — Engineering Workstation content
# Requires: A6 content at /tmp/a6-content/
# Tests all flags and filesystem structure

set -e

BASE="/tmp/a6-content"
[ -d "$BASE" ] || exit 77

python3 << 'PYEOF'
import sys, os, subprocess, tarfile, io

BASE = "/tmp/a6-content"
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# === Directory structure ===
for d in ["home/e.vasik/documents", "home/e.vasik/.gnupg",
          "home/r.tanaka/simulations/standard", "home/r.tanaka/simulations/midnight",
          "home/p.nielsen/designs", "home/jenkins",
          "opt/builds/latest", "opt/builds/archive/build-2847",
          "var/log/sim", "tmp/.deleted"]:
    check(f"dir exists: {d}", os.path.isdir(os.path.join(BASE, d)))

# === Flag 20: Jenkins credentials ===
creds = os.path.join(BASE, "home/jenkins/.credentials")
check("jenkins .credentials exists", os.path.isfile(creds))
with open(creds) as f:
    content = f.read()
check("flag 20 in jenkins creds", "FLAG{5b8e1d3a7c0f9246}" in content)

# === Flag 22: Reactor spec ===
spec = os.path.join(BASE, "opt/builds/latest/reactor_interface_spec.txt")
check("reactor spec exists", os.path.isfile(spec))
with open(spec) as f:
    content = f.read()
check("flag 22 in reactor spec", "FLAG{e2a9c4f7d8b01536}" in content)
check("reactor spec mentions Novikov", "Novikov" in content)

# === Flag 23: Binary in stress_test_44.tar.gz ===
archive = os.path.join(BASE, "home/r.tanaka/simulations/standard/stress_test_44.tar.gz")
check("stress_test_44.tar.gz exists", os.path.isfile(archive))
with tarfile.open(archive) as tf:
    for member in tf.getmembers():
        if member.name.endswith(".dat"):
            f = tf.extractfile(member)
            dat_content = f.read()
            result = subprocess.run(["strings"], input=dat_content, capture_output=True)
            check("flag 23 in binary .dat", b"FLAG{0c7d8a2e5f1b3946}" in result.stdout,
                  "flag not found via strings")
            break

# === Flag 25: MIDNIGHT-7 results ===
midnight = os.path.join(BASE, "home/r.tanaka/simulations/midnight/MIDNIGHT-7_results.dat")
check("MIDNIGHT-7 results exists", os.path.isfile(midnight))
with open(midnight) as f:
    content = f.read()
check("flag 25 in MIDNIGHT-7 results", "FLAG{3f6a9d1e7c4b0258}" in content)
check("MIDNIGHT-7 mentions MN07 simulation ID", "MN07" in content)

# === Flag 26: COG analysis hidden sheet in real XLSX ===
import openpyxl as oxl
cog_path = os.path.join(BASE, "home/p.nielsen/designs/center_of_gravity_analysis.xlsx")
check("COG xlsx exists", os.path.isfile(cog_path))
if os.path.isfile(cog_path):
    wb = oxl.load_workbook(cog_path)
    check("xlsx has 3 sheets", len(wb.sheetnames) == 3, f"got {wb.sheetnames}")
    check("xlsx has Frame sheet", "Frame" in wb.sheetnames)
    check("xlsx has Locomotion sheet", "Locomotion" in wb.sheetnames)
    check("xlsx has Integration sheet", "Integration" in wb.sheetnames)
    ws_int = wb["Integration"]
    check("Integration sheet is hidden", ws_int.sheet_state == "hidden", f"state={ws_int.sheet_state}")
    flag_val = ws_int.cell(row=10, column=2).value
    check("flag 26 in hidden Integration sheet", flag_val == "FLAG{7e2b0c5d9a4f8163}", f"got: {flag_val}")

# === Flag 30 chain artifacts ===
gpg_file = os.path.join(BASE, "tmp/.deleted/full_integration_sim.mp4.gpg")
check("encrypted GPG file exists", os.path.isfile(gpg_file))
check("GPG file is >0 bytes", os.path.getsize(gpg_file) > 100)

pub_key = os.path.join(BASE, "home/e.vasik/.gnupg/vasik_public.asc")
check("public key exists", os.path.isfile(pub_key))
with open(pub_key) as f:
    check("public key is PGP format", "BEGIN PGP PUBLIC KEY" in f.read())

agent_conf = os.path.join(BASE, "home/e.vasik/.gnupg/gpg-agent.conf")
check("gpg-agent.conf exists", os.path.isfile(agent_conf))
with open(agent_conf) as f:
    content = f.read()
check("agent conf hints at A8", "researchdb" in content or "compartment" in content)

# === Nielsen .pgpass (A8 credentials) ===
pgpass = os.path.join(BASE, "home/p.nielsen/.pgpass")
check(".pgpass exists", os.path.isfile(pgpass))
with open(pgpass) as f:
    content = f.read()
check(".pgpass has lab_mfg creds", "lab_mfg" in content and "Mfg2025!" in content)

# === 47 simulation archives ===
archive_dir = os.path.join(BASE, "home/r.tanaka/simulations/standard")
archives = [f for f in os.listdir(archive_dir) if f.endswith(".tar.gz")]
check("47 simulation archives", len(archives) == 47, f"found {len(archives)}")

# === Bipedal references in specific archives ===
for num, keyword in [(28, "Bipedal"), (31, "bipedal"), (44, "Stabilization")]:
    archive_path = os.path.join(archive_dir, f"stress_test_{num}.tar.gz")
    with tarfile.open(archive_path) as tf:
        for member in tf.getmembers():
            if member.name.endswith(".log"):
                content = tf.extractfile(member).read().decode()
                check(f"stress_test_{num} has '{keyword}'", keyword.lower() in content.lower(),
                      f"keyword not found in log")
                break

# === Simulation log shows after-hours runs ===
simlog = os.path.join(BASE, "var/log/sim/simulation.log")
check("simulation log exists", os.path.isfile(simlog))
with open(simlog) as f:
    content = f.read()
check("sim log shows MIDNIGHT-7", "MIDNIGHT-7" in content)
check("sim log shows 02:00 AM runs", "02:0" in content)

# === MIDNIGHT sim files (7 files) ===
midnight_dir = os.path.join(BASE, "home/r.tanaka/simulations/midnight")
sim_files = [f for f in os.listdir(midnight_dir) if f.endswith(".sim")]
check("7 MIDNIGHT sim files", len(sim_files) == 7, f"found {len(sim_files)}")

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
