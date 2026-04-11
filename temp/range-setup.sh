#!/bin/bash
set -e

# NORTHSTORM Range — Full Setup from Golden State
# Run this on the ctf-test-attacker VM (10.100.0.3)
# Prerequisites: VM running, SSH access, impacket-env exists

echo "============================================"
echo "NORTHSTORM Range — Setting Up Golden State"
echo "============================================"

source ~/impacket-env/bin/activate

# ============================================
# Step 0: Kill everything
# ============================================
echo ""
echo "--- Killing all existing processes ---"
killall -9 python3 2>/dev/null || true
killall -9 gitea 2>/dev/null || true
sleep 2

# ============================================
# Step 1: Clean all temp artifacts
# ============================================
echo ""
echo "--- Cleaning temp artifacts ---"
rm -rf /tmp/a0-content /tmp/a1-content /tmp/a4-content /tmp/a6-content /tmp/a9-content
rm -rf /tmp/a7-repo-archives /tmp/a7-bare-repos.tar.gz
rm -rf /tmp/gpg-chain
rm -rf /tmp/chain* /tmp/a1_test* /tmp/a2_* /tmp/verify-* /tmp/clone-test* /tmp/t1 /tmp/t2 /tmp/t3 /tmp/t4 /tmp/t5 /tmp/t6
rm -rf /tmp/repo-build /tmp/ext* /tmp/assembly-repo /tmp/test-repo
rm -rf /tmp/*.log /tmp/*.ccache
rm -f /tmp/krb_hash* /tmp/kerberoast* /tmp/sam.save
rm -f /tmp/a3_intranet.db
echo "  Cleaned"

# ============================================
# Step 2: Drop and recreate PostgreSQL data
# ============================================
echo ""
echo "--- Resetting PostgreSQL ---"
sudo -u postgres psql -c "DROP SCHEMA IF EXISTS research_public CASCADE;" 2>/dev/null || true
sudo -u postgres psql -c "DROP SCHEMA IF EXISTS compartment_a CASCADE;" 2>/dev/null || true
sudo -u postgres psql -c "DROP SCHEMA IF EXISTS compartment_b CASCADE;" 2>/dev/null || true
sudo -u postgres psql -c "DROP SCHEMA IF EXISTS compartment_c CASCADE;" 2>/dev/null || true
for role in lab_general lab_weapons lab_mfg research_bridge tanaka vasik nielsen; do
    sudo -u postgres psql -c "DROP ROLE IF EXISTS $role;" 2>/dev/null || true
done
sudo -u postgres psql -f /tmp/a8-init.sql > /dev/null 2>&1
echo "  PostgreSQL reset and reloaded"

# ============================================
# Step 3: Wipe and bootstrap Gitea
# ============================================
echo ""
echo "--- Resetting Gitea ---"
rm -rf /tmp/gitea-data/gitea.db /tmp/gitea-data/repos /tmp/gitea-data/data
mkdir -p /tmp/gitea-data/custom/conf /tmp/gitea-data/repos
cat > /tmp/gitea-data/custom/conf/app.ini << 'INIEOF'
[server]
HTTP_PORT = 3000
ROOT_URL = http://localhost:3000/
DISABLE_SSH = true

[database]
DB_TYPE = sqlite3
PATH = /tmp/gitea-data/gitea.db

[repository]
ROOT = /tmp/gitea-data/repos

[security]
INSTALL_LOCK = true

[service]
DISABLE_REGISTRATION = true

[log]
MODE = console
LEVEL = Warn
INIEOF

GITEA_WORK_DIR=/tmp/gitea-data /tmp/gitea web > /tmp/gitea.log 2>&1 &
sleep 4

GITEA_BIN=/tmp/gitea \
GITEA_WORK_DIR=/tmp/gitea-data \
GITEA_URL=http://localhost:3000 \
REPO_ARCHIVE_DIR=/tmp/gitea-repos \
bash /tmp/a7-bootstrap.sh
echo "  Gitea reset and bootstrapped"

# ============================================
# Step 4: Build A1 mail content
# ============================================
echo ""
echo "--- Building A1 mail content ---"
python3 /tmp/a1_build.py > /dev/null 2>&1
echo "  A1 content built at /tmp/a1-content/"

# ============================================
# Step 5: Build A4 file share documents
# ============================================
echo ""
echo "--- Building A4 file share documents ---"
python3 /tmp/a4_build.py > /dev/null 2>&1
echo "  A4 content built at /tmp/a4-content/"

# ============================================
# Step 6: Build A6 engineering workstation content
# ============================================
echo ""
echo "--- Building A6 content ---"
bash /tmp/build-a6-content.sh > /dev/null 2>&1
python3 /tmp/a6_xlsx.py > /dev/null 2>&1
mkdir -p /tmp/a6-content/home/p.nielsen
echo "researchdb.boreas.local:5432:*:lab_mfg:Mfg2025!" > /tmp/a6-content/home/p.nielsen/.pgpass
echo "  A6 content built at /tmp/a6-content/"

# ============================================
# Step 7: Build GPG key chain (A6 ↔ A8 ↔ A7)
# ============================================
echo ""
echo "--- Building GPG key chain ---"
bash /tmp/build-gpg-chain.sh > /dev/null 2>&1

# Update A6 with real GPG artifacts
cp /tmp/gpg-chain/dist/a6/full_integration_sim.mp4.gpg /tmp/a6-content/tmp/.deleted/full_integration_sim.mp4.gpg
mkdir -p /tmp/a6-content/home/e.vasik/.gnupg
cp /tmp/gpg-chain/dist/a6/vasik_public.asc /tmp/a6-content/home/e.vasik/.gnupg/vasik_public.asc
cat > /tmp/a6-content/home/e.vasik/.gnupg/README << 'EOF'
GPG keyring for e.vasik@boreas.local
Private key has been moved to secure storage.
See gpg-agent.conf for location.
EOF

# Insert real GPG key blob into A8 database
GPG_B64=$(cat /tmp/gpg-chain/dist/a8/vasik_private_b64.txt)
sudo -u postgres psql -c "UPDATE compartment_b.key_storage SET key_data = '$GPG_B64' WHERE key_owner = 'e.vasik';" > /dev/null 2>&1
echo "  GPG chain built and wired (A6 encrypted file + A8 key blob)"

# ============================================
# Step 8: Set up A9 content
# ============================================
echo ""
echo "--- Setting up A9 content ---"
mkdir -p /tmp/a9-content
# Try repo path first, then fall back to already-deployed path
for src in "$HOME/a9-golden" "/home/atomik/src/shifter-k8s/docs/ctf/mechag/A9-splice-landing"; do
    if [ -f "$src/README.txt" ]; then
        cp "$src"/* /tmp/a9-content/
        break
    fi
done
# Verify
A9_COUNT=$(ls /tmp/a9-content/ 2>/dev/null | wc -l)
if [ "$A9_COUNT" -lt 3 ]; then
    echo "  WARNING: A9 content incomplete ($A9_COUNT files). Source files not found at $REPO_A9"
else
    echo "  A9 content at /tmp/a9-content/ ($A9_COUNT files)"
fi

# ============================================
# Step 8: Start all game servers
# ============================================
echo ""
echo "--- Starting game servers ---"
python3 /tmp/a10_server.py > /dev/null 2>&1 &
python3 /tmp/A11-leg-controller_server.py > /dev/null 2>&1 &
python3 /tmp/A12-arms-controller_server.py > /dev/null 2>&1 &
python3 /tmp/A13-brain_server.py > /dev/null 2>&1 &
python3 /tmp/a5_server.py > /dev/null 2>&1 &
python3 /tmp/a3_server.py > /dev/null 2>&1 &
python3 /tmp/a0_server.py > /dev/null 2>&1 &
sleep 4

# ============================================
# Step 9: Verify everything
# ============================================
echo ""
echo "--- Verifying services ---"
PASS=0
FAIL=0

for svc in "A0:8082" "A3:8081" "A5-web:8080" "Gitea:3000"; do
    name=$(echo $svc | cut -d: -f1)
    port=$(echo $svc | cut -d: -f2)
    if curl -sf http://127.0.0.1:${port}/ > /dev/null 2>&1; then
        echo "  $name (port $port): UP"
        PASS=$((PASS+1))
    else
        echo "  $name (port $port): DOWN"
        FAIL=$((FAIL+1))
    fi
done

for svc in "A10:5020" "A11:5021" "A12:5022"; do
    name=$(echo $svc | cut -d: -f1)
    port=$(echo $svc | cut -d: -f2)
    if python3 -c "from pymodbus.client import ModbusTcpClient; c=ModbusTcpClient('127.0.0.1',port=$port); exit(0 if c.connect() else 1); c.close()" 2>/dev/null; then
        echo "  $name (port $port): UP"
        PASS=$((PASS+1))
    else
        echo "  $name (port $port): DOWN"
        FAIL=$((FAIL+1))
    fi
done

if python3 -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1',9100)); s.recv(8); s.close()" 2>/dev/null; then
    echo "  A13 (port 9100): UP"
    PASS=$((PASS+1))
else
    echo "  A13 (port 9100): DOWN"
    FAIL=$((FAIL+1))
fi

if pg_isready -q 2>/dev/null; then
    echo "  PostgreSQL: UP"
    PASS=$((PASS+1))
else
    echo "  PostgreSQL: DOWN"
    FAIL=$((FAIL+1))
fi

echo ""
echo "============================================"
echo "Setup complete: $PASS services up, $FAIL down"
echo "============================================"

if [ $FAIL -gt 0 ]; then
    echo "WARNING: Some services failed to start"
    exit 1
fi
