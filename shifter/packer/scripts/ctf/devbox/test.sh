#!/bin/bash
# Validation script for CTF Box 3 - DevBox
set -uo pipefail

PASS=0
FAIL=0

check() {
    local desc="$1"
    shift
    if "$@" > /dev/null 2>&1; then
        echo "[PASS] $desc"
        ((PASS++))
    else
        echo "[FAIL] $desc"
        ((FAIL++))
    fi
    return 0
}

echo "=== Validating DevBox ==="

# Services
check "nginx is running" systemctl is-active nginx
check "devnotes service is running" systemctl is-active devnotes
check "SSH is running" systemctl is-active ssh

# Node.js app
check "DevNotes app directory exists" test -d /opt/devnotes
check "server.js exists" test -f /opt/devnotes/server.js
check "package.json exists" test -f /opt/devnotes/package.json
check "node_modules exists" test -d /opt/devnotes/node_modules
check "Notes directory exists" test -d /opt/devnotes/notes
check "App listening on port 3000" ss -tlnp | grep -q ":3000"

# Vulnerable search (check code has the injection point)
check "Search endpoint exists in server.js" grep -q "/search" /opt/devnotes/server.js
check "Search uses unsanitized input" grep -q "grep.*query" /opt/devnotes/server.js

# nginx config
check "nginx devnotes config exists" test -f /etc/nginx/sites-available/devnotes
check "nginx proxies to 3000" grep -q "proxy_pass.*3000" /etc/nginx/sites-available/devnotes
check "Port 80 responds" curl -s -o /dev/null -w "%{http_code}" http://localhost | grep -q "200"

# Users
check "User devops exists" id devops
check "User node exists" id node

# .env with vault creds
check ".env file exists" test -f /opt/devnotes/.env
check ".env contains VAULT_ADMIN" grep -q "VAULT_ADMIN=vaultadmin" /opt/devnotes/.env
check ".env contains VAULT_PASS" grep -q "VAULT_PASS=DevOps2024!" /opt/devnotes/.env
check ".env owned by node" test "$(stat -c %U /opt/devnotes/.env)" = "node"

# SSH key backup (privesc breadcrumb)
check "SSH key backup exists" test -f /opt/backups/devops_key.bak
check "SSH key is readable by node" test -r /opt/backups/devops_key.bak
check "devops authorized_keys exists" test -f /home/devops/.ssh/authorized_keys
check "Key matches authorized_keys" diff -q <(ssh-keygen -y -f /opt/backups/devops_key.bak) <(cat /home/devops/.ssh/authorized_keys)

# Sudo
check "devops sudo rule exists" test -f /etc/sudoers.d/devops
check "Sudo allows devops to run node" grep -q "devops.*NOPASSWD.*/usr/bin/node" /etc/sudoers.d/devops

# Flags
check "User flag exists" test -f /home/devops/user.txt
check "User flag owned by devops" test "$(stat -c %U /home/devops/user.txt)" = "devops"
check "Root flag exists" test -f /root/root.txt
check "Root flag owned by root" test "$(stat -c %U /root/root.txt)" = "root"

# SSH config
check "Effective SSH password auth enabled" sh -c 'sshd -T 2>/dev/null | grep -q "^passwordauthentication yes$"'

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[[ "$FAIL" -eq 0 ]] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit "$FAIL"
