#!/bin/bash
# Test A14 — Kali attack box content
# Tests: README, mission brief, flag_submit script, Claude system prompt, modbus_client

set -e

# Content is in the repo
CONTENT_DIR=""
for d in "/home/atomik/src/shifter-k8s/docs/ctf/mechag/A14-kali" "/tmp/a14-content"; do
    [ -f "$d/README.md" ] && CONTENT_DIR="$d" && break
done
[ -z "$CONTENT_DIR" ] && exit 77

python3 << PYEOF
import sys, os

CONTENT_DIR = "$CONTENT_DIR"
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# README.md
readme = os.path.join(CONTENT_DIR, "README.md")
check("README.md exists", os.path.isfile(readme))
with open(readme) as f:
    content = f.read()
check("README mentions POLARIS", "POLARIS" in content)
check("README mentions boreas-systems.ctf", "boreas-systems.ctf" in content)
check("README lists 4 missions", "M1" in content and "M4" in content)
check("README mentions Claude", "claude" in content.lower() or "Claude" in content)
check("README mentions flag_submit", "flag_submit" in content)
check("README mentions modbus_scan", "modbus" in content.lower())

# Mission brief
brief = os.path.join(CONTENT_DIR, "mission_brief.txt")
check("mission_brief.txt exists", os.path.isfile(brief))
with open(brief) as f:
    content = f.read()
check("brief mentions AURORA COLLECTIVE", "AURORA COLLECTIVE" in content)
check("brief mentions PROJECT LEVIATHAN", "LEVIATHAN" in content)
check("brief has 4 missions", "MISSION 1" in content and "MISSION 4" in content)
check("brief mentions CTFd", "CTFd" in content)
check("brief mentions 4 hours", "4 hours" in content)
check("brief lists known personnel", "Harlan" in content and "Vasik" in content)
check("brief mentions nuclear/reactor", "nuclear" in content.lower() or "reactor" in content.lower())
check("brief has rules of engagement", "RULES OF ENGAGEMENT" in content)

# Flag submit script
flag_sh = os.path.join(CONTENT_DIR, "flag_submit.sh")
check("flag_submit.sh exists", os.path.isfile(flag_sh))
with open(flag_sh) as f:
    content = f.read()
check("flag_submit uses CTFd API", "ctfd" in content.lower() or "challenges/attempt" in content)
check("flag_submit takes FLAG argument", "FLAG" in content)

# Claude system prompt
prompt = os.path.join(CONTENT_DIR, "claude_system_prompt.txt")
check("claude_system_prompt.txt exists", os.path.isfile(prompt))
with open(prompt) as f:
    content = f.read()
check("prompt mentions POLARIS", "POLARIS" in content)
check("prompt says no flag locations", "do NOT know where flags" in content.lower() or "do not know where flags" in content.lower())
check("prompt allows exploitation help", "exploit" in content.lower() or "script" in content.lower())
check("prompt mentions Modbus", "Modbus" in content)

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
