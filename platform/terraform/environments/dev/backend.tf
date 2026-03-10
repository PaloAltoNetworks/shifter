terraform {
  backend "s3" {
    bucket         = "shifter-dev-infra-efff7706-a361-4618-8a92-8f942aa55d0e"
    key            = "shifter/dev/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-dev-terraform-efff7706-a361-4618-8a92-8f942aa55d0e"
    encrypt        = true
  }

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
      Environment = "dev"
      Project     = "shifter"
      ManagedBy   = "terraform"
    }
  }
}
