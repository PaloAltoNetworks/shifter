#!/bin/bash
set -euo pipefail

if [ ! -f "terraform/environments/prod/terraform.tfvars" ]; then
  echo "Error: terraform/environments/prod/terraform.tfvars not found"
  exit 1
fi

echo "Syncing tfvars to GitHub secrets..."
gh secret set TF_VARS_PROD < terraform/environments/prod/terraform.tfvars
echo "Done."
