#!/bin/bash
set -euo pipefail

# LibreChat EC2 User Data - Host Prep Only
# Application config and containers handled by deploy workflow

exec > >(tee /var/log/user-data.log | logger -t user-data -s 2>/dev/console) 2>&1

echo "Starting LibreChat host setup..."

# ------------------------------------------------------------------------------
# Install Docker and Docker Compose
# ------------------------------------------------------------------------------

dnf install -y docker jq
systemctl enable docker
systemctl start docker

# Install Docker Compose plugin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Add ec2-user to docker group
usermod -aG docker ec2-user

# ------------------------------------------------------------------------------
# Mount Data Volume
# ------------------------------------------------------------------------------

DATA_DEVICE="${data_volume_device}"
DATA_MOUNT="/opt/librechat/data"

# Wait for device to be attached
while [ ! -e "$DATA_DEVICE" ]; do
  echo "Waiting for data volume to attach..."
  sleep 5
done

# Format if not already formatted
if ! blkid "$DATA_DEVICE"; then
  echo "Formatting data volume..."
  mkfs.xfs "$DATA_DEVICE"
fi

# Mount the volume
mkdir -p "$DATA_MOUNT"
if ! grep -q "$DATA_MOUNT" /etc/fstab; then
  echo "$DATA_DEVICE $DATA_MOUNT xfs defaults,nofail 0 2" >> /etc/fstab
fi
mount -a

# ------------------------------------------------------------------------------
# Create Application Directory Structure
# ------------------------------------------------------------------------------

mkdir -p /opt/librechat/{images,logs}
mkdir -p /opt/librechat/data/mongodb

# LibreChat runs as UID 1000, MongoDB runs as UID 999
chown -R 1000:1000 /opt/librechat
chown -R 999:999 /opt/librechat/data/mongodb

echo "LibreChat host ready. Waiting for deploy workflow."
