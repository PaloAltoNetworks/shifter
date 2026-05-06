#!/bin/bash
set -e

# Create the real user first so the home dir exists before we populate it.
if ! id s.ivanov >/dev/null 2>&1; then
    useradd -m -s /bin/bash s.ivanov
    echo "s.ivanov:Welcome1" | chpasswd
fi

# Populate ~s.ivanov with the flavor files
install -o s.ivanov -g s.ivanov -m 0644 /opt/ops/ops_runbook.txt /home/s.ivanov/ops_runbook.txt
install -o s.ivanov -g s.ivanov -m 0600 /opt/ops/bash_history    /home/s.ivanov/.bash_history
install -o s.ivanov -g s.ivanov -m 0644 /opt/ops/notes.txt       /home/s.ivanov/notes.txt

# Plant the loot under /root — root-only readable, this is the flag 37 target.
mkdir -p /root/.scada
install -o root -g root -m 0600 /opt/ops/hmi.json /root/.scada/hmi.json
chmod 700 /root/.scada

# Install the sudoers drop-in. Explicit single-command NOPASSWD rule that
# is the entire privesc surface — the script itself has the injection bug.
cat > /etc/sudoers.d/s_ivanov <<'SUDOERS'
s.ivanov ALL=(root) NOPASSWD: /opt/ops/scada_diag.sh
SUDOERS
chmod 440 /etc/sudoers.d/s_ivanov

# sshd hardening: password auth on (we want s.ivanov / Welcome1 to work),
# root login off (forces the privesc path through the sudo rule).
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Host keys (first boot)
if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then
    ssh-keygen -A >/dev/null
fi

# Launch the Ops Telemetry Flask dashboard in the background, then sshd in
# the foreground so container liveness follows sshd.
python3 /opt/ops/dashboard.py >/var/log/dashboard.log 2>&1 &
exec /usr/sbin/sshd -D -e
