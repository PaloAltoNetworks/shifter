#!/bin/sh
set -eu

# Seed home dir from scenario.
if [ -d /generated/home ]; then
    cp -a /generated/home/. /home/kali/
    chown -R kali:kali /home/kali
fi

# Scenario-supplied welcome text
if [ -f /generated/welcome.txt ]; then
    mkdir -p /home/kali/.polaris
    cp /generated/welcome.txt /home/kali/.polaris/welcome.txt
    chown -R kali:kali /home/kali/.polaris
fi

# The private key and SSH client config live in the writable container layer.
# Re-project them from the retained Compose environment on every start, after
# home seeding and before participant services, so recreation cannot strand the
# post-Lights Out bunker path.
/usr/local/libexec/polaris-splice-credential.py repair

# Start xrdp for RDP participant access.
/etc/init.d/xrdp start || true

exec /usr/sbin/sshd -D -e
