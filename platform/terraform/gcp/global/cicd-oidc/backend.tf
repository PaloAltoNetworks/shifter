terraform {
  # Bucket/prefix are supplied via -backend-config="bucket=..." -backend-config="prefix=cicd-oidc"
  # at init time. The bucket is ${project_id}-terraform-state and the prefix keeps this
  # foundational OIDC/WIF identity state separate from the gcp-dev platform root, so a
  # platform destroy never removes the credentials CI authenticates as.
  backend "gcs" {
    bucket = "OVERRIDDEN_VIA_BACKEND_CONFIG"
    prefix = "OVERRIDDEN_VIA_BACKEND_CONFIG"
  }
}
