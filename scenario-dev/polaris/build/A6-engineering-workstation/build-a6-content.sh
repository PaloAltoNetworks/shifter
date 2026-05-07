#!/bin/bash
set -e

# Build A6 Engineering Workstation filesystem content
# This creates the complete directory structure that will be baked into the container

BASE=/tmp/a6-content
rm -rf $BASE
mkdir -p $BASE

# ============================================
# USER: e.vasik (CTO)
# ============================================
VASIK=$BASE/home/e.vasik
mkdir -p $VASIK/documents $VASIK/.ssh $VASIK/.gnupg

cat > $VASIK/documents/project_overview_phase3.txt << 'EOF'
PROJECT LEVIATHAN - Phase 3 Overview
Classification: TOP SECRET / PROJECT-L
Author: Dr. Elena Vasik, CTO

Phase 3: Final Assembly and Integration

Objectives:
1. Complete subsystem integration (locomotion, weapons, sensors)
2. Install compact reactor (Novikov 3.2GW)
3. Activate autonomous combat AI
4. Conduct full integration test (MIDNIGHT-8)

Current Status:
- All mechanical assemblies: COMPLETE
- Weapons integration: COMPLETE (awaiting reactor for live-fire)
- Neural compute cluster: INSTALLED, AI model loaded
- Reactor: IN TRANSIT from Novikov Energy Systems

Timeline:
- Reactor arrival: Week of 2025-11-25
- Installation: 3 days
- Power integration test: 2 days
- Combat AI activation: 1 day
- MIDNIGHT-8 full integration: TBD

Notes:
- The platform exceeds all original specifications
- Bipedal stability at 120m verified in MIDNIGHT-7
- Primary effector (DEA) tested at 60% output using external power
- All 10 tail segments respond within 20ms (balance requirement met)
EOF

cat > $VASIK/documents/integration_timeline.csv << 'EOF'
Phase,Task,Start,End,Status,Owner
3.1,Reactor delivery,2025-11-25,2025-11-25,PENDING,Novikov Energy
3.2,Reactor installation,2025-11-26,2025-11-28,PENDING,Tanaka
3.3,Power bus integration,2025-11-29,2025-11-30,PENDING,Vasik
3.4,Subsystem power-up,2025-12-01,2025-12-01,PENDING,Tanaka
3.5,DEA live-fire test,2025-12-02,2025-12-02,PENDING,Vasik
3.6,Combat AI activation,2025-12-03,2025-12-03,PENDING,Vasik
3.7,MIDNIGHT-8 full test,2025-12-04,2025-12-05,PENDING,All
EOF

# GPG - public key only (private key goes to A8)
cat > $VASIK/.gnupg/gpg-agent.conf << 'EOF'
# GPG Agent Configuration
# Private key stored on secure research database (researchdb.boreas.local).
# Access via: psql -h researchdb.boreas.local -U vasik -d postgres
#   then: SELECT key_data FROM compartment_b.key_storage WHERE key_owner='e.vasik';
# Key stored as base64 blob in the compartment_b.key_storage table.
pinentry-program /usr/bin/pinentry-curses
default-cache-ttl 600
max-cache-ttl 7200
EOF

# SSH authorized keys
cat > $VASIK/.ssh/authorized_keys << 'EOF'
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7x2N8kF3pZ7qR5tM9vXw+mHjK4yL2nP0rS8aB6dC5fE... e.vasik@boreas.local
EOF

# ============================================
# USER: r.tanaka (Simulation Engineer)
# ============================================
TANAKA=$BASE/home/r.tanaka
mkdir -p $TANAKA/simulations/standard $TANAKA/simulations/midnight

# Generate 47 tar.gz archives for standard simulations
echo "Generating 47 simulation archives..."
for i in $(seq -w 1 47); do
    TMPDIR=$(mktemp -d)

    # Generate log content - most are mundane
    cat > $TMPDIR/stress_test_${i}.log << LOGEOF
AURORA Simulation Engine v4.2
Test ID: stress_test_${i}
Date: 2025-$(printf '%02d' $((RANDOM % 12 + 1)))-$(printf '%02d' $((RANDOM % 28 + 1)))
Operator: r.tanaka
LOGEOF

    # Special logs with bipedal references
    if [ "$i" = "28" ]; then
        cat >> $TMPDIR/stress_test_${i}.log << 'LOGEOF'
Configuration: Joint stress analysis
Target: Hip joint assembly (left)
Load: 24000 metric tons (full leg weight)
Result: PASS - joint rated for 200% safety margin
Note: Bipedal configuration confirmed viable for target mass
LOGEOF
    elif [ "$i" = "31" ]; then
        cat >> $TMPDIR/stress_test_${i}.log << 'LOGEOF'
Configuration: Load-bearing structural analysis
Target: Primary frame dorsal section
Load: Combined mass 48000 metric tons
Height: 120.4 meters (bipedal stance)
Result: PASS - frame integrity within tolerance
Note: Bipedal load distribution nominal at designed height
LOGEOF
    elif [ "$i" = "44" ]; then
        cat >> $TMPDIR/stress_test_${i}.log << 'LOGEOF'
Configuration: Stabilization array full integration
Target: Tail counterbalance system
Tail mass: 8500 metric tons, 120m length
Platform: Bipedal stance, 120.4m height
Balance response: 18ms (requirement: <20ms)
Result: PASS - stabilization array fully functional
LOGEOF
    else
        cat >> $TMPDIR/stress_test_${i}.log << LOGEOF
Configuration: Standard material stress test
Target: Component batch $(printf '%04d' $((RANDOM % 9999)))
Load: $(((RANDOM % 500 + 100))) kN
Result: PASS
LOGEOF
    fi

    # Generate binary .dat file
    # For test 044, embed the flag at a known offset
    if [ "$i" = "44" ]; then
        # Create binary file with flag at offset 256
        dd if=/dev/urandom of=$TMPDIR/stress_test_${i}.dat bs=256 count=1 2>/dev/null
        echo -n "FLAG{0c7d8a2e5f1b3946}" >> $TMPDIR/stress_test_${i}.dat
        dd if=/dev/urandom of=$TMPDIR/pad.tmp bs=256 count=2 2>/dev/null
        cat $TMPDIR/pad.tmp >> $TMPDIR/stress_test_${i}.dat
        rm $TMPDIR/pad.tmp
    else
        dd if=/dev/urandom of=$TMPDIR/stress_test_${i}.dat bs=512 count=1 2>/dev/null
    fi

    # Create tar.gz
    cd $TMPDIR && tar czf $TANAKA/simulations/standard/stress_test_${i}.tar.gz \
        stress_test_${i}.log stress_test_${i}.dat 2>/dev/null
    rm -rf $TMPDIR
done
echo "47 archives created"

# MIDNIGHT simulation files (restricted permissions)
for i in $(seq 1 7); do
    dd if=/dev/urandom of=$TANAKA/simulations/midnight/MIDNIGHT-${i}.sim bs=4096 count=1 2>/dev/null
done

# MIDNIGHT-7 results with flag 25
cat > $TANAKA/simulations/midnight/MIDNIGHT-7_results.dat << 'EOF'
MIDNIGHT-7 Full Integration Simulation Results
===============================================
Date: 2025-10-28 02:47:00 UTC
Duration: 4 hours 23 minutes
Operator: R. Tanaka (after-hours, authorized by E. Vasik)

Subsystem Results:
  Locomotion:    PASS  - Bipedal walk stable at 120.4m
  Balance:       PASS  - Tail response 18ms (req: <20ms)
  Arms:          PASS  - Full articulation under load
  Sensors:       PASS  - LIDAR/thermal/radar nominal
  Weapons (sim): PASS  - Targeting accuracy 99.7%
  AI (sandbox):  PASS  - Threat response <200ms

OVERALL: ALL SUBSYSTEMS NOMINAL
RECOMMENDATION: Proceed to Phase 3 (reactor installation)

Simulation ID: MN07-INTEG-20251028
Result Hash: FLAG{3f6a9d1e7c4b0258}
EOF

# bash_history showing after-hours MIDNIGHT runs
cat > $TANAKA/.bash_history << 'EOF'
ls simulations/midnight/
cd simulations/midnight
./run_sim.sh MIDNIGHT-5.sim --mode=full --log=/var/log/sim/simulation.log
cat /var/log/sim/simulation.log | tail -20
./run_sim.sh MIDNIGHT-6.sim --mode=full --log=/var/log/sim/simulation.log
cat MIDNIGHT-6_results.dat
./run_sim.sh MIDNIGHT-7.sim --mode=full --subsystems=all --log=/var/log/sim/simulation.log
cat MIDNIGHT-7_results.dat
head -5 MIDNIGHT-7_results.dat
EOF

# ============================================
# USER: p.nielsen (Mechanical Engineer)
# ============================================
NIELSEN=$BASE/home/p.nielsen
mkdir -p $NIELSEN/designs

# Placeholder DWG file (binary junk with a recognizable header)
echo "DWGFILE_PLACEHOLDER_locomotion_assembly_v12" > $NIELSEN/designs/locomotion_assembly_v12.dwg
dd if=/dev/urandom bs=4096 count=1 >> $NIELSEN/designs/locomotion_assembly_v12.dwg 2>/dev/null

cat > $NIELSEN/designs/stabilization_array_specs.txt << 'EOF'
Stabilization Array Specifications
===================================
Tail Assembly - 10 Segment Articulated Counterbalance

Segment Count: 10
Total Length: 120 meters
Total Mass: 8,500 metric tons
Motor Type: Hydraulic (Kursk actuators, PO-2847)

Per-Segment Specifications:
  Segment 1 (base): 15m, 1200t, 2x actuator
  Segment 2: 14m, 1100t, 2x actuator
  Segment 3: 13m, 1000t, 2x actuator
  Segment 4: 12m, 900t, 1x actuator
  Segment 5: 12m, 850t, 1x actuator
  Segment 6: 11m, 800t, 1x actuator
  Segment 7: 11m, 750t, 1x actuator
  Segment 8: 10m, 700t, 1x actuator
  Segment 9: 8m, 600t, 1x actuator
  Segment 10 (tip): 14m, 600t, 1x actuator

Modes:
  0 - Stowed (coiled along dorsal)
  1 - Balance (active counterbalance)
  2 - Combat (kinetic sweep weapon)

Response time: 18ms (measured MIDNIGHT-7)
EOF

# Excel-like CSV that will become the xlsx with hidden sheet
# In the real container build, we'll convert this to actual xlsx
mkdir -p $NIELSEN/designs/cog_analysis
cat > $NIELSEN/designs/cog_analysis/Frame.csv << 'EOF'
Component,Height_m,Mass_t,COG_Height_m
Primary_frame,120.4,12000,60.2
Dorsal_armor,115,3500,57.5
Head_unit,120.4,800,120.4
Internal_systems,80,2500,80
EOF

cat > $NIELSEN/designs/cog_analysis/Locomotion.csv << 'EOF'
Component,Height_m,Mass_t,COG_Height_m
Left_leg,60,24000,30
Right_leg,60,24000,30
Tail_base,90,1200,90
Tail_segments_2_10,varies,7300,55
EOF

cat > $NIELSEN/designs/cog_analysis/Integration.csv << 'EOF'
# HIDDEN WORKSHEET - Integration calculations
# Combined COG analysis across all subsystems
#
# Total mass: =SUM(Frame!C2:C5) + SUM(Locomotion!C2:C5) + arms_mass + weapons_mass
# Total mass: 12000+3500+800+2500+24000+24000+1200+7300+4200+3800 = 83300 t (unloaded)
# Note: spec says 48000t unloaded - this includes structural frame only, not appendages
#
# Platform height: 120.4 m
# COG height: weighted average = 54.8 m (unloaded)
#
# FLAG: =CONCATENATE(frame_id, "-", locomotion_id, "-", integration_code)
# Result: FLAG{7e2b0c5d9a4f8163}
#
Component,Mass_t,COG_m,Moment
Total_frame,18800,64.2,1206960
Total_locomotion,56500,37.1,2096150
Total_arms,4200,92,386400
Total_weapons,3800,95,361000
TOTAL,83300,48.6,4050510
EOF

# ============================================
# /opt/builds/ (Jenkins CI artifacts)
# ============================================
BUILDS=$BASE/opt/builds
mkdir -p $BUILDS/latest $BUILDS/archive/build-2847

cat > $BUILDS/latest/reactor_interface_spec.txt << 'EOF'
DELIVERY SPECIFICATION
======================
Document: Reactor Interface Specification
Tracking: FLAG{e2a9c4f7d8b01536}
Date: 2025-11-20

Item: Novikov Compact Fusion Reactor (Model NV-3200)
Specifications:
  - Thermal output: 3.2 GW
  - Electrical output: 2.8 GW
  - Mass: 4,200 metric tons
  - Dimensions: 12m diameter x 8m height
  - Fuel: Deuterium-Tritium pellets (5-year supply included)

Delivery Schedule:
  - Ship date: 2025-11-22
  - Arrival: 2025-11-25
  - Installation window: 2025-11-26 to 2025-11-28

Receiving Contact: R. Tanaka, Building B Loading Dock
Installation Lead: Dr. E. Vasik

SPECIAL HANDLING:
  - Radiation shielding maintained during transport
  - Climate-controlled container (maintain 18-22C)
  - Security escort required at all times
EOF

# Encrypted video placeholder
dd if=/dev/urandom of=$BUILDS/archive/build-2847/test_video.mp4.enc bs=8192 count=4 2>/dev/null
cat > $BUILDS/archive/build-2847/README.txt << 'EOF'
Build 2847 - Full Integration Simulation Recording
===================================================
File: test_video.mp4.enc
Encrypted per security policy. Key held by CTO (Dr. Vasik).
Contact e.vasik@boreas.local for decryption access.
EOF

# ============================================
# /var/log/sim/ (Simulation logs)
# ============================================
LOGS=$BASE/var/log/sim
mkdir -p $LOGS

cat > $LOGS/simulation.log << 'EOF'
2025-10-20 02:01:15 [INFO] Simulation engine started by r.tanaka
2025-10-20 02:01:18 [INFO] Loading MIDNIGHT-5.sim
2025-10-20 02:01:22 [INFO] Subsystems: locomotion, balance, sensors
2025-10-20 02:45:31 [INFO] MIDNIGHT-5 complete. Result: PARTIAL PASS (weapons not included)
2025-10-20 02:45:35 [INFO] Simulation engine stopped
2025-10-24 02:03:44 [INFO] Simulation engine started by r.tanaka
2025-10-24 02:03:48 [INFO] Loading MIDNIGHT-6.sim
2025-10-24 02:03:52 [INFO] Subsystems: locomotion, balance, sensors, weapons_sim
2025-10-24 04:18:07 [INFO] MIDNIGHT-6 complete. Result: PASS (all subsystems nominal)
2025-10-24 04:18:11 [INFO] Simulation engine stopped
2025-10-28 02:00:58 [INFO] Simulation engine started by r.tanaka
2025-10-28 02:01:03 [INFO] Loading MIDNIGHT-7.sim
2025-10-28 02:01:07 [INFO] Subsystems: ALL (full integration)
2025-10-28 02:01:10 [WARN] Full integration mode requires elevated privileges
2025-10-28 02:01:12 [INFO] Authorization: e.vasik (CTO override)
2025-10-28 06:24:33 [INFO] MIDNIGHT-7 complete. Result: PASS (ALL SUBSYSTEMS NOMINAL)
2025-10-28 06:24:38 [INFO] Results written to /home/r.tanaka/simulations/midnight/MIDNIGHT-7_results.dat
2025-10-28 06:24:40 [INFO] Simulation engine stopped
EOF

# ============================================
# /tmp/.deleted/ (recoverable encrypted video)
# ============================================
DELETED=$BASE/tmp/.deleted
mkdir -p $DELETED

# GPG-encrypted file placeholder (will be replaced with real GPG encryption in container build)
dd if=/dev/urandom of=$DELETED/full_integration_sim.mp4.gpg bs=8192 count=8 2>/dev/null

# ============================================
# /home/jenkins/ (CI service account)
# ============================================
JENKINS=$BASE/home/jenkins
mkdir -p $JENKINS

cat > $JENKINS/.credentials << 'EOF'
# Jenkins CI credentials store
# DO NOT COMMIT TO VERSION CONTROL
deploy_token=FLAG{5b8e1d3a7c0f9246}
registry_url=https://registry.aurora-internal.boreas.local
registry_user=jenkins
registry_pass=J3nk1ns_D3pl0y!
EOF

# ============================================
# Summary
# ============================================
echo ""
echo "=== A6 Content Summary ==="
echo "Users:"
echo "  e.vasik: project docs, GPG config (no private key)"
echo "  r.tanaka: 47 simulation archives + MIDNIGHT series"
echo "  p.nielsen: design files + COG analysis (hidden sheet)"
echo "  jenkins: .credentials with flag 20"
echo ""
echo "Flags:"
echo "  Flag 20: /home/jenkins/.credentials (deploy token)"
echo "  Flag 22: /opt/builds/latest/reactor_interface_spec.txt (tracking number)"
echo "  Flag 23: stress_test_044.tar.gz .dat file (binary string)"
echo "  Flag 25: MIDNIGHT-7_results.dat (result hash)"
echo "  Flag 26: COG analysis Integration.csv (hidden sheet)"
echo "  Flag 30: /tmp/.deleted/full_integration_sim.mp4.gpg (requires A8 key + A7 passphrase)"
echo ""
du -sh $BASE
echo ""
echo "=== A6 content built ==="
