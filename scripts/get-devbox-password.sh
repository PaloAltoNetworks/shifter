#!/bin/bash
# Get the Windows dev-box admin password from Secrets Manager

set -euo pipefail

PROFILE="${PANW_SHIFTER_DEV_PROFILE:-}"

if [[ -z "$PROFILE" ]]; then
  echo "Error: PANW_SHIFTER_DEV_PROFILE environment variable not set" >&2
  exit 1
fi

aws secretsmanager get-secret-value \
  --secret-id shifter-dev-box-admin-password \
  --profile "$PROFILE" \
  --query SecretString \
  --output text
