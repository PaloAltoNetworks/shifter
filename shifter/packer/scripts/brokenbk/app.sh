#!/bin/bash
# Install Docker and configure Cortex Broken Bank application
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing Docker ==="
apt-get install -y docker.io docker-compose-v2
usermod -aG docker ubuntu
systemctl enable docker

echo "=== Installing git ==="
apt-get install -y git

echo "=== Cloning Cortex Broken Bank ==="
git clone https://github.com/gocortexio/gocortexbrokenbank.git /opt/brokenbk
chown -R ubuntu:ubuntu /opt/brokenbk

echo "=== Pre-pulling Docker images ==="
cd /opt/brokenbk
docker compose pull || true

echo "=== Creating systemd service for Broken Bank ==="
cat > /etc/systemd/system/brokenbk.service << 'EOF'
[Unit]
Description=Cortex Broken Bank
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/brokenbk
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable brokenbk.service

echo "=== Cortex Broken Bank setup complete ==="
echo "Application will start on boot via systemd"
echo "Flask server: port 8888"
echo "Tomcat server: port 9999"
