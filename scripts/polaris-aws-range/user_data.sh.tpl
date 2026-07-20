#!/bin/bash
# POLARIS bake-range bootstrap
# Installs Docker + docker-compose, pulls the polaris build tarball from S3,
# edits docker-compose.override.yml for the range-specific A2 DC, optionally
# publishes Kali's 22 + 3389 to the EC2 host, then `docker compose up -d` so
# the whole range comes online.
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
    jq \
    unzip \
    curl \
    ca-certificates \
    openssh-client

# Ubuntu 24.04 no longer reliably exposes awscli v1 as an apt package.
# Install AWS CLI v2 from Amazon's zip so first-boot S3 fetch works on
# current public Ubuntu images as well as older shifter-ubuntu images.
rm -rf /tmp/awscliv2 /tmp/awscliv2.zip
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
    -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp/awscliv2
/tmp/awscliv2/aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update

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
for svc in ssh ssh.socket sshd sshd.socket xrdp xrdp-sesman apache2 smbd nmbd mysql vsftpd; do
    systemctl disable --now "$svc" 2>/dev/null || true
    systemctl mask "$svc" 2>/dev/null || true
done

# Wait for IMDS to return the instance-profile credentials before we
# call any aws cli command. First-boot user_data can race ahead of the
# attachment propagation and hit "Unable to locate credentials" (seen
# on polaris range 1 during the 3-range bring-up test). `aws sts
# get-caller-identity` is the canonical probe and takes ~1s once the
# role is ready.
for attempt in $(seq 1 30); do
  if aws sts get-caller-identity >/dev/null 2>&1; then
    echo "IMDS credentials available (attempt $attempt)"
    break
  fi
  echo "waiting for IMDS instance-profile credentials... (attempt $attempt/30)"
  sleep 4
done

# Pull the polaris build tarball via the instance profile.
mkdir -p /opt/polaris
cd /opt/polaris
aws s3 cp "${tarball_s3_uri}" polaris-build.tar.gz
tar xzf polaris-build.tar.gz

# Work from the build root (where docker-compose.yml lives).
cd /opt/polaris/scenario-dev/polaris/build

# Stage the per-range splice-relay keypair. The private half lands in A14
# through KALI_SPLICE_PRIVATE_KEY_B64 and the public half lands in A9's
# authorized_keys through A9_AUTHORIZED_KEY. This matches the dev/test
# prewired splice contract that A14-smoketest.sh and isolation-smoketest.sh
# validate.
SPLICE_KEY_DIR=/opt/polaris/.splice
install -d -m 700 "$SPLICE_KEY_DIR"
if [[ ! -f "$SPLICE_KEY_DIR/splice_relay" ]]; then
    ssh-keygen -t ed25519 -N "" \
        -C "splice-relay@aws-$(date -u +%Y%m%dT%H%M%SZ)" \
        -f "$SPLICE_KEY_DIR/splice_relay" -q
fi
SPLICE_PRIVATE_KEY_B64="$(base64 -w0 < "$SPLICE_KEY_DIR/splice_relay")"
SPLICE_PUBLIC_KEY="$(cat "$SPLICE_KEY_DIR/splice_relay.pub")"

# Optionally publish the Kali container's sshd (22) and xrdp (3389) on the EC2
# host so the Shifter portal (terminal UI + Guacamole RDP) can reach them.
# Standalone/default-VPC mode keeps host ports unpublished and uses SSM for
# operator access. Always pass the operator SSH pubkey as a KALI_AUTHORIZED_KEY
# env var so the a14 entrypoint can inject it into /home/kali/.ssh/authorized_keys
# on every container start, and pass the range-specific A2 DC IP into the dns
# container so its boreas.local zone resolves dc01 to the DC inside this range's
# /28 (not range 0's). We use a placeholder + python replace pass so the pubkey
# can contain any shell-meaningful characters without breaking the YAML
# (terraform already rendered ${kali_authorized_key} inline at plan time).
cat > docker-compose.override.yml <<'COMPOSE_EOF'
services:
  a9-splice:
    environment:
      A9_AUTHORIZED_KEY: "__A9_AUTHORIZED_KEY_PLACEHOLDER__"
  a14-kali:
%{ if publish_kali_host_ports }
    ports:
      - "22:22"
      - "3389:3389"
%{ endif }
    networks:
      shared:
        ipv4_address: 172.20.0.140
      corporate:
        ipv4_address: 172.20.10.140
      splice-link:
        ipv4_address: 172.20.60.140
    environment:
      KALI_AUTHORIZED_KEY: "__KALI_AUTHORIZED_KEY_PLACEHOLDER__"
      KALI_SPLICE_PRIVATE_KEY_B64: "__KALI_SPLICE_PRIVATE_KEY_B64_PLACEHOLDER__"
  dns:
    environment:
      DC01_IP: "__DC01_IP_PLACEHOLDER__"
COMPOSE_EOF

SPLICE_PUBLIC_KEY="$SPLICE_PUBLIC_KEY" SPLICE_PRIVATE_KEY_B64="$SPLICE_PRIVATE_KEY_B64" python3 - <<'PY'
import os

key = """${kali_authorized_key}"""
dc01_ip = """${a2_private_ip}"""
splice_public_key = os.environ["SPLICE_PUBLIC_KEY"]
splice_private_key_b64 = os.environ["SPLICE_PRIVATE_KEY_B64"]
with open("docker-compose.override.yml") as f:
    content = f.read()
content = content.replace("__KALI_AUTHORIZED_KEY_PLACEHOLDER__", key)
content = content.replace("__DC01_IP_PLACEHOLDER__", dc01_ip)
content = content.replace("__A9_AUTHORIZED_KEY_PLACEHOLDER__", splice_public_key)
content = content.replace("__KALI_SPLICE_PRIVATE_KEY_B64_PLACEHOLDER__", splice_private_key_b64)
with open("docker-compose.override.yml", "w") as f:
    f.write(content)
PY

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
