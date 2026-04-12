#!/bin/bash
set -e

# Create users
useradd -m -s /bin/bash e.vasik 2>/dev/null || true; echo "e.vasik:Reactor#Core9" | chpasswd
useradd -m -s /bin/bash r.tanaka 2>/dev/null || true; echo "r.tanaka:SimEngine#42" | chpasswd
useradd -m -s /bin/bash p.nielsen 2>/dev/null || true; echo "p.nielsen:Hydraulics1" | chpasswd
useradd -m -s /bin/bash jenkins 2>/dev/null || true; echo "jenkins:build2025" | chpasswd

# Deploy content from build into home dirs
cp -a /tmp/a6-content/home/e.vasik/* /home/e.vasik/ 2>/dev/null || true
cp -a /tmp/a6-content/home/e.vasik/.* /home/e.vasik/ 2>/dev/null || true
cp -a /tmp/a6-content/home/r.tanaka/* /home/r.tanaka/ 2>/dev/null || true
cp -a /tmp/a6-content/home/r.tanaka/.* /home/r.tanaka/ 2>/dev/null || true
cp -a /tmp/a6-content/home/p.nielsen/* /home/p.nielsen/ 2>/dev/null || true
cp -a /tmp/a6-content/home/p.nielsen/.* /home/p.nielsen/ 2>/dev/null || true
cp -a /tmp/a6-content/home/jenkins/* /home/jenkins/ 2>/dev/null || true
cp -a /tmp/a6-content/home/jenkins/.* /home/jenkins/ 2>/dev/null || true

# Deploy system dirs
cp -a /tmp/a6-content/opt /opt/ 2>/dev/null || true
cp -a /tmp/a6-content/var /var/ 2>/dev/null || true
mkdir -p /tmp/.deleted
cp -a /tmp/a6-content/tmp/.deleted/* /tmp/.deleted/ 2>/dev/null || true

# Set permissions
chown -R e.vasik:e.vasik /home/e.vasik
chown -R r.tanaka:r.tanaka /home/r.tanaka
chown -R p.nielsen:p.nielsen /home/p.nielsen
chown -R jenkins:jenkins /home/jenkins
chmod 700 /home/r.tanaka/simulations/midnight
chmod 700 /home/p.nielsen/designs

# Start SSH
exec /usr/sbin/sshd -D
