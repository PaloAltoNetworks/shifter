#!/bin/bash
# Shifter Ubuntu scenario pod entrypoint.
#
# Per-pod unique SSH host keys, mysql data dir init on first run, then
# supervisord.
set -euo pipefail

echo "[entrypoint] regenerating SSH host keys"
install -d -m 0755 /etc/ssh
ssh-keygen -A

echo "[entrypoint] ensuring /run/sshd exists"
install -d -m 0755 /run/sshd

if [ ! -d /var/lib/mysql/mysql ]; then
    echo "[entrypoint] initialising MySQL data directory"
    install -d -m 0750 -o mysql -g mysql /var/lib/mysql
    mysqld --initialize-insecure --user=mysql --datadir=/var/lib/mysql
fi

echo "[entrypoint] exec supervisord"
exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/shifter.conf
