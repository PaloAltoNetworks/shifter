#!/bin/sh
set -eu

# Create any scenario-declared local users. The runner writes a users file at
# /generated/users.sh that looks like:
#   adduser --disabled-password --gecos '' r.tanaka
#   echo 'r.tanaka:tanaka_password_value' | chpasswd
if [ -x /generated/users.sh ]; then
    /generated/users.sh || true
fi

# Apply any scenario-seeded content (flat copy). The generator writes paths
# with the leading slash preserved so rsync/cp -a merges into /.
if [ -d /generated/root ]; then
    cp -a /generated/root/. /
fi

# sshd config allows password auth; intentional per scenario vulns.
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config

exec /usr/sbin/sshd -D -e
