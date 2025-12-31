#!/bin/bash
# Development tools for Ubuntu victim AMI
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing build-essential ==="
apt-get install -y build-essential

echo "=== Installing Python 3 with pip and venv ==="
apt-get install -y python3 python3-pip python3-venv

echo "=== Installing Node.js 20.x ==="
# NodeSource setup for Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

echo "=== Installing additional tools ==="
apt-get install -y \
  git \
  curl \
  nano \
  netcat-openbsd

echo "=== Tools setup complete ==="
