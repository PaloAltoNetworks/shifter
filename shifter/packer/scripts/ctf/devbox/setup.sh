#!/bin/bash
# CTF Box 3 - "DevBox" - Ubuntu
# Chain: Command injection in DevNotes search -> reverse shell as node ->
#        SSH key in /opt/backups -> SSH as devops -> sudo node -> GTFOBins -> root
# Dual-homed: second NIC on 10.0.2.0/24 with .env containing vault creds
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing packages ==="
apt-get update
apt-get install -y nginx curl

# Install Node.js 18.x from NodeSource (apt nodejs is too old for Express 4.18)
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt-get install -y nodejs

echo "=== Creating users ==="
id devops &>/dev/null || useradd -m -s /bin/bash devops
id node &>/dev/null || useradd -r -m -s /bin/bash node

echo "=== Creating DevNotes application ==="
mkdir -p /opt/devnotes

cat > /opt/devnotes/package.json << 'PKGEOF'
{
  "name": "devnotes",
  "version": "1.0.0",
  "description": "Developer Notes App",
  "main": "server.js",
  "dependencies": {
    "express": "^4.18.2"
  }
}
PKGEOF

# NOTE: This Node.js app is INTENTIONALLY VULNERABLE to command injection.
# This is a CTF challenge box designed for security training.
# The execSync call with unsanitized user input is the deliberate vulnerability.
cat > /opt/devnotes/server.js << 'JSEOF'
const express = require('express');
const { execSync } = require('child_process');
const app = express();

const notes = [
  { id: 1, title: "Sprint Planning", content: "Review backlog items for Q1 sprint", author: "devops", date: "2024-01-10" },
  { id: 2, title: "API Redesign", content: "Migrate REST endpoints to GraphQL", author: "mgarcia", date: "2024-01-12" },
  { id: 3, title: "Deploy Checklist", content: "Run tests, build docker image, push to registry", author: "devops", date: "2024-01-15" },
  { id: 4, title: "Vault Setup", content: "Configure vault server on internal network for secrets management", author: "devops", date: "2024-01-20" },
  { id: 5, title: "Backup Script", content: "Backup script moved to /opt/backups, runs nightly via cron", author: "node", date: "2024-02-01" }
];

app.get('/', (req, res) => {
  res.send(`
    <html>
    <head><title>DevNotes</title>
    <style>
      body { font-family: monospace; max-width: 800px; margin: 40px auto; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
      h1 { color: #00d4ff; }
      .note { border: 1px solid #333; padding: 15px; margin: 10px 0; border-radius: 5px; background: #16213e; }
      .note h3 { color: #00d4ff; margin-top: 0; }
      .meta { color: #888; font-size: 0.9em; }
      input[type=text] { width: 300px; padding: 8px; background: #0f3460; border: 1px solid #00d4ff; color: #e0e0e0; border-radius: 3px; }
      button { padding: 8px 16px; background: #00d4ff; border: none; color: #1a1a2e; cursor: pointer; border-radius: 3px; font-weight: bold; }
      a { color: #00d4ff; }
    </style>
    </head>
    <body>
    <h1>DevNotes</h1>
    <form action="/search" method="GET">
      <input type="text" name="q" placeholder="Search notes...">
      <button type="submit">Search</button>
    </form>
    <hr>
    ${notes.map(n => `
      <div class="note">
        <h3>${n.title}</h3>
        <p>${n.content}</p>
        <div class="meta">By ${n.author} on ${n.date}</div>
      </div>
    `).join('')}
    </body>
    </html>
  `);
});

// INTENTIONALLY VULNERABLE - CTF challenge: OS command injection via search
app.get('/search', (req, res) => {
  const query = req.query.q || '';
  try {
    const cmd = "grep -ri '" + query + "' /opt/devnotes/notes/ 2>/dev/null || echo 'No results found'";
    const result = execSync(cmd, { timeout: 5000 }).toString();
    res.send(`
      <html>
      <head><title>DevNotes - Search</title>
      <style>
        body { font-family: monospace; max-width: 800px; margin: 40px auto; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
        h1 { color: #00d4ff; }
        pre { background: #0f3460; padding: 15px; border-radius: 5px; overflow-x: auto; }
        a { color: #00d4ff; }
      </style>
      </head>
      <body>
      <h1>DevNotes - Search Results</h1>
      <p><a href="/">Back to notes</a></p>
      <p>Results for: <strong>${query}</strong></p>
      <pre>${result}</pre>
      </body>
      </html>
    `);
  } catch (e) {
    res.send(`
      <html><body style="font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:20px;">
      <h1>Search Error</h1>
      <p><a href="/" style="color:#00d4ff;">Back to notes</a></p>
      <pre>${e.message}</pre>
      </body></html>
    `);
  }
});

app.listen(3000, '127.0.0.1', () => {
  console.log('DevNotes running on port 3000');
});
JSEOF

# Create notes directory for grep to search
mkdir -p /opt/devnotes/notes

cat > /opt/devnotes/notes/sprint.txt << 'EOF'
Sprint Planning - Review backlog items for Q1 sprint
Assigned to devops team
Priority: High
EOF

cat > /opt/devnotes/notes/api.txt << 'EOF'
API Redesign - Migrate REST endpoints to GraphQL
Frontend team needs updated SDK
Timeline: 2 weeks
EOF

cat > /opt/devnotes/notes/deploy.txt << 'EOF'
Deploy Checklist
1. Run tests
2. Build docker image
3. Push to registry
4. Update kubernetes manifests
5. Apply with kubectl
EOF

cat > /opt/devnotes/notes/vault.txt << 'EOF'
Vault Setup
- Configure vault server on internal network
- Vault is on the internal subnet (10.0.2.0/24)
- Access via SSH from this box only
- Credentials in /opt/devnotes/.env
EOF

cat > /opt/devnotes/notes/backup.txt << 'EOF'
Backup Configuration
- Script location: /opt/backups/
- Runs nightly via cron
- Backs up all dev databases
- SSH keys stored in backup dir for remote access
EOF

# Install npm dependencies
cd /opt/devnotes && npm install

# Set ownership
chown -R node:node /opt/devnotes

echo "=== Creating .env with vault credentials ==="
cat > /opt/devnotes/.env << 'ENVEOF'
# DevNotes Environment Configuration
NODE_ENV=production
PORT=3000

# Vault server credentials (internal network)
VAULT_HOST=10.0.2.10
VAULT_ADMIN=vaultadmin
VAULT_PASS=DevOps2024!
ENVEOF
chown node:node /opt/devnotes/.env
chmod 640 /opt/devnotes/.env

echo "=== Creating systemd service ==="
cat > /etc/systemd/system/devnotes.service << 'SVCEOF'
[Unit]
Description=DevNotes Application
After=network.target

[Service]
Type=simple
User=node
WorkingDirectory=/opt/devnotes
ExecStart=/usr/bin/node /opt/devnotes/server.js
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
SVCEOF
systemctl daemon-reload
systemctl enable devnotes
systemctl start devnotes

echo "=== Configuring nginx reverse proxy ==="
cat > /etc/nginx/sites-available/devnotes << 'NGXEOF'
server {
    listen 80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
NGXEOF
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/devnotes /etc/nginx/sites-enabled/devnotes
systemctl enable nginx
systemctl restart nginx

echo "=== Creating SSH key backup (privesc breadcrumb) ==="
mkdir -p /opt/backups
[ -f /opt/backups/devops_key.bak ] || ssh-keygen -t rsa -b 2048 -f /opt/backups/devops_key.bak -N "" -q
mkdir -p /home/devops/.ssh
cp /opt/backups/devops_key.bak.pub /home/devops/.ssh/authorized_keys
chown -R devops:devops /home/devops/.ssh
chmod 700 /home/devops/.ssh
chmod 600 /home/devops/.ssh/authorized_keys

# Make key readable by node user (the breadcrumb)
chmod 644 /opt/backups/devops_key.bak
chown node:node /opt/backups/devops_key.bak

echo "=== Configuring sudo for devops ==="
echo "devops ALL=(root) NOPASSWD: /usr/bin/node" > /etc/sudoers.d/devops
chmod 440 /etc/sudoers.d/devops

echo "=== Planting flags ==="
echo "FLAG{d3vb0x_us3r_0wn3d}" > /home/devops/user.txt
chown devops:devops /home/devops/user.txt
chmod 400 /home/devops/user.txt

echo "FLAG{d3vb0x_r00t_pwn3d}" > /root/root.txt
chmod 400 /root/root.txt

# SSH already installed and configured in base AMI (services.sh)

echo "=== DevBox setup complete ==="
