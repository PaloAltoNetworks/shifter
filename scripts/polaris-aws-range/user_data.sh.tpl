#!/bin/bash
# POLARIS bake-range bootstrap
# Installs Docker + docker-compose, pulls the polaris build tarball from S3,
# edits docker-compose.yml to publish Kali's 22 + 3389 to the EC2 host,
# then `docker compose up -d` so the whole range comes online.
set -euo pipefail
exec > >(tee /var/log/polaris-bootstrap.log) 2>&1

echo "=== polaris bootstrap starting $(date -u +%FT%TZ) ==="

export DEBIAN_FRONTEND=noninteractive

# Give apt a moment to finish any on-boot unattended-upgrades work
# before we try to hold the dpkg lock.
for i in 1 2 3 4 5; do
  if ! fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
    break
  fi
  echo "dpkg lock held, waiting..."
  sleep 5
done

apt-get update
apt-get install -y \
    docker.io \
    awscli \
    jq \
    unzip \
    curl

systemctl enable --now docker

# docker-compose-plugin is not in Ubuntu 22.04 apt. Install the v2 binary
# from docker's github release directly so `docker compose` works.
mkdir -p /usr/libexec/docker/cli-plugins
curl -fsSL \
    https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
    -o /usr/libexec/docker/cli-plugins/docker-compose
chmod +x /usr/libexec/docker/cli-plugins/docker-compose

# The host sshd on :22 would conflict with the Kali container's published
# port 22. Disable the host sshd and use SSM Session Manager for operator
# access instead. Port 22 on the host is now free for docker to forward to
# Kali.
systemctl disable --now ssh || true
systemctl mask ssh || true

# Pull the polaris build tarball via the instance profile.
mkdir -p /opt/polaris
cd /opt/polaris
aws s3 cp "${tarball_s3_uri}" polaris-build.tar.gz
tar xzf polaris-build.tar.gz

# Work from the build root (where docker-compose.yml lives).
cd /opt/polaris/scenario-dev/polaris/build

# Publish the Kali container's sshd (22) and xrdp (3389) on the EC2 host
# so the Shifter portal (terminal UI + Guacamole RDP) can reach them.
# Drop-in compose override keeps the original docker-compose.yml untouched.
cat > docker-compose.override.yml <<'COMPOSE_EOF'
services:
  a14-kali:
    ports:
      - "22:22"
      - "3389:3389"
COMPOSE_EOF

# Build + start the stack.
docker compose build
docker compose up -d

# Wait for A14 Kali to be reachable.
for i in $(seq 1 60); do
  if docker compose ps a14-kali | grep -q "Up"; then
    echo "=== a14-kali up ==="
    break
  fi
  sleep 2
done

docker compose ps | tee /var/log/polaris-compose-ps.log

echo "=== polaris bootstrap complete $(date -u +%FT%TZ) ==="
