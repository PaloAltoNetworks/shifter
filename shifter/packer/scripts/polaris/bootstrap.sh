#!/bin/bash
# POLARIS bake — build and run the 17-container polaris stack, then let Packer
# image the running builder. Faithful port of the retired
# scripts/polaris-aws-range/user_data.sh.tpl (which the deleted
# polaris-scenario-bake.yml ran via a Terraform bake range); Packer now owns the
# instance lifecycle. Runs as root via Packer sudo.
#
# The stack is baked RUNNING with range-0 override values: a placeholder DC IP
# and a throwaway bake-time kali key. Both are overwritten at range launch by
# PolarisRangeBootstrapPlan, which regenerates docker-compose.override.yml with
# the real per-range DC IP + per-instance key and force-recreates only the dns +
# a14-kali + a9-splice containers. The other 14 containers keep running from this
# baked state, so the stack MUST be baked up.
#
# No private scenario content lives in this repo: the build tarball is supplied
# out of band via POLARIS_TARBALL_S3_URI and read with the builder's instance
# profile.
set -euo pipefail
exec > >(tee /var/log/polaris-bootstrap.log) 2>&1

echo "=== polaris bake bootstrap starting $(date -u +%FT%TZ) ==="

: "${POLARIS_TARBALL_S3_URI:?POLARIS_TARBALL_S3_URI must be set (s3://bucket/key of the operator-supplied build tarball)}"

# Placeholder DC IP + throwaway kali key baked into the range-0 stack. Both are
# regenerated per range at launch (see PolarisRangeBootstrapPlan); they are not
# secrets and grant access to nothing real (the range's own key replaces the
# bake key before any participant reaches the box).
BAKE_DC01_IP="10.100.0.11"

export DEBIAN_FRONTEND=noninteractive

# Pin curl to HTTPS on the initial request and on any redirect without repeating
# the literal.
https_proto='=https'

# Give apt a moment to finish any on-boot unattended-upgrades work before we try
# to hold the dpkg lock.
for _ in 1 2 3 4 5; do
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

# Ubuntu 24.04 no longer reliably exposes awscli v1 as an apt package. Install
# AWS CLI v2 from Amazon's zip so the S3 fetch works on current public Ubuntu.
rm -rf /tmp/awscliv2 /tmp/awscliv2.zip
curl -fsSL --proto "$https_proto" --proto-redir "$https_proto" "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp/awscliv2
/tmp/awscliv2/aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update

systemctl enable --now docker

# docker-compose-plugin is not in Ubuntu apt. Install the v2 binary from docker's
# github release directly so `docker compose` works.
mkdir -p /usr/libexec/docker/cli-plugins
curl -fsSL --proto "$https_proto" --proto-redir "$https_proto" \
    https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
    -o /usr/libexec/docker/cli-plugins/docker-compose
chmod +x /usr/libexec/docker/cli-plugins/docker-compose

# The base Ubuntu host ships several services (ssh on 22, xrdp on 3389, etc.)
# that compete with the polaris containers for host ports — particularly Kali's
# sshd (22) and xrdp (3389) that we publish to the host for the portal Terminal
# UI + Guacamole RDP. Disable + mask them before compose up so first boot is
# clean. Operator access to the VM is via SSM Session Manager, not host ssh.
for svc in ssh ssh.socket sshd sshd.socket xrdp xrdp-sesman apache2 smbd nmbd mysql vsftpd; do
    systemctl disable --now "$svc" 2>/dev/null || true
    systemctl mask "$svc" 2>/dev/null || true
done

# The builder profile credentials are available immediately over the SSM path,
# but probe with STS before the first S3 call to avoid a first-boot race.
for attempt in $(seq 1 30); do
  if aws sts get-caller-identity >/dev/null 2>&1; then
    echo "instance-profile credentials available (attempt $attempt)"
    break
  fi
  echo "waiting for instance-profile credentials... (attempt $attempt/30)"
  sleep 4
done

# Pull the private polaris build tarball via the instance profile.
mkdir -p /opt/polaris
cd /opt/polaris
aws s3 cp "${POLARIS_TARBALL_S3_URI}" polaris-build.tar.gz
tar xzf polaris-build.tar.gz

# Work from the build root (where docker-compose.yml lives).
cd /opt/polaris/scenario-dev/polaris/build

# Stage the bake-time splice-relay keypair. Regenerated per range at launch.
SPLICE_KEY_DIR=/opt/polaris/.splice
install -d -m 700 "$SPLICE_KEY_DIR"
if [[ ! -f "$SPLICE_KEY_DIR/splice_relay" ]]; then
    ssh-keygen -t ed25519 -N "" \
        -C "splice-relay@bake-$(date -u +%Y%m%dT%H%M%SZ)" \
        -f "$SPLICE_KEY_DIR/splice_relay" -q
fi
SPLICE_PRIVATE_KEY_B64="$(base64 -w0 < "$SPLICE_KEY_DIR/splice_relay")"
SPLICE_PUBLIC_KEY="$(cat "$SPLICE_KEY_DIR/splice_relay.pub")"

# Throwaway bake-time kali key. The a14 entrypoint injects KALI_AUTHORIZED_KEY on
# every container start; range launch replaces it with the per-instance key.
BAKE_KEY_DIR=/opt/polaris/.bakekey
install -d -m 700 "$BAKE_KEY_DIR"
if [[ ! -f "$BAKE_KEY_DIR/kali" ]]; then
    ssh-keygen -t ed25519 -N "" -C "polaris-bake" -f "$BAKE_KEY_DIR/kali" -q
fi
BAKE_KALI_PUBKEY="$(cat "$BAKE_KEY_DIR/kali.pub")"

# Range-0 override. Publish Kali's sshd (22) + xrdp (3389) on the host (matches a
# launched range), pin the a14-kali network addresses, and seed the dns zone with
# the placeholder DC IP. All values are bake-time defaults; range launch rewrites
# this file (see PolarisRangeBootstrapPlan) before any participant use.
cat > docker-compose.override.yml <<COMPOSE_EOF
services:
  a9-splice:
    environment:
      A9_AUTHORIZED_KEY: "${SPLICE_PUBLIC_KEY}"
  a14-kali:
    ports:
      - "22:22"
      - "3389:3389"
    networks:
      shared:
        ipv4_address: 172.20.0.140
      corporate:
        ipv4_address: 172.20.10.140
      splice-link:
        ipv4_address: 172.20.60.140
    environment:
      KALI_AUTHORIZED_KEY: "${BAKE_KALI_PUBKEY}"
      KALI_SPLICE_PRIVATE_KEY_B64: "${SPLICE_PRIVATE_KEY_B64}"
  dns:
    environment:
      DC01_IP: "${BAKE_DC01_IP}"
COMPOSE_EOF

# Build + start the stack (the expensive immutable step: builds the local images
# from the tarball's Dockerfiles, then brings the whole range online).
docker compose build
docker compose up -d

# Wait for A14 Kali to be reachable.
for _ in $(seq 1 60); do
  if docker compose ps a14-kali | grep -q "Up"; then
    echo "=== a14-kali up ==="
    break
  fi
  sleep 2
done

docker compose ps | tee /var/log/polaris-compose-ps.log

echo "=== polaris bake bootstrap complete $(date -u +%FT%TZ) ==="
