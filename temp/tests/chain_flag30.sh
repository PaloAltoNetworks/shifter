#!/bin/bash
# Chain test: Flag 30 — GPG decryption chain across A6, A8, A7
#
# Participant path:
#   1. Find encrypted file on A6: /tmp/.deleted/full_integration_sim.mp4.gpg
#   2. A6 .gnupg/gpg-agent.conf hints at A8 for private key
#   3. Connect to A8 as vasik (or SQLi from tanaka), extract base64 key blob
#   4. Decode and import the GPG private key
#   5. Find passphrase in A7: aurora/weapons-integration/src/crypto_config.py
#   6. Decrypt file → FLAG{d4c8f0a2e6b71935}
#
# Requires: PostgreSQL running with A8 data, Gitea running with A7 repos,
#           A6 content at /tmp/a6-content/

set -e

# Check prerequisites
pg_isready -q 2>/dev/null || { echo "PostgreSQL not running"; exit 77; }
curl -sf http://localhost:3000/api/v1/version > /dev/null 2>&1 || { echo "Gitea not running"; exit 77; }
[ -f /tmp/a6-content/tmp/.deleted/full_integration_sim.mp4.gpg ] || { echo "A6 content not found"; exit 77; }

python3 << 'PYEOF'
import subprocess, sys, os, tempfile, shutil

errors = []

def check(name, condition, detail=""):
    if not condition:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# Create a clean temporary GPG home (simulates participant starting fresh)
gpg_home = tempfile.mkdtemp(prefix="chain30_gpg_")
os.chmod(gpg_home, 0o700)
env = os.environ.copy()
env["GNUPGHOME"] = gpg_home

try:
    # === Step 1: Find encrypted file on A6 ===
    enc_file = "/tmp/a6-content/tmp/.deleted/full_integration_sim.mp4.gpg"
    check("encrypted file exists on A6", os.path.isfile(enc_file))
    check("encrypted file is >0 bytes", os.path.getsize(enc_file) > 0,
          f"size={os.path.getsize(enc_file)}")

    # === Step 2: Find hint in gpg-agent.conf ===
    agent_conf = "/tmp/a6-content/home/e.vasik/.gnupg/gpg-agent.conf"
    check("gpg-agent.conf exists", os.path.isfile(agent_conf))
    with open(agent_conf) as f:
        conf_text = f.read()
    check("agent conf hints at research database", "researchdb" in conf_text or "compartment" in conf_text,
          f"content: {conf_text[:100]}")

    # === Step 3: Extract GPG private key from A8 (as vasik with direct access) ===
    result = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-t", "-A", "-c",
         "SET ROLE vasik; SELECT key_data FROM compartment_b.key_storage WHERE key_owner = 'e.vasik';"],
        capture_output=True, text=True
    )
    key_b64 = "\n".join(l for l in result.stdout.strip().split("\n") if l.strip() != "SET")
    check("key blob extracted from A8", len(key_b64) > 1000, f"length={len(key_b64)}")

    # === Step 4: Decode and import the private key ===
    import base64
    key_pem = base64.b64decode(key_b64)
    key_file = os.path.join(gpg_home, "imported_key.asc")
    with open(key_file, "wb") as f:
        f.write(key_pem)

    result = subprocess.run(
        ["gpg", "--batch", "--yes", "--import", key_file],
        capture_output=True, text=True, env=env
    )
    check("GPG key imported successfully", result.returncode == 0 or "imported: 1" in result.stderr,
          f"rc={result.returncode}, stderr={result.stderr[:200]}")

    # === Step 5: Find passphrase in A7 (weapons-integration repo) ===
    # Clone the repo from Gitea
    repo_dir = tempfile.mkdtemp(prefix="chain30_repo_")
    result = subprocess.run(
        ["git", "clone", "-q",
         "http://e_vasik:TestPass123!@localhost:3000/aurora/weapons-integration.git",
         repo_dir],
        capture_output=True, text=True
    )
    check("weapons-integration cloned from A7", result.returncode == 0,
          f"rc={result.returncode}, stderr={result.stderr[:200]}")

    crypto_config = os.path.join(repo_dir, "src", "crypto_config.py")
    check("crypto_config.py exists in repo", os.path.isfile(crypto_config))

    with open(crypto_config) as f:
        config_text = f.read()

    # Extract passphrase
    passphrase = None
    for line in config_text.split("\n"):
        if "LEGACY_PASSPHRASE" in line and "=" in line:
            passphrase = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
    check("passphrase found in crypto_config.py", passphrase is not None, "LEGACY_PASSPHRASE not found")
    check("passphrase is correct", passphrase == "Pr0m3th3us_Unb0und_2024", f"got: {passphrase}")

    # === Step 6: Decrypt the file ===
    decrypted_file = os.path.join(gpg_home, "decrypted.txt")
    result = subprocess.run(
        ["gpg", "--batch", "--yes", "--passphrase", passphrase,
         "--pinentry-mode", "loopback",
         "--output", decrypted_file, "--decrypt", enc_file],
        capture_output=True, text=True, env=env
    )
    check("GPG decryption succeeded", result.returncode == 0,
          f"rc={result.returncode}, stderr={result.stderr[:200]}")

    if os.path.isfile(decrypted_file):
        with open(decrypted_file) as f:
            content = f.read()
        check("decrypted content contains flag 30", "FLAG{d4c8f0a2e6b71935}" in content,
              f"flag not found in {len(content)} chars of content")
        check("decrypted content is simulation data", "MIDNIGHT" in content or "LEVIATHAN" in content,
              "doesn't look like simulation content")
    else:
        check("decrypted file exists", False, "file not created")

    # Cleanup
    shutil.rmtree(repo_dir, ignore_errors=True)

finally:
    shutil.rmtree(gpg_home, ignore_errors=True)

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
