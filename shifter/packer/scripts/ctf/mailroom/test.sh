#!/bin/bash
# Validation script for CTF Box 1 - MailRoom
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

echo "=== Validating MailRoom Box ==="

# Services
check "vsftpd is running" systemctl is-active vsftpd
check "SSH is running" systemctl is-active ssh
check "postfix is running" systemctl is-active postfix

# FTP anonymous content
check "FTP root exists" test -d /srv/ftp
check "onboarding.txt exists" test -f /srv/ftp/notes/onboarding.txt
check "employees.txt exists" test -f /srv/ftp/employees.txt
check "onboarding mentions password format" grep -q "Welcome<username>2024!" /srv/ftp/notes/onboarding.txt
check "employees lists svc-mail" grep -q "svc-mail" /srv/ftp/employees.txt

# vsftpd config
check "Anonymous FTP enabled" grep -q "anonymous_enable=YES" /etc/vsftpd.conf
check "FTP anon root set" grep -q "anon_root=/srv/ftp" /etc/vsftpd.conf

# User
check "User svc-mail exists" id svc-mail
check "svc-mail has bash shell" grep -q "svc-mail.*bash" /etc/passwd

# Vulnerable script
check "mail-backup.sh exists" test -f /opt/mail-backup.sh
check "mail-backup.sh is executable" test -x /opt/mail-backup.sh
check "mail-backup.sh calls tar without full path" grep -q "^tar " /opt/mail-backup.sh || grep -q " tar " /opt/mail-backup.sh

# Sudo
check "svc-mail sudo rule exists" test -f /etc/sudoers.d/svc-mail
check "Sudo allows svc-mail to run mail-backup.sh" grep -q "svc-mail.*NOPASSWD.*mail-backup" /etc/sudoers.d/svc-mail

# Flags
check "User flag exists" test -f /home/svc-mail/user.txt
check "User flag owned by svc-mail" test "$(stat -c %U /home/svc-mail/user.txt)" = "svc-mail"
check "Root flag exists" test -f /root/root.txt
check "Root flag owned by root" test "$(stat -c %U /root/root.txt)" = "root"

# SSH config
check "Effective SSH password auth enabled" sh -c 'sshd -T 2>/dev/null | grep -q "^passwordauthentication yes$"'

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[[ "$FAIL" -eq 0 ]] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit "$FAIL"
