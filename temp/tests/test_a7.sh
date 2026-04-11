#!/bin/bash
# Test A7 — Gitea Source Repository
# Requires: Gitea running on localhost:3000
# Tests:
#   - All 6 repos exist with correct visibility
#   - Access control: d_kowalski can clone internal but not private
#   - Access control: e_vasik can clone Lab-Access private repos
#   - Access control: r_tanaka cannot clone Project-L repos
#   - Flag 24: recoverable from navigation-controller git history
#   - Flag 29: recoverable from leviathan-assembly deleted file
#   - BRAIN_AUTH_TOKEN present in nav-controller config
#   - LEGACY_PASSPHRASE present in weapons-integration
#   - Tail diagnostic hint in manufacturing-orchestrator
#   - Leg calibration sequence in manufacturing-orchestrator

set -e

API="http://localhost:3000/api/v1"
curl -sf -u gitea_admin:AdminPass123! "$API/version" > /dev/null 2>&1 || exit 77

python3 << 'PYEOF'
import subprocess, sys, os, json, tempfile, shutil

errors = []

def check(name, condition, detail=""):
    if not condition:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

def clone(repo, user, password="TestPass123!"):
    """Clone a repo as a user. Returns (success, dir_path)."""
    d = tempfile.mkdtemp(prefix="a7test_")
    result = subprocess.run(
        ["git", "clone", "-q", f"http://{user}:{password}@localhost:3000/{repo}.git", d],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return True, d
    shutil.rmtree(d, ignore_errors=True)
    return False, None

dirs_to_clean = []

try:
    # === Repo existence (via admin API) ===
    import urllib.request, base64
    creds = base64.b64encode(b"gitea_admin:AdminPass123!").decode()
    req = urllib.request.Request(f"http://localhost:3000/api/v1/repos/search?limit=50",
                                 headers={"Authorization": f"Basic {creds}"})
    resp = urllib.request.urlopen(req)
    repos = json.loads(resp.read())["data"]
    repo_names = {r["full_name"] for r in repos}

    for expected in ["boreas-consulting/client-tools", "boreas-consulting/internal-docs",
                     "aurora/navigation-controller", "aurora/weapons-integration",
                     "aurora/manufacturing-orchestrator", "aurora/leviathan-assembly"]:
        check(f"repo {expected} exists", expected in repo_names, f"missing from {repo_names}")

    # === Access control ===
    # d_kowalski: can clone internal (leviathan-assembly), blocked from private (navigation-controller)
    ok, d = clone("aurora/leviathan-assembly", "d_kowalski")
    if d: dirs_to_clean.append(d)
    check("d_kowalski can clone leviathan-assembly (internal)", ok)

    ok, d = clone("aurora/navigation-controller", "d_kowalski")
    if d: dirs_to_clean.append(d)
    check("d_kowalski blocked from navigation-controller (private)", not ok)

    # e_vasik: can clone Lab-Access and Project-L repos
    ok, d_nav = clone("aurora/navigation-controller", "e_vasik")
    if d_nav: dirs_to_clean.append(d_nav)
    check("e_vasik can clone navigation-controller (Lab-Access)", ok)

    ok, d_wep = clone("aurora/weapons-integration", "e_vasik")
    if d_wep: dirs_to_clean.append(d_wep)
    check("e_vasik can clone weapons-integration (Project-L)", ok)

    # r_tanaka: can clone Lab-Access but NOT Project-L
    ok, d = clone("aurora/manufacturing-orchestrator", "r_tanaka")
    if d: dirs_to_clean.append(d)
    check("r_tanaka can clone manufacturing-orchestrator (Lab-Access)", ok)
    d_mfg = d

    ok, d = clone("aurora/weapons-integration", "r_tanaka")
    if d: dirs_to_clean.append(d)
    check("r_tanaka blocked from weapons-integration (Project-L)", not ok)

    # === Flag 24: git history in navigation-controller ===
    if d_nav:
        result = subprocess.run(
            ["git", "-C", d_nav, "log", "-p", "--", ".github/workflows/deploy.yml"],
            capture_output=True, text=True
        )
        check("flag 24 in git history", "FLAG{8a0e3c7f2d5b1946}" in result.stdout,
              "flag not found in deploy.yml history")

    # === Flag 29: deleted file in leviathan-assembly ===
    ok, d_asm = clone("aurora/leviathan-assembly", "d_kowalski")
    if d_asm:
        dirs_to_clean.append(d_asm)
        # Verify schematic is NOT in working tree
        check("schematic.svg not in HEAD", not os.path.isfile(os.path.join(d_asm, "schematic.svg")))

        # Find deletion commit
        result = subprocess.run(
            ["git", "-C", d_asm, "log", "--diff-filter=D", "--format=%H", "--", "schematic.svg"],
            capture_output=True, text=True
        )
        del_commits = result.stdout.strip().split("\n")
        check("deletion commit found", len(del_commits) > 0 and del_commits[0], f"got: {del_commits}")

        if del_commits[0]:
            # Recover file from parent of deletion
            result = subprocess.run(
                ["git", "-C", d_asm, "show", f"{del_commits[0]}^:schematic.svg"],
                capture_output=True, text=True
            )
            check("flag 29 in recovered SVG", "FLAG{1f9b4e7c0a3d8265}" in result.stdout,
                  "flag not found in schematic.svg XML")
            check("SVG is actual SVG content", "<svg" in result.stdout, "not valid SVG")

    # === Cross-asset data in repos ===
    # BRAIN_AUTH_TOKEN in nav-controller
    if d_nav:
        config_path = os.path.join(d_nav, "config.yaml")
        check("config.yaml exists", os.path.isfile(config_path))
        if os.path.isfile(config_path):
            with open(config_path) as f:
                config = f.read()
            check("BRAIN_AUTH_TOKEN in config", "a4f8e2c1d7b03965e8f2a1c4d7b03965" in config,
                  "token not found")
            check("Modbus targets in config", "10.10.40.10" in config, "tail controller IP missing")

    # LEGACY_PASSPHRASE in weapons-integration
    if d_wep:
        crypto_path = os.path.join(d_wep, "src", "crypto_config.py")
        check("crypto_config.py exists", os.path.isfile(crypto_path))
        if os.path.isfile(crypto_path):
            with open(crypto_path) as f:
                crypto = f.read()
            check("LEGACY_PASSPHRASE present", "Pr0m3th3us_Unb0und_2024" in crypto)

    # brain_client.py in weapons-integration
    if d_wep:
        brain_path = os.path.join(d_wep, "src", "brain_client.py")
        check("brain_client.py exists", os.path.isfile(brain_path))
        if os.path.isfile(brain_path):
            with open(brain_path) as f:
                brain = f.read()
            check("brain_client documents handshake protocol", "SHA256" in brain or "sha256" in brain)
            check("brain_client references serial numbers", "serial" in brain.lower())

    # Tail diagnostic hint in manufacturing-orchestrator
    if d_mfg:
        deploy_path = os.path.join(d_mfg, "playbooks", "deploy_combat_ai.yml")
        check("deploy_combat_ai.yml exists", os.path.isfile(deploy_path))
        if os.path.isfile(deploy_path):
            with open(deploy_path) as f:
                playbook = f.read()
            check("tail diagnostic mode 3 hint", "mode" in playbook and "3" in playbook,
                  "diagnostic mode hint not found")
            check("leg calibration sequence hint", "0" in playbook and "1" in playbook and "2" in playbook,
                  "calibration sequence not found")

finally:
    for d in dirs_to_clean:
        shutil.rmtree(d, ignore_errors=True)

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
