#!/bin/bash
set -e

WORKDIR=/tmp/gpg-chain
rm -rf $WORKDIR
mkdir -p $WORKDIR

# The passphrase from A7 (aurora/weapons-integration/src/crypto_config.py)
PASSPHRASE="Pr0m3th3us_Unb0und_2024"

# ============================================
# Step 1: Generate Vasik's GPG key pair
# ============================================
export GNUPGHOME=$WORKDIR/gnupg
mkdir -p $GNUPGHOME
chmod 700 $GNUPGHOME

# Generate key with the known passphrase
cat > $WORKDIR/keygen.conf << EOF
%no-protection
Key-Type: RSA
Key-Length: 2048
Subkey-Type: RSA
Subkey-Length: 2048
Name-Real: Dr. Elena Vasik
Name-Email: e.vasik@boreas.local
Name-Comment: AURORA Project Lead
Expire-Date: 0
%commit
EOF

gpg --batch --gen-key $WORKDIR/keygen.conf 2>&1
echo ""
echo "=== Key generated ==="
gpg --list-keys 2>&1

# Get the key fingerprint
KEY_FP=$(gpg --list-keys --with-colons 2>/dev/null | grep "^fpr" | head -1 | cut -d: -f10)
echo "Fingerprint: $KEY_FP"

# Now add the passphrase to the private key
# (we generated without protection, now we add it)
echo "$PASSPHRASE" | gpg --batch --yes --passphrase-fd 0 \
  --pinentry-mode loopback \
  --change-passphrase $KEY_FP 2>&1 || true

# Actually, let's regenerate WITH the passphrase from the start
rm -rf $GNUPGHOME
mkdir -p $GNUPGHOME
chmod 700 $GNUPGHOME

cat > $WORKDIR/keygen2.conf << EOF
Key-Type: RSA
Key-Length: 2048
Subkey-Type: RSA
Subkey-Length: 2048
Name-Real: Dr. Elena Vasik
Name-Email: e.vasik@boreas.local
Name-Comment: AURORA Project Lead
Expire-Date: 0
Passphrase: $PASSPHRASE
%commit
EOF

gpg --batch --gen-key $WORKDIR/keygen2.conf 2>&1
echo ""
echo "=== Key generated with passphrase ==="
gpg --list-keys 2>&1
KEY_FP=$(gpg --list-keys --with-colons 2>/dev/null | grep "^fpr" | head -1 | cut -d: -f10)
echo "Fingerprint: $KEY_FP"

# ============================================
# Step 2: Export public key (goes to A6)
# ============================================
gpg --export --armor e.vasik@boreas.local > $WORKDIR/vasik_public.asc
echo ""
echo "=== Public key exported ==="
head -3 $WORKDIR/vasik_public.asc
wc -c $WORKDIR/vasik_public.asc

# ============================================
# Step 3: Export private key (goes to A8 as base64)
# ============================================
echo "$PASSPHRASE" | gpg --batch --yes --passphrase-fd 0 \
  --pinentry-mode loopback \
  --export-secret-keys --armor e.vasik@boreas.local > $WORKDIR/vasik_private.asc
echo ""
echo "=== Private key exported ==="
head -3 $WORKDIR/vasik_private.asc
wc -c $WORKDIR/vasik_private.asc

# Base64 encode the private key for storage in A8 database
base64 $WORKDIR/vasik_private.asc > $WORKDIR/vasik_private_b64.txt
echo ""
echo "=== Private key base64 encoded ==="
wc -c $WORKDIR/vasik_private_b64.txt

# ============================================
# Step 4: Create the "simulation video" content
# ============================================
# We'll create a text file that looks like video metadata/content
# with the flag in the "final frame"
cat > $WORKDIR/simulation_content.txt << 'VIDEOF'
LEVIATHAN MKII - FULL INTEGRATION SIMULATION RECORDING
=======================================================
MIDNIGHT-7 Test Series
Recorded: 2025-10-28 02:00-06:24 UTC
Classification: TOP SECRET / PROJECT-L

Simulation Parameters:
  Mode: Full integration (all subsystems)
  Duration: 4h 24m
  Platform state: Bipedal stance, 120.4m
  Subsystems: Locomotion, Balance, Sensors, Weapons (simulated), AI (sandbox)

Frame Log:
  00:00:00 - System initialization, all controllers online
  00:05:12 - Locomotion test: walk cycle initiated
  00:12:44 - Balance test: tail counterbalance at various tilt angles
  00:28:03 - Sensor sweep: LIDAR mapping 500m radius
  00:45:17 - Arms articulation test: full range of motion
  01:02:33 - Simulated weapons test: targeting accuracy verification
  01:30:00 - Combined locomotion + balance: walking with arm movement
  02:15:44 - Terrain adaptation test: uneven ground simulation
  03:00:00 - Extended walk test: 30 minutes continuous
  03:45:22 - AI sandbox: threat detection and response
  04:20:00 - Final integration: all systems simultaneous
  04:23:55 - Test complete. All subsystems nominal.

FINAL FRAME DATA:
  Platform status: STABLE
  All systems: NOMINAL
  Simulation result: PASS
  Simulation ID: FLAG{d4c8f0a2e6b71935}

END OF RECORDING
VIDEOF

echo ""
echo "=== Simulation content created ==="

# ============================================
# Step 5: Encrypt the content with Vasik's public key
# ============================================
gpg --batch --yes --trust-model always \
  --recipient e.vasik@boreas.local \
  --output $WORKDIR/full_integration_sim.mp4.gpg \
  --encrypt $WORKDIR/simulation_content.txt 2>&1
echo ""
echo "=== Encrypted file created ==="
ls -la $WORKDIR/full_integration_sim.mp4.gpg
file $WORKDIR/full_integration_sim.mp4.gpg

# ============================================
# Step 6: Verify the decryption chain works
# ============================================
echo ""
echo "=== VERIFICATION: Full decryption chain ==="
echo "Decrypting with private key + passphrase..."
echo "$PASSPHRASE" | gpg --batch --yes --passphrase-fd 0 \
  --pinentry-mode loopback \
  --output $WORKDIR/decrypted.txt \
  --decrypt $WORKDIR/full_integration_sim.mp4.gpg 2>&1
echo ""
echo "=== Decrypted content (last 5 lines) ==="
tail -5 $WORKDIR/decrypted.txt
echo ""
echo "=== Flag 30 ==="
grep "FLAG{" $WORKDIR/decrypted.txt

# ============================================
# Step 7: Test with a FRESH gnupg home (simulates participant)
# ============================================
echo ""
echo "=== SIMULATION: Participant decryption flow ==="
PARTICIPANT_GPG=$WORKDIR/participant_gnupg
mkdir -p $PARTICIPANT_GPG
chmod 700 $PARTICIPANT_GPG

# Step 7a: Participant finds the encrypted file on A6
echo "1. Found encrypted file on A6: full_integration_sim.mp4.gpg"
cp $WORKDIR/full_integration_sim.mp4.gpg $PARTICIPANT_GPG/

# Step 7b: Participant finds public key on A6, sees it needs Vasik's key
echo "2. A6 .gnupg has public key only - need private key"

# Step 7c: Participant finds private key blob on A8 (compartment_b)
echo "3. Found private key blob on A8 (base64 encoded)"
# Decode and import
base64 -d $WORKDIR/vasik_private_b64.txt > $PARTICIPANT_GPG/imported_private.asc
GNUPGHOME=$PARTICIPANT_GPG gpg --batch --yes --import $PARTICIPANT_GPG/imported_private.asc 2>&1

# Step 7d: Participant finds passphrase in A7 source code
echo "4. Found passphrase in A7: crypto_config.py -> Pr0m3th3us_Unb0und_2024"

# Step 7e: Decrypt
echo "5. Decrypting..."
echo "$PASSPHRASE" | GNUPGHOME=$PARTICIPANT_GPG gpg --batch --yes \
  --passphrase-fd 0 --pinentry-mode loopback \
  --output $PARTICIPANT_GPG/decrypted.txt \
  --decrypt $PARTICIPANT_GPG/full_integration_sim.mp4.gpg 2>&1
echo ""
echo "=== Participant recovered flag ==="
grep "FLAG{" $PARTICIPANT_GPG/decrypted.txt

# ============================================
# Step 8: Package artifacts for distribution
# ============================================
echo ""
echo "=== Packaging artifacts ==="
mkdir -p $WORKDIR/dist/{a6,a8}

# A6 gets: public key, gpg-agent.conf hint, encrypted file
cp $WORKDIR/vasik_public.asc $WORKDIR/dist/a6/
cp $WORKDIR/full_integration_sim.mp4.gpg $WORKDIR/dist/a6/

# A8 gets: private key as base64 blob (for DB insertion)
cp $WORKDIR/vasik_private_b64.txt $WORKDIR/dist/a8/

echo "A6 artifacts:"
ls -la $WORKDIR/dist/a6/
echo ""
echo "A8 artifacts:"
ls -la $WORKDIR/dist/a8/

echo ""
echo "=== GPG CHAIN BUILD COMPLETE ==="
