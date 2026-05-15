terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0"
    }
    # Required for ``random_password.guest`` per-instance secrets (#762).
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
  }

  # Partial backend configuration - actual values passed via -backend-config at init
  backend "s3" {}
}
