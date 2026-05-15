#!/bin/bash
set -e

# Create mail users
USERS="v.harlan:Boreas2025! e.vasik:Reactor#Core9 m.webb:Welcome1 j.chen:Summer2024 d.kowalski:P@ssw0rd123 s.morrison:Br3ach!ng s.ivanov:Welcome1"

> /etc/dovecot/users
for entry in $USERS; do
    user=$(echo $entry | cut -d: -f1)
    pass=$(echo $entry | cut -d: -f2)

    # Create system user
    useradd -m -s /bin/bash "$user" 2>/dev/null || true
    echo "$user:$pass" | chpasswd

    # Create Maildir
    mkdir -p "/home/$user/Maildir/cur" "/home/$user/Maildir/new" "/home/$user/Maildir/tmp"
    chown -R "$user:$user" "/home/$user/Maildir"

    # Add to Dovecot passwd file
    HASH=$(doveadm pw -s PLAIN -p "$pass")
    echo "$user:$HASH:::::::" >> /etc/dovecot/users
done

# Seed EML files into Maildirs
for userdir in /tmp/a1-content/*/; do
    user=$(basename "$userdir")
    if [ -d "/home/$user/Maildir" ]; then
        for eml in "$userdir"/*.eml; do
            [ -f "$eml" ] && cp "$eml" "/home/$user/Maildir/cur/$(date +%s).$(basename $eml):2,S"
        done
        chown -R "$user:$user" "/home/$user/Maildir"
    fi
done

# Start services
service postfix start
service dovecot start
service apache2 start

# Keep running
exec tail -f /dev/null
