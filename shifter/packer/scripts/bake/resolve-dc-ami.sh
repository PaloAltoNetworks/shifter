#!/bin/bash
# Shared pre-promoted DC AMI resolver + validator (issue #1656).
#
# The Domain Controller AMI is pre-promoted, not built: both publishers read its
# id from dc-amis.json and write it to the /shifter/ami/dc runtime pointer -
# packer.yml (base build, dev/proof) and packer-promote.yml (prod). This is the
# single validator they share so the two call sites cannot drift into two
# schemas (one of which was a bare, unvalidated `jq -r '.prod'`).
#
# The registry MUST be read from trusted protected provenance (a dedicated
# checkout of the protected `dev` ref), never the caller-supplied build checkout
# or a mutable self-hosted-runner workspace: the caller passes DC_AMIS_JSON
# pointing at that trusted copy. This script enforces the checks that a
# well-formed-but-wrong id would otherwise slip past:
#   1. the environment key exists and is a single non-empty string (jq -e);
#   2. the value matches the AWS AMI id shape;
#   3. EC2 confirms the AMI is visible, `available`, and owned by the account we
#      are publishing into (a syntactically valid id can be missing, pending,
#      deregistered, or shared from the wrong account).
# Any failure exits non-zero with a bounded ::error:: message and no rejected
# value echoed, so the caller leaves the previous known-good /shifter/ami/dc
# pointer untouched.
#
# Env: DC_AMIS_JSON       path to the trusted dc-amis.json
#      DC_ENV_KEY         registry key to resolve (dev | prod)
#      EXPECTED_ACCOUNT_ID AWS account that must own the AMI (the publish target)
# Writes the validated AMI id to stdout.
set -euo pipefail

: "${DC_AMIS_JSON:?DC_AMIS_JSON must be set}"
: "${DC_ENV_KEY:?DC_ENV_KEY must be set}"
: "${EXPECTED_ACCOUNT_ID:?EXPECTED_ACCOUNT_ID must be set}"

if [[ ! -f "$DC_AMIS_JSON" ]]; then
  echo "::error::trusted DC registry not found at the expected protected-provenance path" >&2
  exit 1
fi

# jq -e exits non-zero when the key is absent or null; `|| true` keeps set -e
# from killing the script before the explicit emptiness check below.
AMI_ID="$(jq -e -r --arg env "$DC_ENV_KEY" '.[$env]' "$DC_AMIS_JSON" 2>/dev/null || true)"
if [[ -z "$AMI_ID" || "$AMI_ID" == "null" ]]; then
  echo "::error::no prebaked DC AMI id for '${DC_ENV_KEY}' in the trusted DC registry" >&2
  exit 1
fi

if ! printf '%s' "$AMI_ID" | grep -qE '^ami-[0-9a-f]{8,}$'; then
  echo "::error::prebaked DC AMI id for '${DC_ENV_KEY}' is not a valid AMI id" >&2
  exit 1
fi

# --owners scopes the lookup to the expected account, so an id owned by (or
# shared from) another account, or one that no longer exists, returns no image.
STATE="$(aws ec2 describe-images \
  --image-ids "$AMI_ID" \
  --owners "$EXPECTED_ACCOUNT_ID" \
  --query 'Images[0].State' --output text 2>/dev/null || true)"
if [[ "$STATE" != "available" ]]; then
  echo "::error::prebaked DC AMI for '${DC_ENV_KEY}' is not an available image owned by the publish-target account" >&2
  exit 1
fi

printf '%s\n' "$AMI_ID"
