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

# Start xrdp for RDP participant access.
/etc/init.d/xrdp start || true

exec /usr/sbin/sshd -D -e
