#!/usr/bin/env bash
# Post-deploy live range smoke for GCP (issue #1638).
#
# Runs ``python manage.py run_post_deploy_smoke`` inside the deployed portal
# container via kubectl exec. Requires a configured kubectl context for the
# target GKE cluster and env vars documented in scripts/post_deploy_smoke/README.md.
set -euo pipefail

VARIANT="linux"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --variant)
      VARIANT="${2:?--variant requires a value}"
      shift 2
      ;;
    -h | --help)
      echo "Usage: $0 [--variant linux|windows]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${SMOKE_TEST_USER_EMAIL:-}" ]]; then
  echo "::error::SMOKE_TEST_USER_EMAIL is required" >&2
  exit 1
fi

KUBECTL_REQUEST_TIMEOUT="${KUBECTL_REQUEST_TIMEOUT:-3600s}"

kubectl -n shifter-platform exec deployment/portal-web -c portal \
  --request-timeout="${KUBECTL_REQUEST_TIMEOUT}" -- \
  env SMOKE_TEST_USER_EMAIL="${SMOKE_TEST_USER_EMAIL}" \
  python manage.py run_post_deploy_smoke --variant "${VARIANT}"
