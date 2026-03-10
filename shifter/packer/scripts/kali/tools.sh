#!/bin/bash
# Kali pentesting tools and sshpass
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

# Wait for any background apt/dpkg processes to finish
echo "=== Waiting for dpkg lock ==="
while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
  echo "Waiting for dpkg lock to be released..."
  sleep 5
done

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
  wget \
  tmux

# Configure tmux for mouse scrolling (enables xterm.js scrollbar in web terminal)
cat > /etc/tmux.conf << 'EOF'
set -g mouse on
EOF

echo "=== Installing Certipy for AD Certificate Services testing ==="
pip3 install --break-system-packages certipy-ad

echo "=== Tools setup complete ==="
