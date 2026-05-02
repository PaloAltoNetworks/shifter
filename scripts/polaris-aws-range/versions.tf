terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  profile = "panw-shifter-dev-workstation"
  region  = "us-east-2"

  default_tags {
    tags = {
      Project   = "polaris"
      ManagedBy = "terraform"
      Purpose   = "golden-range-bake"
    }
  }
}
