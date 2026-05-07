#!/bin/bash
set -e

# Create the analyst user first so the home dir exists before we populate it.
if ! id p.shah >/dev/null 2>&1; then
    useradd -m -s /bin/bash p.shah
    echo "p.shah:Welcome1" | chpasswd
fi

HOME_DIR=/home/p.shah

# .pgpass
install -o p.shah -g p.shah -m 0600 /opt/research/pgpass $HOME_DIR/.pgpass

# .ssh/ with the research-analyst keypair + config alias
mkdir -p $HOME_DIR/.ssh
install -o p.shah -g p.shah -m 0600 /opt/research/id_rsa      $HOME_DIR/.ssh/id_rsa
install -o p.shah -g p.shah -m 0644 /opt/research/id_rsa.pub  $HOME_DIR/.ssh/id_rsa.pub
install -o p.shah -g p.shah -m 0644 /opt/research/ssh_config  $HOME_DIR/.ssh/config
chown -R p.shah:p.shah $HOME_DIR/.ssh
chmod 700 $HOME_DIR/.ssh

# reports/ script + .reports/ANALYST_TOKEN (flag 38)
mkdir -p $HOME_DIR/reports $HOME_DIR/.reports
install -o p.shah -g p.shah -m 0755 /opt/research/daily_integration_report.py $HOME_DIR/reports/daily_integration_report.py
install -o p.shah -g p.shah -m 0644 /opt/research/ANALYST_TOKEN $HOME_DIR/.reports/ANALYST_TOKEN
chown -R p.shah:p.shah $HOME_DIR/reports $HOME_DIR/.reports

# sshd hardening
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then
    ssh-keygen -A >/dev/null
fi

# Launch the Research Dashboard on port 8080 in the background, then sshd
# in the foreground so container liveness follows sshd.
python3 /opt/research/dashboard.py >/var/log/dashboard.log 2>&1 &
exec /usr/sbin/sshd -D -e
