terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend configured via -backend-config during init
  # This allows separate state per environment
  backend "s3" {}
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
