#!/bin/bash
# Kali pentesting tools and sshpass
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing Kali metapackage (this takes a while) ==="
apt-get install -y kali-linux-headless

echo "=== Installing sshpass for non-interactive SSH ==="
apt-get install -y sshpass

echo "=== Installing additional dev tools ==="
apt-get install -y \
  python3 \
  python3-pip \
  python3-venv \
  nodejs \
  npm \
  build-essential \
  git \
  curl \
  wget

echo "=== Tools setup complete ==="
