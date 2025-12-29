#!/bin/bash
set -euo pipefail

# Install Docker and ECR credential helper
dnf install -y docker amazon-ecr-credential-helper
systemctl enable docker
systemctl start docker

# Add ec2-user to docker group
usermod -aG docker ec2-user

# Configure Docker daemon to use awslogs driver by default
mkdir -p /etc/docker
cat <<EOF > /etc/docker/daemon.json
{
  "log-driver": "awslogs",
  "log-opts": {
    "awslogs-region": "${aws_region}",
    "awslogs-group": "${log_group_name}",
    "awslogs-create-group": "false"
  }
}
EOF

# Restart Docker to apply logging config
systemctl restart docker

# Configure Docker to use ECR credential helper (auto-refreshes tokens)
# Extract registry from repository URL (e.g., 123456789.dkr.ecr.us-east-2.amazonaws.com)
ECR_REGISTRY=$(echo "${ecr_repository_url}" | cut -d'/' -f1)

mkdir -p /root/.docker /home/ec2-user/.docker
cat <<EOF > /root/.docker/config.json
{
  "credHelpers": {
    "$ECR_REGISTRY": "ecr-login"
  }
}
EOF

# Copy config for ec2-user
cp /root/.docker/config.json /home/ec2-user/.docker/config.json
chown -R ec2-user:ec2-user /home/ec2-user/.docker

echo "EC2 user data complete. Docker ready for container deployment."
