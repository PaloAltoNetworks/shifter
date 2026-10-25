#!/bin/bash
# Install MITRE Caldera adversary emulation platform
# https://github.com/mitre/caldera
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing Caldera dependencies ==="
apt-get install -y zlib1g zlib1g-dev golang

echo "=== Cloning Caldera with all submodules (includes emu plugin) ==="
git clone https://github.com/mitre/caldera.git --recursive /opt/caldera

echo "=== Installing uv to manage a Caldera-supported Python ==="
# Kali Rolling now ships Python 3.14, but Caldera's pinned requirements
# (pyyaml==6.0.1, aiohttp-apispec==3.0.0b2, ...) predate it — several have no
# cp314 wheels and are not 3.14-compatible. Run Caldera under a supported
# Python 3.12 via a uv-managed standalone interpreter, so the bake does not
# depend on whichever python3.x Kali's repos currently package.
# (Follow-up hardening: pin the uv installer + the Caldera clone to exact refs.)
export UV_INSTALL_DIR=/usr/local/bin
export UV_PYTHON_INSTALL_DIR=/opt/uv/python
curl --proto '=https' --proto-redir '=https' --tlsv1.2 -sSfL https://astral.sh/uv/install.sh | sh
export PATH="/usr/local/bin:${PATH}"
uv python install 3.12

echo "=== Creating Python 3.12 venv and installing requirements ==="
cd /opt/caldera
uv venv --python 3.12 --seed .venv
# Keep the uv-managed interpreter world-readable so a non-root range user can run
# Caldera from the baked image (the venv symlinks into UV_PYTHON_INSTALL_DIR).
chmod -R a+rX /opt/uv/python
source .venv/bin/activate
# Caldera pins exactly two sdist-only dependencies with no PyPI wheels —
# aiohttp-apispec==3.0.0b2 and svglib==1.5.1 (verified against PyPI; both
# pure-Python). Keep wheels-only for everything else and carve out just those
# two so setup scripts are not executed for the rest of the tree (SonarCloud
# shell:S8541). On Python 3.12 every other pin resolves as a wheel.
uv pip install --only-binary :all: --no-binary aiohttp-apispec,svglib -r requirements.txt

echo "=== Starting server with --build to compile VueJS UI and download content ==="
# Start server in background, let it initialize and build UI
timeout 180 python3 server.py --insecure --build || true
# Give it time to initialize
sleep 60
pkill -f "python3 server.py" || true

deactivate

echo "=== Creating convenience start script ==="
cat > /usr/local/bin/start-caldera << 'SCRIPT'
#!/bin/bash
cd /opt/caldera
source .venv/bin/activate
python3 server.py --insecure "$@"
SCRIPT
chmod +x /usr/local/bin/start-caldera

echo "=== Caldera installation complete ==="
echo "Start with: start-caldera"
echo "Access at: http://localhost:8888 (red/admin)"
