#!/bin/bash
# AWS Systems Manager agent install for the Kali AMI.
#
# Only the amazon-ebs source in kali.pkr.hcl runs this script via a gated
# `only = ["amazon-ebs.kali"]` provisioner. GCP builds (googlecompute VM
# image and Dockerfile pod image) skip it entirely because GCP ranges reach
# VM Runtime assets over VXLAN+SSH, not SSM.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing AWS Systems Manager agent (Kali) ==="
cd /tmp
wget -q https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_amd64/amazon-ssm-agent.deb
dpkg -i amazon-ssm-agent.deb
systemctl enable amazon-ssm-agent

echo "=== SSM agent install complete ==="
