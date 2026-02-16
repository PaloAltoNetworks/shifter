#!/bin/bash

# Validation script for host-based CTF setup

echo "=== CTF Host Setup Validation ==="
echo ""

# Test 1: Web server
echo "✓ Test 1: Web Server"
if curl -s http://localhost/ | grep -q "Victim Server"; then
    echo "  ✅ Apache is serving pages"
else
    echo "  ❌ Web server not responding"
fi

# Test 2: Command execution
echo "✓ Test 2: Command Execution Vulnerability"
RESULT=$(curl -s "http://localhost/cmd.php?cmd=whoami")
if echo "$RESULT" | grep -q "www-data"; then
    echo "  ✅ Command execution working (running as www-data)"
else
    echo "  ❌ Command execution failed"
fi

# Test 3: User john
echo "✓ Test 3: User Account"
if id john &>/dev/null; then
    echo "  ✅ User 'john' exists (UID: $(id -u john))"
else
    echo "  ❌ User 'john' not found"
fi

# Test 4: Flags
echo "✓ Test 4: Flags"
if sudo test -f /home/john/local.txt && sudo test -f /root/root.txt; then
    echo "  ✅ Both flags present"
    echo "     - User flag: $(sudo cat /home/john/local.txt)"
    echo "     - Root flag: $(sudo cat /root/root.txt)"
else
    echo "  ❌ Flags missing"
fi

# Test 5: SUID binary
echo "✓ Test 5: SUID Binary"
if [ -u /usr/local/bin/backup ]; then
    echo "  ✅ SUID binary configured: $(ls -la /usr/local/bin/backup)"
else
    echo "  ❌ SUID binary not properly configured"
fi

# Test 6: Sudo config
echo "✓ Test 6: Sudo Configuration"
if sudo -l -U www-data 2>/dev/null | grep -q "john"; then
    echo "  ✅ Sudo rule configured (www-data → john)"
else
    echo "  ❌ Sudo rule not found"
fi

# Test 7: SSH key backup
echo "✓ Test 7: SSH Key Backup"
if [ -f /var/backups/.old/john_ssh_key ]; then
    echo "  ✅ SSH key backup found"
else
    echo "  ❌ SSH key backup missing"
fi

# Test 8: SSH service
echo "✓ Test 8: SSH Service"
if systemctl is-active --quiet ssh; then
    echo "  ✅ SSH service is running"
else
    echo "  ❌ SSH service not running"
fi

echo ""
echo "=== Quick Attack Test ==="
echo ""
echo "1. Finding SUID binaries:"
curl -s "http://localhost/cmd.php?cmd=find+/usr/local/bin+-perm+-4000+2>/dev/null" | grep -oP '(?<=<pre>).*(?=</pre>)'

echo ""
echo "2. Finding SSH keys:"
curl -s "http://localhost/cmd.php?cmd=find+/var/backups+-name+*ssh*+2>/dev/null" | grep -oP '(?<=<pre>).*(?=</pre>)'

echo ""
echo "=== All Tests Complete ==="
echo ""
echo "🎯 Attack this system:"
echo "   Web:  http://localhost/cmd.php?cmd=<command>"
echo "   SSH:  ssh john@localhost (password: password123)"
echo ""
