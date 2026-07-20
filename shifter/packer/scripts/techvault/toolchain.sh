#!/bin/bash
# TechVault bake — phase 1: host toolchain (runs as root via Packer sudo).
# Faithful port of the retired techvault-scenario-bake.yml "toolchain" phase.
set -euo pipefail

# Pin curl to HTTPS on the initial request and on any redirect (no clear-text
# downgrade) without repeating the literal.
https_proto='=https'

export DEBIAN_FRONTEND=noninteractive
cloud-init status --wait || true

curl -fsSL --proto "$https_proto" --proto-redir "$https_proto" https://get.docker.com | sh
systemctl enable --now docker

# The stack is baked as the ubuntu user (uid 1000, see stack.sh), and aptl's
# very first docker op (the Suricata named-volume seed) runs as ubuntu.
# get.docker.com does not add ubuntu to the docker group when installed as
# root, so grant it explicitly or the seed fails with a docker.sock
# permission denied (surfaced as BackendSeedError).
usermod -aG docker ubuntu

curl -fsSL --proto "$https_proto" --proto-redir "$https_proto" https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
# @anthropic-ai/claude-code has a required postinstall (install.cjs) that sets up
# the CLI; --ignore-scripts would break it. First-party package pulled from the
# trusted npm registry over HTTPS.
npm install -g @anthropic-ai/claude-code # NOSONAR
apt-get install -y pipx jq
