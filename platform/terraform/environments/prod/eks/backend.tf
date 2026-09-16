terraform {
  # Dedicated EKS state. This root must never share, move, import, or destroy
  # resources from the legacy prod portal/ECS state.
  backend "s3" {
    bucket       = "OVERRIDDEN_VIA_BACKEND_CONFIG"
    key          = "OVERRIDDEN_VIA_BACKEND_CONFIG"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }
}
