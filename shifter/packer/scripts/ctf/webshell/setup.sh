#!/bin/bash
# CTF Box 0 - "WebShell" (Walkthrough) - Ubuntu
# Chain: Browse web -> cmd.php -> RCE as www-data -> sudo -u john -> SUID backup -> root
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing Apache + PHP ==="
apt-get update
apt-get install -y apache2 libapache2-mod-php php openssh-server

echo "=== Creating webshell (cmd.php) ==="
cat > /var/www/html/cmd.php << 'PHPEOF'
<html>
<head><title>System Status</title></head>
<body>
<h1>System Status Check</h1>
<form method="GET">
  <input type="text" name="cmd" placeholder="Enter command..." size="60">
  <input type="submit" value="Run">
</form>
<pre>
<?php
if (isset($_GET['cmd'])) {
    echo htmlspecialchars(shell_exec($_GET['cmd']));
}
?>
</pre>
</body>
</html>
PHPEOF
chown www-data:www-data /var/www/html/cmd.php

# Create a basic index page that hints at cmd.php
cat > /var/www/html/index.html << 'HTMLEOF'
<html>
<head><title>Server Management</title></head>
<body>
<h1>Server Management Portal</h1>
<p>Welcome to the server management portal.</p>
<!-- TODO: remove /cmd.php before production deployment -->
<p><a href="/info.php">Server Info</a></p>
</body>
</html>
HTMLEOF

cat > /var/www/html/info.php << 'PHPEOF'
<?php phpinfo(); ?>
PHPEOF

echo "=== Creating user john ==="
id john &>/dev/null || useradd -m -s /bin/bash john
echo "john:SuperSecret123!" | chpasswd

echo "=== Planting flags ==="
echo "FLAG{w3bsh3ll_us3r_0wn3d}" > /home/john/local.txt
chown john:john /home/john/local.txt
chmod 400 /home/john/local.txt

echo "FLAG{w3bsh3ll_r00t_pwn3d}" > /root/root.txt
chmod 400 /root/root.txt

echo "=== Creating SUID backup binary ==="
cat > /tmp/backup.c << 'CEOF'
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    if (argc < 2) {
        printf("Usage: backup <directory>\n");
        printf("Backs up the specified directory to /tmp/backup.tar.gz\n");
        return 1;
    }
    setuid(0);
    setgid(0);
    char cmd[512];
    snprintf(cmd, sizeof(cmd), "/bin/tar czf /tmp/backup.tar.gz %s", argv[1]);
    return system(cmd);
}
CEOF
apt-get install -y gcc
gcc -o /usr/local/bin/backup /tmp/backup.c
chmod u+s /usr/local/bin/backup
rm /tmp/backup.c

echo "=== Configuring sudo for www-data -> john ==="
echo "www-data ALL=(john) NOPASSWD: /bin/bash" > /etc/sudoers.d/www-data
chmod 440 /etc/sudoers.d/www-data

echo "=== Configuring SSH ==="
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl enable ssh

echo "=== Enabling services ==="
systemctl enable apache2

echo "=== WebShell box setup complete ==="
