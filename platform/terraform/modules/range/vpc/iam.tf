# Range Instance IAM Configuration
#
# Creates IAM resources for range EC2 instances (Victim, Kali, DC):
# - IAM role with EC2 assume role trust
# - SSM managed instance core policy for Systems Manager access
# - S3 read access for agent installers
# - Instance profile to attach role to EC2 instances
#
# Range guests do NOT access SSM Parameter Store via this role. Guest setup is
# brokered by the engine provisioner; secret-bearing password delivery uses a
# host-key-pinned SSH stdin channel after non-secret SSM bootstrap.
# A direct Parameter Store grant here would be over-broad and cross-tenant;
# see issue #1178 and scripts/check_tf_iam_ssm_range_scope.

# Data sources for constructing ARNs
data "aws_caller_identity" "current" {}

# ------------------------------------------------------------------------------
# Range Instance IAM Role (for Victim, Kali, and DC EC2s)
# ------------------------------------------------------------------------------

resource "aws_iam_role" "range_instance" {
  name                 = "${local.iam_name_prefix}-range-instance"
  permissions_boundary = var.permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-range-instance"
    Module = "range-vpc"
  })
}

resource "aws_iam_role_policy_attachment" "range_instance_ssm" {
  role       = aws_iam_role.range_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# S3 read access for downloading agent installers during user data bootstrap
resource "aws_iam_role_policy" "range_instance_s3" {
  name = "s3-agent-read"
  role = aws_iam_role.range_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "arn:aws:s3:::${var.agent_s3_bucket}/*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "range_instance" {
  name = "${local.iam_name_prefix}-range-instance"
  role = aws_iam_role.range_instance.name

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-range-instance"
    Module = "range-vpc"
  })
}
