#!/bin/bash
# Fail-closed encryption publish gate (issue #1455). Runner-side: refuse to
# publish a scenario AMI unless every EBS block-device mapping is encrypted. The
# range provisioner IAM denies RunInstances when ec2:Encrypted=false, so an
# unencrypted golden AMI would record cleanly in SSM yet make every range launch
# fail. Run this BEFORE the SSM parameter update.
#
# Env: AMI_ID
set -euo pipefail

: "${AMI_ID:?AMI_ID must be set}"

# EBS_COUNT = EBS-backed block devices on the AMI; ENCRYPTED_COUNT = those whose
# Ebs.Encrypted is true. Every EBS mapping carries a boolean Encrypted, so a
# mismatch means at least one is unencrypted.
EBS_COUNT="$(aws ec2 describe-images --image-ids "$AMI_ID" \
  --query 'length(Images[0].BlockDeviceMappings[?Ebs])' --output text)"
ENCRYPTED_COUNT="$(aws ec2 describe-images --image-ids "$AMI_ID" \
  --query 'length(Images[0].BlockDeviceMappings[?Ebs.Encrypted])' --output text)"

echo "AMI ${AMI_ID}: ${ENCRYPTED_COUNT}/${EBS_COUNT} EBS volume(s) encrypted"

if [[ "$EBS_COUNT" -eq 0 ]]; then
  echo "::error::AMI ${AMI_ID} exposes no EBS volumes to verify; refusing to publish" >&2
  exit 1
fi
if [[ "$ENCRYPTED_COUNT" -ne "$EBS_COUNT" ]]; then
  echo "::error::AMI ${AMI_ID} has $((EBS_COUNT - ENCRYPTED_COUNT)) unencrypted EBS volume(s); refusing to publish. Ensure the bake root volume launches with Encrypted=true (the range provisioner requires ec2:Encrypted=true)." >&2
  exit 1
fi

echo "AMI ${AMI_ID} verified: all ${EBS_COUNT} EBS volume(s) encrypted"
