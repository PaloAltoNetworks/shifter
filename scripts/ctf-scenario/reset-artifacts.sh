#!/bin/bash
# Reset attacker artifacts without removing the CTF setup

echo "=== Resetting Attacker Artifacts ==="
echo ""

# Clean up any extra files in web root (keep only the legitimate ones)
echo "🧹 Cleaning web root..."
sudo find /var/www/html -type f ! -name "cmd.php" ! -name "note.txt" ! -name "index.html" -delete 2>/dev/null
echo "  ✅ Web root cleaned"

# Clear john's bash history
echo "🧹 Clearing bash history..."
sudo rm -f /home/john/.bash_history 2>/dev/null
echo "  ✅ Bash history cleared"

# Kill any processes running as john
echo "🧹 Killing john's processes..."
sudo pkill -u john 2>/dev/null || true
echo "  ✅ Processes cleared"

# Clear any suspicious files in /tmp owned by john or www-data
echo "🧹 Cleaning /tmp..."
sudo find /tmp -user john -delete 2>/dev/null || true
sudo find /tmp -user www-data -type f -delete 2>/dev/null || true
echo "  ✅ Temp files cleaned"

# Reset john's home directory to clean state (except .ssh and local.txt)
echo "🧹 Resetting john's home..."
sudo find /home/john -type f ! -path "*/.ssh/*" ! -name "local.txt" ! -name ".bash*" ! -name ".profile" -delete 2>/dev/null || true
echo "  ✅ Home directory reset"

# Clear root's bash history (if attacker got root)
echo "🧹 Clearing root history..."
sudo rm -f /root/.bash_history 2>/dev/null
echo "  ✅ Root history cleared"

# Verify flags are still in place
echo ""
echo "🔍 Verifying CTF integrity..."
if sudo test -f /home/john/local.txt && sudo test -f /root/root.txt; then
    echo "  ✅ Flags intact"
else
    echo "  ⚠️  Warning: Flags may be missing"
fi

if [ -u /usr/local/bin/backup ]; then
    echo "  ✅ SUID binary intact"
else
    echo "  ⚠️  Warning: SUID binary missing"
fi

if id john &>/dev/null; then
    echo "  ✅ User john intact"
else
    echo "  ⚠️  Warning: User john missing"
fi

echo ""
echo "=== Reset Complete - Ready for Fresh Attack ==="
echo ""
