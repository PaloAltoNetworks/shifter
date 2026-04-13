#!/bin/bash
# Base package refresh for the Ubuntu range image.
#
# Cloud-neutral: runs unchanged on the AWS amazon-ebs build, the GCP
# googlecompute build, and the Docker buildx pod build. SSM agent install
# is extracted to ubuntu/aws-ssm.sh and wired into only the amazon-ebs
# source. The snap package manager isn't available in the ubuntu:24.04 pod
# base either, which is the other reason the snap install moved out.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Updating package lists ==="
apt-get update

echo "=== Upgrading system packages ==="
apt-get upgrade -y

# CVE-2024-24790 snapd patch. snapd is present on AWS Canonical AMI and on
# the ubuntu-2204-lts GCE image but not in the ubuntu:24.04 pod base, so
# gate on `snap` being available instead of branching on cloud.
if command -v snap >/dev/null 2>&1; then
    echo "=== Updating snapd to patch CVE-2024-24790 ==="
    apt-get install -y --only-upgrade snapd
    snap refresh
fi

echo "=== Base setup complete ==="
