#------------------------------------------------------------------------------
# Shared per-account / per-VPC resources. One copy drives every POLARIS
# range produced by ranges.tf, because:
#
# - AWS security group names are unique per VPC, so we can't have
#   "polaris-bake-sg" three times in the same range VPC — but one SG can
#   attach to 220 ENIs (110 ranges × 2 instances) just fine, and its rules
#   (allow anything from 10.1.0.0/16 + portal VPC peering CIDR) are
#   identical for every range.
# - AWS IAM role + instance profile names are unique per account, so we
#   can't have "polaris-bake-instance-role" three times in this account —
#   but every POLARIS instance wants the exact same permissions (SSM core
#   + S3 read on the build tarball bucket), so one role/profile is what
#   we actually want architecturally.
#------------------------------------------------------------------------------

resource "aws_security_group" "polaris" {
  name        = "${local.name_prefix}-sg"
  description = "POLARIS range - allow intra-VPC and portal-peering ingress"
  vpc_id      = var.range_vpc_id

  ingress {
    description = "All intra-range-VPC traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["10.1.0.0/16"]
  }

  ingress {
    description = "SSH from portal VPC (terminal UI)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.portal_vpc_cidr]
  }

  ingress {
    description = "RDP from portal VPC (Guacamole)"
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = [var.portal_vpc_cidr]
  }

  egress {
    description = "All outbound (bake-time apt/docker/S3)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${local.name_prefix}-sg"
    Project = "polaris"
  }
}

resource "aws_iam_role" "polaris" {
  name = "${local.name_prefix}-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "polaris_ssm" {
  role       = aws_iam_role.polaris.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "polaris_s3_read" {
  name = "polaris-bake-s3-read"
  role = aws_iam_role.polaris.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket",
      ]
      Resource = [
        "arn:aws:s3:::${var.build_tarball_bucket}",
        "arn:aws:s3:::${var.build_tarball_bucket}/*",
      ]
    }]
  })
}

resource "aws_iam_instance_profile" "polaris" {
  name = "${local.name_prefix}-instance-profile"
  role = aws_iam_role.polaris.name
}
