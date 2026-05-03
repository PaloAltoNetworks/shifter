#!/bin/sh
set -eu

getent group vmail >/dev/null 2>&1 || groupadd -g 5000 vmail
id vmail >/dev/null 2>&1 || useradd -u 5000 -g vmail -s /usr/sbin/nologin -d /var/mail vmail
mkdir -p /var/mail

# Import Maildir + users from the email-box generator output.
if [ -d /generated/maildirs ]; then
    for user_dir in /generated/maildirs/*/ ; do
        [ -d "$user_dir" ] || continue
        username=$(basename "$user_dir")
        mkdir -p "/var/mail/${username}"
        cp -a "${user_dir}Maildir/." "/var/mail/${username}/" 2>/dev/null || true
        chown -R vmail:vmail "/var/mail/${username}"
    done
fi

# Rebuild dovecot users file from /generated/maildirs/users.json.
if [ -f /generated/maildirs/users.json ]; then
    python3 - <<'PY'
import json
import os
with open("/generated/maildirs/users.json") as f:
    users = json.load(f)
lines = []
for u in users:
    username = u.get("username")
    # Password comes from env substitution done at apply time, or a placeholder.
    pw = os.environ.get(f"MAIL_PW_{username.upper().replace('.', '_')}", "change-me")
    lines.append(f"{username}:{{PLAIN}}{pw}")
with open("/etc/dovecot/users", "w") as f:
    f.write("\n".join(lines) + "\n")
PY
fi

# vmailbox map for postfix virtual delivery.
if [ -f /generated/maildirs/users.json ]; then
    python3 - <<'PY'
import json
with open("/generated/maildirs/users.json") as f:
    users = json.load(f)
with open("/etc/postfix/vmailbox", "w") as f:
    for u in users:
        username = u.get("username")
        f.write(f"{username}@boreas.local {username}/Maildir/\n")
PY
    postmap /etc/postfix/vmailbox
fi

exec /usr/bin/supervisord -c /etc/supervisord.conf
