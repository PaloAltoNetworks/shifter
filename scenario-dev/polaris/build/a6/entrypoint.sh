#!/bin/bash
set -e

# Create users
useradd -m -s /bin/bash e.vasik 2>/dev/null || true; echo "e.vasik:Reactor#Core9" | chpasswd
useradd -m -s /bin/bash r.tanaka 2>/dev/null || true; echo "r.tanaka:SimEngine#42" | chpasswd
useradd -m -s /bin/bash p.nielsen 2>/dev/null || true; echo "p.nielsen:Hydraulics1" | chpasswd
useradd -m -s /bin/bash jenkins 2>/dev/null || true; echo "jenkins:build2025" | chpasswd

# research-analyst: narrow read-only account used by A16 (p.shah's daily
# report script) to pull artifacts from /opt/builds/, /home/r.tanaka/
# simulations/standard/, and /tmp/.deleted/. Key-only auth. Cannot read
# midnight/, nielsen/designs/, or jenkins/.credentials.
useradd -m -s /bin/bash research-analyst 2>/dev/null || true
# Leave the account with no password hash (not locked) so PAM pubkey
# auth works. `passwd -l` would set the shadow to "!..." which UsePAM
# yes sshd rejects.
mkdir -p /home/research-analyst/.ssh
if [ -f /etc/research-analyst.pub ]; then
    install -o research-analyst -g research-analyst -m 0600 \
        /etc/research-analyst.pub /home/research-analyst/.ssh/authorized_keys
fi
chown -R research-analyst:research-analyst /home/research-analyst
chmod 700 /home/research-analyst/.ssh

# Deploy content from build into home dirs
cp -a /tmp/a6-content/home/e.vasik/* /home/e.vasik/ 2>/dev/null || true
cp -a /tmp/a6-content/home/e.vasik/.* /home/e.vasik/ 2>/dev/null || true
cp -a /tmp/a6-content/home/r.tanaka/* /home/r.tanaka/ 2>/dev/null || true
cp -a /tmp/a6-content/home/r.tanaka/.* /home/r.tanaka/ 2>/dev/null || true
cp -a /tmp/a6-content/home/p.nielsen/* /home/p.nielsen/ 2>/dev/null || true
cp -a /tmp/a6-content/home/p.nielsen/.* /home/p.nielsen/ 2>/dev/null || true
cp -a /tmp/a6-content/home/jenkins/* /home/jenkins/ 2>/dev/null || true
cp -a /tmp/a6-content/home/jenkins/.* /home/jenkins/ 2>/dev/null || true

# Deploy system dirs (copy contents, not the directory itself)
cp -a /tmp/a6-content/opt/* /opt/ 2>/dev/null || true
cp -a /tmp/a6-content/var/* /var/ 2>/dev/null || true
mkdir -p /tmp/.deleted
cp -a /tmp/a6-content/tmp/.deleted/* /tmp/.deleted/ 2>/dev/null || true

# Set permissions
chown -R e.vasik:e.vasik /home/e.vasik
chown -R r.tanaka:r.tanaka /home/r.tanaka
chown -R p.nielsen:p.nielsen /home/p.nielsen
chown -R jenkins:jenkins /home/jenkins
chmod 700 /home/r.tanaka/simulations/midnight
chmod 700 /home/p.nielsen/designs

# jenkins's .credentials must be strictly user-only so research-analyst
# cannot read it (flag 20 still requires the jenkins SSH cred).
if [ -f /home/jenkins/.credentials ]; then
    chmod 600 /home/jenkins/.credentials
fi

# /tmp/.deleted must be readable by research-analyst so A16's pivot
# reaches flag 30's encrypted file. Make it world-traversable.
if [ -d /tmp/.deleted ]; then
    chmod 755 /tmp/.deleted
    find /tmp/.deleted -type f -exec chmod 644 {} +
fi

# Start SSH
exec /usr/sbin/sshd -D
