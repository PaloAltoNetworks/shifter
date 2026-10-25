terraform {
  # Bucket/prefix supplied via -backend-config="bucket=..." -backend-config="prefix=..."
  # at init time (see .github/workflows/_gcp-dev.yml).
  backend "gcs" {
    bucket = "OVERRIDDEN_VIA_BACKEND_CONFIG"
    prefix = "OVERRIDDEN_VIA_BACKEND_CONFIG"
  }
}
