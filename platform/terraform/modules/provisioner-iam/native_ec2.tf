# Native RAES resources use an explicit manager identity instead of claiming
# Terraform ownership. Existing dependent-resource RunInstances grants still
# constrain AMIs to this account, encrypted disks to the range zone, and NICs to
# the range VPC. No instance profile is requested by the native guest realizer.
resource "aws_iam_policy" "native_ec2" {
  name = "${var.name_prefix}-native-ec2-managed"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["ec2:CreateTags"]
        Resource = [for kind in ["instance", "volume", "network-interface", "subnet", "security-group", "route-table"] :
          "arn:aws:ec2:${local.region}:${local.account_id}:${kind}/*"
        ]
        Condition = {
          StringEquals = {
            "ec2:CreateAction"                   = ["RunInstances", "CreateSubnet", "CreateSecurityGroup", "CreateRouteTable"]
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "shifter"
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:RunInstances"]
        Resource = ["arn:aws:ec2:${local.region}:${local.account_id}:instance/*"]
        Condition = {
          StringEquals = {
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "shifter"
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:TerminateInstances", "ec2:StopInstances", "ec2:StartInstances", "ec2:DeleteVolume"]
        Resource = [for kind in ["instance", "volume"] : "arn:aws:ec2:${local.region}:${local.account_id}:${kind}/*"]
        Condition = {
          StringEquals = {
            "ec2:ResourceTag/shifter:system"      = "shifter"
            "ec2:ResourceTag/shifter:environment" = var.environment
            "ec2:ResourceTag/ManagedBy"           = "shifter"
          }
        }
      }
    ]
  })
  tags = var.tags
}
resource "aws_iam_role_policy_attachment" "native_ec2" {
  role       = var.role_name
  policy_arn = aws_iam_policy.native_ec2.arn
}
