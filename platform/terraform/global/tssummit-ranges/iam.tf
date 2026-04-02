# ------------------------------------------------------------------------------
# SSM Instance Role
# ------------------------------------------------------------------------------
# Shared IAM role for range instances (WinServer, WinDesktop, workstation,
# webserver) to enable SSM management.
# ------------------------------------------------------------------------------

resource "aws_iam_role" "ssm_instance" {
  name = "${local.prefix}-ssm-instance"

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

  tags = {
    Name = "${local.prefix}-ssm-instance"
  }
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ssm_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ssm_instance" {
  name = "${local.prefix}-ssm-instance"
  role = aws_iam_role.ssm_instance.name

  tags = {
    Name = "${local.prefix}-ssm-instance"
  }
}
