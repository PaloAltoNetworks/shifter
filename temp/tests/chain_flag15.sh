#!/bin/bash
# Chain test: Flag 15 — A1 creds backup email → A4 IT share backup log
#
# Path: Read Kowalski's "creds backup" email on A1 →
#       Extract file share service account credentials →
#       Access A4 IT share → Read backup_verification.log → flag 15
#
# Requires: A1 content at /tmp/a1-content/, A4 content at /tmp/a4-content/

set -e

[ -d "/tmp/a1-content/d.kowalski" ] || exit 77
[ -d "/tmp/a4-content/IT" ] || exit 77

python3 << 'PYEOF'
import sys, os, email, re
from email import policy

errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# Step 1: Read Kowalski's creds backup email
eml_path = "/tmp/a1-content/d.kowalski/02_creds_backup.eml"
with open(eml_path) as f:
    msg = email.message_from_file(f, policy=policy.default)
body = msg.get_content()

# Step 2: Extract file share credentials
check("email mentions fileserv", "fileserv" in body.lower())
check("email has service account name", "svc-fileshare" in body or "svc_fileshare" in body)

# Extract the file share password (not the wiki admin password)
# Look for the block that mentions fileserv
fileshare_section = body[body.lower().find("file share"):]
password_match = re.search(r"Pass:\s*(\S+)", fileshare_section)
check("file share password extractable", password_match is not None)
if password_match:
    password = password_match.group(1)
    check("password is F1l3Sh@r3Svc!", password == "F1l3Sh@r3Svc!", f"got: {password}")

# Step 3: The email mentions \\fileserv\IT has backup logs
check("email mentions IT share", "\\\\fileserv\\IT" in body or "IT" in body)

# Step 4: Access A4 IT share and read backup log
# In production this would be SMB auth, here we verify the file exists and contains flag 15
log_path = "/tmp/a4-content/IT/backup_verification.log"
check("backup log exists on A4", os.path.isfile(log_path))

with open(log_path) as f:
    log_content = f.read()

check("flag 15 in backup log", "FLAG{9a4c7e2f58d0b163}" in log_content)
check("backup log mentions svc-backup", "svc-backup" in log_content)

# Step 5: Verify the full chain makes narrative sense
check("email references the correct share path", "backup" in body.lower() or "IT" in body)

if errors:
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
