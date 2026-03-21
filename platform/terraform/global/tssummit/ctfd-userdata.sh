#!/bin/bash
set -ex

# Install Docker and dependencies
dnf install -y docker git nginx certbot python3-certbot-nginx
systemctl enable docker
systemctl start docker

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Clone and configure CTFd
mkdir -p /opt/ctfd
cd /opt/ctfd
git clone https://github.com/CTFd/CTFd.git .

# Generate secret key
SECRET_KEY=$(openssl rand -hex 32)

# Set environment in docker-compose override
cat > docker-compose.override.yml << YAML
services:
  ctfd:
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - WORKERS=4
      - REVERSE_PROXY=true
    restart: always
  db:
    restart: always
  cache:
    restart: always
YAML

# Start CTFd (listens on 8000)
docker-compose up -d

# Configure nginx as reverse proxy
cat > /etc/nginx/conf.d/ctfd.conf << 'NGINX'
server {
    listen 80;
    server_name ts2026.keplerops.com;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

# Remove default nginx config if present
rm -f /etc/nginx/conf.d/default.conf

systemctl enable nginx
systemctl start nginx

# Certbot will be run manually after DNS is pointed at the EIP

# Systemd service for CTFd
cat > /etc/systemd/system/ctfd.service << 'SYSTEMD'
[Unit]
Description=CTFd Platform
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/ctfd
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable ctfd
