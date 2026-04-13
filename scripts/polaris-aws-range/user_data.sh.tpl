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

# The shifter-ubuntu base AMI ships with a bunch of pre-installed and
# pre-started services (ssh on 22, xrdp on 3389, apache2 on 80, smbd/nmbd
# on 139/445, vsftpd on 21, mysql on 3306). Those compete with the polaris
# containers for host ports — particularly Kali's sshd (22) and xrdp (3389)
# that we publish to the host for portal Terminal UI + Guacamole RDP.
# Disable + mask all of them before docker compose up so first boot is
# clean. Operator access to the VM is via SSM Session Manager, not host ssh.
for svc in ssh xrdp xrdp-sesman apache2 smbd nmbd mysql vsftpd; do
    systemctl disable --now "$svc" 2>/dev/null || true
    systemctl mask "$svc" 2>/dev/null || true
done

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

# Inject the operator SSH pubkey into a14-kali so the Shifter portal's
# Terminal UI (which key-auths as kali via the matching private key in
# Secrets Manager) can SSH in. Value templated from the
# `kali_authorized_key` terraform variable so it survives a cold rebuild
# without a manual SSM follow-up step. Blank value = skip (useful if the
# operator rotates keys out-of-band).
KALI_AUTHORIZED_KEY='${kali_authorized_key}'
if [[ -n "$KALI_AUTHORIZED_KEY" ]]; then
    docker exec -u root a14-kali bash -c "
        mkdir -p /home/kali/.ssh &&
        echo '$KALI_AUTHORIZED_KEY' > /home/kali/.ssh/authorized_keys &&
        chown -R kali:kali /home/kali/.ssh &&
        chmod 700 /home/kali/.ssh &&
        chmod 600 /home/kali/.ssh/authorized_keys
    "
    echo "=== kali authorized_keys injected ==="
fi

echo "=== polaris bootstrap complete $(date -u +%FT%TZ) ==="
