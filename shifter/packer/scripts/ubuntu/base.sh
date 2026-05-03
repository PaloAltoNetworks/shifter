#!/bin/bash
# Base packages and SSM agent for Ubuntu victim AMI
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

# The official Canonical Ubuntu 22.04 AMI occasionally ships with a
# corrupted apt list cache that breaks GPG signature parsing on first
# `apt-get update` ("Splitting up InRelease into data and signature
# failed" / "The repository ... is not signed"). Clear the cache and
# refresh the keyring before doing anything else so subsequent
# operations have a clean slate.
echo "=== Resetting apt state (defensive) ==="
rm -rf /var/lib/apt/lists/*
apt-get clean
apt-get install -y --reinstall ubuntu-keyring 2>/dev/null || true

echo "=== Updating package lists ==="
apt-get -o Acquire::Retries=3 update

echo "=== Upgrading system packages ==="
apt-get upgrade -y

echo "=== Updating snapd to patch CVE-2024-24790 ==="
apt-get install -y --only-upgrade snapd
snap refresh

echo "=== Installing SSM Agent ==="
# SSM agent for AWS Systems Manager
snap install amazon-ssm-agent --classic
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service

echo "=== Base setup complete ==="
