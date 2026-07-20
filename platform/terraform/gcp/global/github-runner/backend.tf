terraform {
  # Bucket/prefix are supplied via -backend-config="bucket=..." -backend-config="prefix=github-runner"
  # at init time (scripts/bootstrap/gcp_runner.py -> apply_runner_terraform). The
  # bucket is ${project_id}-terraform-state and the prefix keeps the runner state
  # separate from the gcp-dev platform root so a platform destroy never removes it.
  backend "gcs" {
    bucket = "OVERRIDDEN_VIA_BACKEND_CONFIG"
    prefix = "OVERRIDDEN_VIA_BACKEND_CONFIG"
  }
}
