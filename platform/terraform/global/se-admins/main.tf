# ------------------------------------------------------------------------------
# SE Admin IAM Users
# ------------------------------------------------------------------------------
# Provisions IAM users with AdministratorAccess for PANW SEs who need
# admin access to the dev AWS account. Console access with password reset
# required on first login.
# ------------------------------------------------------------------------------

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Bucket/key supplied via -backend-config=dev.s3.tfbackend at init time.
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
      Project   = "shifter"
      Component = "se-admins"
      ManagedBy = "terraform"
    }
  }
}

# ------------------------------------------------------------------------------
# IAM Users
# ------------------------------------------------------------------------------

resource "aws_iam_user" "admin" {
  for_each = var.admins

  name = each.key

  tags = {
    Email = each.value.email
  }
}

# ------------------------------------------------------------------------------
# Console Access (password reset required on first login)
# ------------------------------------------------------------------------------

resource "aws_iam_user_login_profile" "admin" {
  for_each = var.admins

  user                    = aws_iam_user.admin[each.key].name
  password_reset_required = true
}

# ------------------------------------------------------------------------------
# AdministratorAccess Policy Attachment
# ------------------------------------------------------------------------------

resource "aws_iam_user_policy_attachment" "admin" {
  for_each = var.admins

  user       = aws_iam_user.admin[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
