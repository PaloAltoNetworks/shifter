# Dev Box - Manually managed Windows development instance
# NOT managed by CI/CD - apply manually with:
#   cd terraform/global/dev-box
#   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform init
#   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform apply

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket  = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key     = "global/dev-box/terraform.tfstate"
    region  = "us-east-2"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# Latest Windows Server 2022 AMI
data "aws_ami" "windows" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Windows_Server-2022-English-Full-Base-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Use default VPC for simplicity
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security group for dev box
resource "aws_security_group" "dev_box" {
  name        = "shifter-dev-box"
  description = "Security group for dev box - RDP and SSM"
  vpc_id      = data.aws_vpc.default.id

  # RDP access (optional - can use SSM Fleet Manager instead)
  ingress {
    description = "RDP from allowed IPs"
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = var.allowed_rdp_cidrs
  }

  # All outbound
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "shifter-dev-box"
    Project = "shifter"
  }
}

# IAM role for dev box
resource "aws_iam_role" "dev_box" {
  name = "shifter-dev-box"

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
    Name    = "shifter-dev-box"
    Project = "shifter"
  }
}

# SSM managed instance policy for Session Manager access
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.dev_box.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Dev permissions - broad access for development work
resource "aws_iam_role_policy" "dev_permissions" {
  name = "dev-permissions"
  role = aws_iam_role.dev_box.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Access"
        Effect = "Allow"
        Action = ["s3:*"]
        Resource = [
          "arn:aws:s3:::shifter-*",
          "arn:aws:s3:::shifter-*/*"
        ]
      },
      {
        Sid      = "ECRAccess"
        Effect   = "Allow"
        Action   = ["ecr:*"]
        Resource = "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/shifter-*"
      },
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "SecretsManager"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter-*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "dev_box" {
  name = "shifter-dev-box"
  role = aws_iam_role.dev_box.name
}

# Spot instance request
resource "aws_spot_instance_request" "dev_box" {
  ami                    = data.aws_ami.windows.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.dev_box.id]
  iam_instance_profile   = aws_iam_instance_profile.dev_box.name

  # Spot config
  spot_type            = "persistent"
  wait_for_fulfillment = true

  # Root volume - generous size for dev tools
  root_block_device {
    volume_size           = var.root_volume_size
    volume_type           = "gp3"
    delete_on_termination = false # Persist data across spot interruptions
    encrypted             = true
  }

  # User data to set up admin password and install tools
  user_data = base64encode(<<-EOF
    <powershell>
    # Set administrator password
    $Password = ConvertTo-SecureString "${var.admin_password}" -AsPlainText -Force
    Set-LocalUser -Name "Administrator" -Password $Password

    # Enable RDP
    Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name "fDenyTSConnections" -Value 0
    Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

    # Install Chocolatey
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

    # Install dev tools
    choco install -y git
    choco install -y python312
    choco install -y nodejs-lts
    choco install -y awscli
    choco install -y terraform
    choco install -y vscode
    choco install -y googlechrome

    # Install Claude Code (via npm after Node is installed)
    refreshenv
    npm install -g @anthropic-ai/claude-code
    </powershell>
  EOF
  )

  tags = {
    Name    = "shifter-dev-box"
    Project = "shifter"
  }
}

# Tag the spot instance once it's created
resource "aws_ec2_tag" "dev_box_name" {
  resource_id = aws_spot_instance_request.dev_box.spot_instance_id
  key         = "Name"
  value       = "shifter-dev-box"
}

resource "aws_ec2_tag" "dev_box_project" {
  resource_id = aws_spot_instance_request.dev_box.spot_instance_id
  key         = "Project"
  value       = "shifter"
}
