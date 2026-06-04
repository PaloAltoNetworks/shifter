#!/bin/bash
# Shifter portal runtime-secret helpers. Sourced by entrypoint.sh at
# container start; isolated into its own file so the regression tests in
# `tests/test_entrypoint_lib.sh` can exercise the function without
# running the entire entrypoint (which migrates the DB, collects static
# files, and execs the web server).

# ------------------------------------------------------------------------------
# fetch_runtime_secret
# ------------------------------------------------------------------------------
# Fetch a Secrets Manager / GCP Secret Manager value and print its
# string payload on stdout. Returns the python subshell's exit code so
# `set -euo pipefail` in the caller aborts on fetch failure (issue #52).
#
# Earlier versions ended with a bare `return 0`, which silently turned a
# failed AWS/GCP secret call into "return 0 + empty stdout". Combined
# with `EXPORT_VAR=$(fetch_runtime_secret …)` callers, that left
# required env vars like DC_DOMAIN_PASSWORD empty and let the container
# run in a broken-but-up state instead of aborting at startup. The fix
# is to NOT mask the exit code — bash propagates the heredoc's exit
# code as the function's exit code, which propagates through the
# command substitution back to the caller's `set -e`.

fetch_runtime_secret() {
    local secret_name="$1"
    python - "$secret_name" <<'PY'
import os
import sys

provider = os.environ.get("CLOUD_PROVIDER", "aws")
secret_id = sys.argv[1]

if provider == "gcp":
    from google.cloud import secretmanager

    name = secret_id
    if "/versions/" not in name:
        if name.startswith("projects/"):
            name = f"{name}/versions/latest"
        else:
            project_id = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
            if not project_id:
                raise RuntimeError("GCP_PROJECT_ID or GOOGLE_CLOUD_PROJECT is required for Secret Manager access")
            name = f"projects/{project_id}/secrets/{name}/versions/latest"

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": name})
    print(response.payload.data.decode("utf-8"))
else:
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("CLOUD_REGION") or "us-east-2"
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_id)
    print(response["SecretString"])
PY
}
