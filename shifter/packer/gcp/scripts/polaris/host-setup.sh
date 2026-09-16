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
#   3. The compose stack itself is fetched, verified, built, and started by the sibling
#      verify-stack.sh provisioner (which runs after this one, once Docker + the
#      Cloud SDK are installed). Every declared container exists before image
#      capture, and the step is fail-closed for a promotable polaris-vm.
set -euo pipefail

HOST_MGMT_SSH_PORT="${HOST_MGMT_SSH_PORT:-2222}"

export DEBIAN_FRONTEND=noninteractive
apt-get update

# --- Docker Engine + compose plugin -----------------------------------------
apt-get install -y ca-certificates curl gnupg git jq
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

# The compose stack fetch/verify/build/start runs in verify-stack.sh (next provisioner).
echo "polaris host-setup: docker + cloud sdk + mgmt sshd port ${HOST_MGMT_SSH_PORT} ready"
