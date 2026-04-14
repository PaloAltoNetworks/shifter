#------------------------------------------------------------------------------
# Shared per-account IAM resources. IAM role + instance profile names are
# unique per account, so this layer holds the single copies that every
# POLARIS range instance reuses — every polaris VM + A2 DC wants the same
# permissions (SSM-managed-core + S3 read on the build tarball bucket),
# so one role / one profile is architecturally correct.
#
# Security groups do NOT live here. SG rules are per-range and live in
# ranges.tf alongside the subnet they protect — matching the shifter
# provisioner module (shifter/engine/provisioner/terraform/modules/range/
# main.tf:82-165), which scopes every ingress rule to a single subnet
# CIDR and routes inter-subnet traffic through an NGFW. A "shared SG
# allowing 10.1.0.0/16" would let range 1's kali reach range 0's DC at
# layer 3, which is exactly the cross-range leak we're preventing.
#------------------------------------------------------------------------------

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
