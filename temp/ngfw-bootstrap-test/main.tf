terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

locals {
  name_prefix = "ngfw-bootstrap-test"
}

# ------------------------------------------------------------------------------
# Data Sources
# ------------------------------------------------------------------------------

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_subnet" "selected" {
  id = data.aws_subnets.default.ids[0]
}

# ------------------------------------------------------------------------------
# S3 Bootstrap Bucket
# ------------------------------------------------------------------------------

resource "aws_s3_bucket" "bootstrap" {
  bucket        = "${local.name_prefix}-bootstrap-${random_id.suffix.hex}"
  force_destroy = true

  tags = {
    Name        = "${local.name_prefix}-bootstrap"
    Environment = "test"
    Purpose     = "ngfw-bootstrap-test"
  }
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket_versioning" "bootstrap" {
  bucket = aws_s3_bucket.bootstrap.id
  versioning_configuration {
    status = "Enabled"
  }
}

# ------------------------------------------------------------------------------
# Bootstrap Files - S3 Structure
# config/
#   init-cfg.txt
#   bootstrap.xml
# content/
#   .keep
# license/
#   authcodes (optional for test)
# software/
#   .keep
# ------------------------------------------------------------------------------

resource "aws_s3_object" "init_cfg" {
  bucket  = aws_s3_bucket.bootstrap.id
  key     = "config/init-cfg.txt"
  content = templatefile("${path.module}/templates/init-cfg.txt.tpl", {
    hostname  = "ngfw-test"
    pin_id    = var.scm_pin_id
    pin_value = var.scm_pin_value
    dgname    = var.scm_folder_name
  })
}

resource "aws_s3_object" "bootstrap_xml" {
  bucket  = aws_s3_bucket.bootstrap.id
  key     = "config/bootstrap.xml"
  content = templatefile("${path.module}/templates/bootstrap.xml.tpl", {
    admin_password_hash = var.admin_password_hash
  })
}

resource "aws_s3_object" "content_placeholder" {
  bucket  = aws_s3_bucket.bootstrap.id
  key     = "content/.keep"
  content = ""
}

resource "aws_s3_object" "license_placeholder" {
  bucket  = aws_s3_bucket.bootstrap.id
  key     = "license/.keep"
  content = ""
}

resource "aws_s3_object" "software_placeholder" {
  bucket  = aws_s3_bucket.bootstrap.id
  key     = "software/.keep"
  content = ""
}

# Add authcodes if provided
resource "aws_s3_object" "authcodes" {
  count   = var.authcode != "" ? 1 : 0
  bucket  = aws_s3_bucket.bootstrap.id
  key     = "license/authcodes"
  content = var.authcode
}

# ------------------------------------------------------------------------------
# Security Groups
# ------------------------------------------------------------------------------

resource "aws_security_group" "ngfw_mgmt" {
  name        = "${local.name_prefix}-mgmt"
  description = "NGFW management interface"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-mgmt-sg"
  }
}

resource "aws_security_group" "ngfw_data" {
  name        = "${local.name_prefix}-data"
  description = "NGFW data interface"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "All traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-data-sg"
  }
}

# ------------------------------------------------------------------------------
# SSH Key Pair
# ------------------------------------------------------------------------------

resource "tls_private_key" "ngfw" {
  algorithm = "ED25519"
}

resource "aws_key_pair" "ngfw" {
  key_name   = "${local.name_prefix}-key"
  public_key = tls_private_key.ngfw.public_key_openssh
}

resource "local_file" "private_key" {
  content         = tls_private_key.ngfw.private_key_openssh
  filename        = "${path.module}/ngfw-test-key.pem"
  file_permission = "0600"
}

# ------------------------------------------------------------------------------
# IAM Role for S3 Bootstrap Access
# ------------------------------------------------------------------------------

resource "aws_iam_role" "ngfw" {
  name = "${local.name_prefix}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "ngfw_bootstrap" {
  name = "${local.name_prefix}-bootstrap-policy"
  role = aws_iam_role.ngfw.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.bootstrap.arn,
        "${aws_s3_bucket.bootstrap.arn}/*"
      ]
    }]
  })
}

resource "aws_iam_instance_profile" "ngfw" {
  name = "${local.name_prefix}-profile"
  role = aws_iam_role.ngfw.name
}

# ------------------------------------------------------------------------------
# Network Interfaces
# ------------------------------------------------------------------------------

resource "aws_network_interface" "mgmt" {
  subnet_id       = data.aws_subnet.selected.id
  security_groups = [aws_security_group.ngfw_mgmt.id]
  description     = "NGFW management interface"

  tags = {
    Name = "${local.name_prefix}-mgmt-eni"
  }
}

resource "aws_network_interface" "data" {
  subnet_id         = data.aws_subnet.selected.id
  security_groups   = [aws_security_group.ngfw_data.id]
  source_dest_check = false
  description       = "NGFW data interface"

  tags = {
    Name = "${local.name_prefix}-data-eni"
  }
}

# ------------------------------------------------------------------------------
# EC2 Instance
# ------------------------------------------------------------------------------

resource "aws_instance" "ngfw" {
  ami                  = var.vm_series_ami_id
  instance_type        = var.instance_type
  key_name             = aws_key_pair.ngfw.key_name
  iam_instance_profile = aws_iam_instance_profile.ngfw.name

  # Management ENI as primary (device_index 0)
  network_interface {
    device_index         = 0
    network_interface_id = aws_network_interface.mgmt.id
  }

  # Data ENI as secondary (device_index 1 = ethernet1/1)
  network_interface {
    device_index         = 1
    network_interface_id = aws_network_interface.data.id
  }

  user_data = "vmseries-bootstrap-aws-s3bucket=${aws_s3_bucket.bootstrap.id}"

  tags = {
    Name        = "${local.name_prefix}-instance"
    Environment = "test"
    Purpose     = "ngfw-bootstrap-test"
  }
}

# ------------------------------------------------------------------------------
# Elastic IP for Management Access
# ------------------------------------------------------------------------------

resource "aws_eip" "mgmt" {
  domain            = "vpc"
  network_interface = aws_network_interface.mgmt.id

  tags = {
    Name = "${local.name_prefix}-mgmt-eip"
  }

  depends_on = [aws_instance.ngfw]
}
