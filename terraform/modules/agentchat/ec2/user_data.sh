#!/bin/bash
set -euo pipefail

# Install Docker
dnf install -y docker git

# Configure Docker log rotation to prevent disk fill
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
EOF

systemctl enable docker
systemctl start docker

# Add ec2-user to docker group
usermod -aG docker ec2-user

# Install docker-compose (pinned version for reproducibility)
COMPOSE_VERSION="v2.32.4"
curl -L "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

echo "EC2 user data complete. Docker ready for container deployment."
