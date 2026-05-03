terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Backend bucket/key are environment-specific and supplied via
  # -backend-config=<env>.s3.tfbackend at init time. The values below are
  # placeholders so `terraform validate` succeeds standalone.
  backend "s3" {
    bucket       = "OVERRIDDEN_VIA_BACKEND_CONFIG"
    key          = "OVERRIDDEN_VIA_BACKEND_CONFIG"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "shifter"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}
