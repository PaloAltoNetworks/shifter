#!/bin/bash
# Validation script for CTF Box 0 - WebShell
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
}

echo "=== Validating WebShell Box ==="

# Services
check "Apache is running" systemctl is-active apache2
check "SSH is running" systemctl is-active ssh

# Web content
check "cmd.php exists" test -f /var/www/html/cmd.php
check "index.html exists" test -f /var/www/html/index.html
check "cmd.php owned by www-data" test "$(stat -c %U /var/www/html/cmd.php)" = "www-data"
check "cmd.php contains shell_exec" grep -q "shell_exec" /var/www/html/cmd.php
check "index.html hints at cmd.php" grep -q "cmd.php" /var/www/html/index.html

# User
check "User john exists" id john
check "John has bash shell" grep -q "john.*bash" /etc/passwd

# Flags
check "User flag exists" test -f /home/john/local.txt
check "User flag owned by john" test "$(stat -c %U /home/john/local.txt)" = "john"
check "Root flag exists" test -f /root/root.txt
check "Root flag owned by root" test "$(stat -c %U /root/root.txt)" = "root"

# SUID binary
check "Backup binary exists" test -f /usr/local/bin/backup
check "Backup binary has SUID" test -u /usr/local/bin/backup

# Sudo
check "www-data sudo rule exists" test -f /etc/sudoers.d/www-data
check "Sudo rule allows www-data -> john" grep -q "www-data.*john" /etc/sudoers.d/www-data

# SSH config
check "Effective SSH password auth enabled" sh -c 'sshd -T 2>/dev/null | grep -q "^passwordauthentication yes$"'

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[[ "$FAIL" -eq 0 ]] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit "$FAIL"
