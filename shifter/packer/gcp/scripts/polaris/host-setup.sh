#!/bin/bash
# Polaris range-host (polaris-vm) GCE image setup.
#
# The Polaris participant endpoint is a Kali container running inside this
# Ubuntu/Debian Docker host. The host runs the polaris docker-compose stack
# (17 containers incl. a14-kali, dns, a9-splice). This script prepares the
# host image:
#
#   1. Install Docker Engine + compose plugin, the Google Cloud SDK (for the
#      GCS smoketest-tarball fetch and to make the range host's Vertex/GCS
#      access self-contained), and git.
#   2. Move the host sshd to the management port so the participant Kali
#      container can bind host :22 / :3389. The provisioner drives host guest
#      setup on this management port (see gcp_range_cell_plan._host_access).
#      The change is written as an sshd drop-in captured into the image and
#      applied on the range VM's first boot; the packer builder's live sshd
#      stays on :22 so the build connection is not dropped mid-provision.
#   3. Build/pull the compose stack when its source is staged at
#      /opt/polaris/scenario-dev/polaris/build. The full stack (docker-compose
#      .yml + container build context) is supplied at bake time the same way
#      the AWS polaris-vm AMI is baked; when it is absent this script warns and
#      leaves the host image otherwise range-ready.
set -euo pipefail

HOST_MGMT_SSH_PORT="${HOST_MGMT_SSH_PORT:-2222}"
POLARIS_STACK_BUCKET="${POLARIS_STACK_BUCKET:-}"
POLARIS_STACK_KEY="${POLARIS_STACK_KEY:-polaris/stack/polaris-stack.tar.gz}"
POLARIS_ROOT="/opt/polaris/scenario-dev/polaris"
COMPOSE_DIR="${POLARIS_ROOT}/build"

export DEBIAN_FRONTEND=noninteractive
apt-get update

# --- Docker Engine + compose plugin -----------------------------------------
apt-get install -y ca-certificates curl gnupg git
install -m 0755 -d /etc/apt/keyrings
curl --proto '=https' --tlsv1.2 -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker

# --- Google Cloud SDK (gcloud storage for the GCS tarball fetch) -------------
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  > /etc/apt/sources.list.d/google-cloud-sdk.list
curl --proto '=https' --tlsv1.2 -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
apt-get update
apt-get install -y google-cloud-cli

# --- Management sshd port (drop-in, applied on the range VM's first boot) -----
# The participant Kali container publishes host :22 / :3389, so the host sshd
# must not occupy :22 on the running range VM. Written as a drop-in so the
# builder's live sshd (still on :22) keeps packer's connection alive.
install -d -m 0755 /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/10-shifter-mgmt-port.conf <<EOF
# Managed by shifter polaris-vm image bake. The participant Kali container
# binds host :22; the provisioner reaches the host sshd on this port.
Port ${HOST_MGMT_SSH_PORT}
EOF

# --- Compose stack ------------------------------------------------------------
# The compose stack is not in the repo (scenario-dev/polaris/build is
# gitignored). Fetch it from GCS at bake time when configured; the builder VM's
# service account authenticates via ADC.
if [[ -n "${POLARIS_STACK_BUCKET}" ]]; then
  echo "polaris host-setup: fetching compose stack from gs://${POLARIS_STACK_BUCKET}/${POLARIS_STACK_KEY}"
  mkdir -p "${POLARIS_ROOT}"
  STACK_TARBALL="$(mktemp)"
  gcloud storage cp "gs://${POLARIS_STACK_BUCKET}/${POLARIS_STACK_KEY}" "${STACK_TARBALL}"
  rm -rf "${COMPOSE_DIR}"
  mkdir -p "${COMPOSE_DIR}"
  tar xzf "${STACK_TARBALL}" -C "${COMPOSE_DIR}"
  rm -f "${STACK_TARBALL}"
fi

if [[ -f "${COMPOSE_DIR}/docker-compose.yml" ]]; then
  echo "polaris host-setup: building/pulling compose stack in ${COMPOSE_DIR}"
  cd "${COMPOSE_DIR}"
  docker compose build
  docker compose pull --ignore-buildable || true
else
  echo "polaris host-setup: WARNING no docker-compose.yml at ${COMPOSE_DIR}; set" >&2
  echo "  POLARIS_STACK_BUCKET so the bake can fetch the compose stack from GCS." >&2
fi

echo "polaris host-setup: complete (mgmt sshd port ${HOST_MGMT_SSH_PORT})"
