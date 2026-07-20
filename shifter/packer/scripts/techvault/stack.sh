#!/bin/bash
# TechVault bake — phase 2: stand up the full techvault-operational stack as the
# ubuntu user (uid 1000). Faithful port of the retired
# techvault-scenario-bake.yml "stack" phase. Runs as root via Packer sudo; drops
# to ubuntu for every aptl op.
#
# Gotcha (root versus uid 1000): aptl writes the Wazuh TLS certs 0400 owned by
# the running user, and wazuh-indexer/dashboard run as uid 1000, so the lab must
# run as ubuntu (uid 1000). The default aptl.json disables several container
# groups; enable them all for the full stack.
set -euo pipefail

: "${APTL_VERSION:?APTL_VERSION must be set}"

sudo -u ubuntu env HOME=/home/ubuntu pipx install "aptl-labs==${APTL_VERSION}"
sudo -u ubuntu env HOME=/home/ubuntu bash -c '
  set -euo pipefail
  cd /home/ubuntu
  ~/.local/bin/aptl lab init techvault
  cd techvault
  jq ".containers = {wazuh:true,victim:true,kali:true,reverse:true,enterprise:true,soc:true,mail:true,fileshare:true,dns:true}" aptl.json > t && mv t aptl.json
  ~/.local/bin/aptl lab start
  if [ -f .mcp.json.example ]; then cp -n .mcp.json.example .mcp.json || true; fi
'
