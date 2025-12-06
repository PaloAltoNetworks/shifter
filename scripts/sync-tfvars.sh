#!/bin/bash
set -euo pipefail

# Sync all terraform.tfvars files to GitHub secrets
# Secret naming: TF_VARS_{ENV}_{COMPONENT}
# Example: terraform/environments/prod/portal/terraform.tfvars → TF_VARS_PROD_PORTAL
#
# Usage: Run from repository root
#   ./scripts/sync-tfvars.sh

# Ensure we're at repo root
if [ ! -f "CLAUDE.md" ] || [ ! -d "terraform/environments" ]; then
  echo "Error: Must be run from repository root"
  exit 1
fi

ENVS_DIR="terraform/environments"

echo "Discovering tfvars files..."

found=0
while IFS= read -r -d '' tfvars_file; do
  # Extract path relative to environments dir
  rel_path="${tfvars_file#$ENVS_DIR/}"

  # Parse environment and component from path
  # prod/terraform.tfvars → env=prod, component=foundation
  # prod/portal/terraform.tfvars → env=prod, component=portal

  env=$(echo "$rel_path" | cut -d'/' -f1)

  # Check if there's a component subdirectory
  dir_count=$(echo "$rel_path" | tr '/' '\n' | wc -l)

  if [ "$dir_count" -eq 2 ]; then
    # prod/terraform.tfvars - root level, use "foundation"
    component="foundation"
  else
    # prod/portal/terraform.tfvars - component subdirectory
    component=$(echo "$rel_path" | cut -d'/' -f2)
  fi

  # Build secret name: TF_VARS_PROD_PORTAL
  secret_name="TF_VARS_$(echo "${env}_${component}" | tr '[:lower:]' '[:upper:]')"

  echo "  $tfvars_file → $secret_name"
  gh secret set "$secret_name" < "$tfvars_file"

  found=$((found + 1))
done < <(find "$ENVS_DIR" -name "terraform.tfvars" -print0)

if [ "$found" -eq 0 ]; then
  echo "No terraform.tfvars files found"
  exit 1
fi

echo "Done. Synced $found secret(s)."
