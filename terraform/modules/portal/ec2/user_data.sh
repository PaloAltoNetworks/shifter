#!/bin/bash
set -euo pipefail

# Install Docker
dnf install -y docker
systemctl enable docker
systemctl start docker

# Add ec2-user to docker group
usermod -aG docker ec2-user

# Wait for IAM instance profile credentials to be available
echo "Waiting for IAM instance profile..."
for i in {1..30}; do
  if aws sts get-caller-identity &>/dev/null; then
    echo "IAM credentials available"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "ERROR: Timed out waiting for IAM credentials" >&2
    exit 1
  fi
  sleep 2
done

# ECR login with error handling
if ! aws ecr get-login-password --region ${aws_region} | docker login --username AWS --password-stdin ${ecr_repository_url}; then
  echo "ERROR: Failed to authenticate with ECR" >&2
  exit 1
fi

echo "EC2 user data complete. Docker ready for container deployment."
