#!/bin/bash
# AWS Systems Manager agent install for the Ubuntu victim AMI.
#
# Only the amazon-ebs source in ubuntu.pkr.hcl runs this script via a gated
# `only = ["amazon-ebs.ubuntu"]` provisioner. GCP builds (googlecompute VM
# image and Dockerfile pod image) skip it entirely because GCP ranges reach
# VM Runtime assets over VXLAN+SSH, not SSM.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing AWS Systems Manager agent (Ubuntu) ==="
snap install amazon-ssm-agent --classic
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service

echo "=== SSM agent install complete ==="
