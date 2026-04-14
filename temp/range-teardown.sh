#!/bin/bash

# NORTHSTORM Range — Full Teardown
# Kills all services and cleans all artifacts
# Run this on the ctf-test-attacker VM (10.100.0.3)

echo "============================================"
echo "NORTHSTORM Range — Tearing Down"
echo "============================================"

# Kill all game processes
echo "--- Killing processes ---"
killall -9 python3 2>/dev/null || true
killall -9 gitea 2>/dev/null || true
sleep 1

# Verify
REMAINING=$(ps aux | grep -E "python3|gitea" | grep -v grep | grep -v networkd | grep -v unattended | grep -v postgres | wc -l)
echo "  Remaining processes: $REMAINING"

# Clean all temp content
echo ""
echo "--- Cleaning content ---"
rm -rf /tmp/a0-content /tmp/a1-content /tmp/a4-content /tmp/a6-content /tmp/a9-content
rm -rf /tmp/a7-repo-archives /tmp/a7-bare-repos.tar.gz
rm -rf /tmp/gpg-chain
rm -rf /tmp/chain* /tmp/a1_test* /tmp/a2_* /tmp/verify-* /tmp/clone-test*
rm -rf /tmp/t1 /tmp/t2 /tmp/t3 /tmp/t4 /tmp/t5 /tmp/t6
rm -rf /tmp/repo-build /tmp/ext* /tmp/assembly-repo /tmp/test-repo
rm -rf /tmp/*.log /tmp/*.ccache
rm -f /tmp/krb_hash* /tmp/kerberoast* /tmp/sam.save
rm -f /tmp/a3_intranet.db
echo "  Temp content cleaned"

# Clean Gitea data (but keep binary and config template)
echo ""
echo "--- Cleaning Gitea data ---"
rm -rf /tmp/gitea-data/gitea.db /tmp/gitea-data/repos /tmp/gitea-data/data
echo "  Gitea data cleaned"

# Reset PostgreSQL schemas
echo ""
echo "--- Resetting PostgreSQL ---"
sudo -u postgres psql -c "DROP SCHEMA IF EXISTS research_public CASCADE;" 2>/dev/null || true
sudo -u postgres psql -c "DROP SCHEMA IF EXISTS compartment_a CASCADE;" 2>/dev/null || true
sudo -u postgres psql -c "DROP SCHEMA IF EXISTS compartment_b CASCADE;" 2>/dev/null || true
sudo -u postgres psql -c "DROP SCHEMA IF EXISTS compartment_c CASCADE;" 2>/dev/null || true
for role in lab_general lab_weapons lab_mfg research_bridge tanaka vasik nielsen; do
    sudo -u postgres psql -c "DROP ROLE IF EXISTS $role;" 2>/dev/null || true
done
echo "  PostgreSQL schemas and roles dropped"

echo ""
echo "============================================"
echo "Teardown complete. Range is cold."
echo "Run range-setup.sh to rebuild from golden state."
echo "============================================"
