#!/usr/bin/env bash
#
# Stand up a standalone CTFd workshop instance on GCE.
#
# GCE twin of platform/terraform/global/ctfd-workshop (the AWS EC2 + EIP +
# docker-compose CTFd + host nginx/certbot pattern). CTFd is an out-of-band
# workshop surface, NOT Shifter's native CTF layer, and is slated for eventual
# removal in favour of repo-native CTF tooling -- so this is a small, re-runnable
# gcloud script rather than a Terraform module or CI workflow.
#
# It reserves a static IP, opens 80/443 (+ IAP SSH), and boots a debian-12 VM
# whose startup-script installs Docker + CTFd (docker compose) behind host nginx.
# Event content is NOT baked in: after the setup wizard + admin token, seed with
# scripts/ctfd-workshop/sync_polaris_ctfd*.py passing a manifest at run time.
#
# Usage:
#   PROJECT=prod-ksqdkj DOMAIN=gcp.polaris.keplerops.com ./standup-gcp-ctfd.sh
#
# All inputs are env vars with defaults; override as needed. Safe to re-run
# (describe-or-create guards); re-running does NOT rebuild an existing VM.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT (e.g. prod-ksqdkj)}"
DOMAIN="${DOMAIN:?set DOMAIN (e.g. gcp.polaris.keplerops.com)}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
NETWORK="${NETWORK:-shifter-gcp-dev-platform}"
SUBNET="${SUBNET:-shifter-gcp-dev-packer-builder}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-4}"
DISK_SIZE="${DISK_SIZE:-50GB}"
NAME="${NAME:-shifter-ctfd-workshop}"
IP_NAME="${IP_NAME:-ctfd-workshop}"
TAG="${TAG:-ctfd-workshop}"
CTFD_REPO_URL="${CTFD_REPO_URL:-https://github.com/CTFd/CTFd.git}"
CTFD_GIT_REF="${CTFD_GIT_REF:-b5f0cf2b7f0e29f72c9227ea9bc08024230b4f06}"

gc() { gcloud --project "$PROJECT" "$@"; }

echo "== Reserve static external IP ($IP_NAME, $REGION) =="
gc compute addresses describe "$IP_NAME" --region "$REGION" >/dev/null 2>&1 ||
  gc compute addresses create "$IP_NAME" --region "$REGION"
IP="$(gc compute addresses describe "$IP_NAME" --region "$REGION" --format='value(address)')"
echo "   static IP: $IP"

echo "== Firewall: 80/443 from anywhere, 22 from IAP (tag $TAG) =="
gc compute firewall-rules describe "${TAG}-web" >/dev/null 2>&1 ||
  gc compute firewall-rules create "${TAG}-web" \
    --network "$NETWORK" --direction INGRESS --action ALLOW \
    --rules tcp:80,tcp:443 --source-ranges 0.0.0.0/0 --target-tags "$TAG"
# Priority 850 so it beats the platform VPC's priority-900 external-SSH deny
# (shifter-gcp-dev-platform-deny-external-ssh-rdp); a default 1000 allow would
# lose to that deny and IAP SSH (needed for certbot) would fail.
gc compute firewall-rules describe "${TAG}-iap-ssh" >/dev/null 2>&1 ||
  gc compute firewall-rules create "${TAG}-iap-ssh" \
    --network "$NETWORK" --direction INGRESS --action ALLOW --priority 850 \
    --rules tcp:22 --source-ranges 35.235.240.0/20 --target-tags "$TAG"

# Static startup-script: reads its config from instance metadata so this file
# needs no templating. Runs on every boot; idempotent.
STARTUP="$(cat <<'STARTUP_EOF'
#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
md() { curl -sf -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
DOMAIN="$(md ctfd-domain)"
CTFD_REPO_URL="$(md ctfd-repo-url)"
CTFD_GIT_REF="$(md ctfd-git-ref)"

if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  apt-get install -y docker.io git nginx certbot python3-certbot-nginx openssl curl
fi
systemctl enable --now docker

# Debian's docker.io ships no compose v2 / buildx plugins, so install them as
# CLI plugins directly (mirrors the AWS userdata's binary downloads). CTFd's
# compose builds the app image, so buildx is required for `docker compose up`.
install -d -m 0755 /usr/local/lib/docker/cli-plugins
if [ ! -x /usr/local/lib/docker/cli-plugins/docker-compose ]; then
  curl -fsSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod 0755 /usr/local/lib/docker/cli-plugins/docker-compose
fi
if [ ! -x /usr/local/lib/docker/cli-plugins/docker-buildx ]; then
  curl -fsSL "https://github.com/docker/buildx/releases/download/v0.21.2/buildx-v0.21.2.linux-amd64" \
    -o /usr/local/lib/docker/cli-plugins/docker-buildx
  chmod 0755 /usr/local/lib/docker/cli-plugins/docker-buildx
fi

if [ ! -d /opt/ctfd/.git ]; then
  install -d -m 0755 /opt/ctfd
  git clone "$CTFD_REPO_URL" /opt/ctfd
fi
cd /opt/ctfd
git fetch --all --tags || true
git checkout "$CTFD_GIT_REF"

if [ ! -f /opt/ctfd/docker-compose.override.yml ]; then
  secret_key="$(openssl rand -hex 32)"
  cat > /opt/ctfd/docker-compose.override.yml <<YAML
services:
  ctfd:
    environment:
      - SECRET_KEY=${secret_key}
      - WORKERS=4
      - REVERSE_PROXY=true
    restart: always
  db:
    restart: always
  cache:
    restart: always
  nginx:
    profiles:
      - container-nginx
YAML
fi

docker compose up -d

cat > /etc/nginx/sites-available/ctfd <<NGINX
server {
    listen 80;
    server_name ${DOMAIN};
    client_max_body_size 100M;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/ctfd /etc/nginx/sites-enabled/ctfd
rm -f /etc/nginx/sites-enabled/default
systemctl enable nginx
systemctl restart nginx

cat > /etc/systemd/system/ctfd.service <<'SYSTEMD'
[Unit]
Description=CTFd Platform
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/ctfd
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
[Install]
WantedBy=multi-user.target
SYSTEMD
systemctl daemon-reload
systemctl enable ctfd
echo "ctfd startup-script: done"
STARTUP_EOF
)"

echo "== Create VM ($NAME) =="
if gc compute instances describe "$NAME" --zone "$ZONE" >/dev/null 2>&1; then
  echo "   $NAME already exists; leaving it as-is (delete it to rebuild)."
else
  TMP="$(mktemp)"; printf '%s' "$STARTUP" > "$TMP"
  gc compute instances create "$NAME" \
    --zone "$ZONE" \
    --machine-type "$MACHINE_TYPE" \
    --image-family debian-12 --image-project debian-cloud \
    --boot-disk-size "$DISK_SIZE" --boot-disk-type pd-ssd \
    --network "$NETWORK" --subnet "$SUBNET" \
    --address "$IP" \
    --tags "$TAG" \
    --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
    --metadata "ctfd-domain=${DOMAIN},ctfd-repo-url=${CTFD_REPO_URL},ctfd-git-ref=${CTFD_GIT_REF}" \
    --metadata-from-file "startup-script=${TMP}"
  rm -f "$TMP"
fi

cat <<NEXT

CTFd workshop VM standing up.
  VM:        $NAME  (zone $ZONE)
  Static IP: $IP
  Domain:    $DOMAIN

Next steps:
  1. Create DNS A record: $DOMAIN -> $IP  (DNS-only for the first certbot run).
  2. After DNS resolves, obtain TLS:
       gcloud compute ssh $NAME --zone $ZONE --tunnel-through-iap --project $PROJECT
       sudo certbot --nginx -d $DOMAIN
  3. Finish the CTFd setup wizard at https://$DOMAIN/ and create an admin API token.
  4. Seed event content (event-agnostic) from your checkout, e.g.:
       python3 scripts/ctfd-workshop/sync_polaris_ctfd.py --base-url https://$DOMAIN --token <token> --manifest <manifest>
NEXT
