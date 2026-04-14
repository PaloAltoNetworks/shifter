#!/bin/bash
# Test CTFd Configuration
# Validates the challenges JSON against known flags.
# Requires: ctfd-challenges.json in the repo

set -e

CONFIG=""
for f in "/home/atomik/src/shifter-k8s/docs/ctf/mechag/ctfd-challenges.json" \
         "./docs/ctf/mechag/ctfd-challenges.json" \
         "/tmp/ctfd-challenges.json"; do
    [ -f "$f" ] && CONFIG="$f" && break
done
[ -z "$CONFIG" ] && exit 77

python3 << PYEOF
import sys, json

CONFIG = "$CONFIG"
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

with open(CONFIG) as f:
    data = json.load(f)

challenges = data["challenges"]

# === 36 challenges ===
check("36 challenges defined", len(challenges) == 36, f"got {len(challenges)}")

# === All flags present and correct ===
EXPECTED_FLAGS = {
    1: "FLAG{8f3a2c1e9b7d4056}",
    2: "FLAG{d4e7b1f283a6c950}",
    3: "FLAG{a1c9e3f7054b82d6}",
    4: "FLAG{72b5e0d8f1a34c69}",
    5: "FLAG{5e9c2a0f73b148d6}",
    6: "FLAG{c6f8d2b3e91a4507}",
    7: "FLAG{4f2e8b7a1c6d9035}",
    8: "FLAG{3b7e9a2d1c8f4063}",
    9: "FLAG{7a1b3d9e2c8f0546}",
    10: "FLAG{e5d1f8c2a7b03946}",
    11: "FLAG{0e6f9c2d4a8b7135}",
    12: "FLAG{d8a3c5e9f1b07264}",
    13: "FLAG{8c5a0d3f7e1b2964}",
    14: "FLAG{2f8b4a6c1d9e7053}",
    15: "FLAG{9a4c7e2f58d0b163}",
    16: "FLAG{b3d7e1f0c8a24596}",
    17: "FLAG{6c0a9d4e7f2b8135}",
    18: "FLAG{1d4e7b0a3c9f8265}",
    19: "FLAG{a7f2c8d0e5b34169}",
    20: "FLAG{5b8e1d3a7c0f9246}",
    21: "FLAG{4b9e2a7d0c8f1365}",
    22: "FLAG{e2a9c4f7d8b01536}",
    23: "FLAG{0c7d8a2e5f1b3946}",
    24: "FLAG{8a0e3c7f2d5b1946}",
    25: "FLAG{3f6a9d1e7c4b0258}",
    26: "FLAG{7e2b0c5d9a4f8163}",
    27: "FLAG{6d1a8f3c7e0b4952}",
    28: "FLAG{a3f7d9e1c0b52846}",
    29: "FLAG{1f9b4e7c0a3d8265}",
    30: "FLAG{d4c8f0a2e6b71935}",
    31: "FLAG{2e8c0a5d7f3b1946}",
    32: "FLAG{9b3e7c1d0f5a2846}",
    33: "FLAG{c7a1e3f9d0b52864}",
    34: "FLAG{f0d8b2e6a4c71935}",
    35: "FLAG{8d2f5a0e7c9b3146}",
    36: "FLAG{0b7e3d9a1f6c4258}",
}

for c in challenges:
    cid = c["id"]
    flags = c.get("flags", [])
    check(f"challenge {cid} has flags", len(flags) > 0, "no flags defined")
    if flags:
        actual_flag = flags[0]["content"]
        expected = EXPECTED_FLAGS.get(cid)
        check(f"challenge {cid} flag matches", actual_flag == expected,
              f"got {actual_flag}, expected {expected}")

# === Categories ===
categories = set(c["category"] for c in challenges)
check("has M1 OSINT category", any("OSINT" in c for c in categories))
check("has M1 Front Office category", any("Front Office" in c for c in categories))
check("has M2 Lab category", any("Lab" in c for c in categories))
check("has M4 Bunker category", any("Bunker" in c for c in categories))

# === Point values ===
values = [c["value"] for c in challenges]
check("easy flags worth 50", values.count(50) >= 10)
check("medium flags worth 100", values.count(100) >= 8)
check("hard flags worth 200", values.count(200) >= 5)
check("expert flags worth 300", values.count(300) >= 3)
check("total points = 4400", sum(values) == 4400, f"got {sum(values)}")

# === Bunker challenges hidden until gate ===
bunker = [c for c in challenges if "Bunker" in c["category"]]
for c in bunker:
    check(f"bunker challenge {c['id']} hidden", c["state"] == "hidden",
          f"state={c['state']}")

# === All challenge IDs unique ===
ids = [c["id"] for c in challenges]
check("unique IDs", len(ids) == len(set(ids)))

# === All challenges have descriptions ===
for c in challenges:
    check(f"challenge {c['id']} has description", len(c.get("description", "")) > 10)

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
