terraform {
  backend "s3" {
    bucket         = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key            = "shifter/dev/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-dev-terraform-e3462f0c-c5b5-4b47-836b-efe3f657858c"
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

