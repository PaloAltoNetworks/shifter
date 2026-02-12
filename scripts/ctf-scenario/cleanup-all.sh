#!/bin/bash
# Complete cleanup script

echo "=== Cleaning up CTF scenario ==="

# Remove john user
sudo userdel -r john 2>/dev/null
echo "✓ John user removed"

# Remove web files
sudo rm -f /var/www/html/cmd.php
sudo rm -f /var/www/html/note.txt
sudo rm -f /var/www/html/out.txt
echo "✓ Web files removed"

# Remove SUID binary
sudo rm -f /usr/local/bin/backup
echo "✓ SUID binary removed"

# Remove sudo config
sudo rm -f /etc/sudoers.d/www-data_john
echo "✓ Sudo config removed"

# Remove SSH backup
sudo rm -rf /var/backups/.old
echo "✓ SSH backup removed"

# Remove flags
sudo rm -f /root/root.txt
echo "✓ Root flag removed"

# Remove temp files
rm -f /tmp/cmd.php /tmp/index.html /tmp/note.txt /tmp/vulnerable_binary.c
echo "✓ Temp files removed"

echo ""
echo "=== Cleanup complete ==="
