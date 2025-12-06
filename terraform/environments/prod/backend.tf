/*
 * Terraform S3 backend configuration
 *
 * The S3 bucket and DynamoDB table for state locking are not hardcoded here.
 * Instead, supply them via a backend config file or CLI arguments.
 *
 * These resources must be created before initializing this environment.
 * Ensure the bucket and table names match those referenced in:
 *   terraform/global/iam/github-oidc.tf (lines 112-113, 123)
 *
 * Example usage:
 *   terraform init \
 *     -backend-config="bucket=shifter-infra-<UUID>" \
 *     -backend-config="dynamodb_table=shifter-terraform-<UUID>" \
 *     -backend-config="key=shifter/prod/terraform.tfstate" \
 *     -backend-config="region=us-east-2"
 *
 * Or create a file named prod.tfbackend with:
 *   bucket         = "shifter-infra-<UUID>"
 *   key            = "shifter/prod/terraform.tfstate"
 *   region         = "us-east-2"
 *   dynamodb_table = "shifter-terraform-<UUID>"
 *   encrypt        = true
 *
 * Document where these resources are created and update this comment if the process changes.
 */

terraform {
  backend "s3" {}

  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Environment = "prod"
      Project     = "shifter"
      ManagedBy   = "terraform"
    }
  }
}
