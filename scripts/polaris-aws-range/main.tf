#------------------------------------------------------------------------------
# POLARIS test range — one VM inside the existing dev range VPC running the
# polaris docker-compose stack with --network host on the attacker container.
#
# This is a manual "user range" — cyberscript/provisioner is bypassed; DB
# records are populated by a separate script once the VM is up.
#------------------------------------------------------------------------------

locals {
  name_prefix = "polaris-bake"
}

# New /28 subnet inside the existing range VPC.
resource "aws_subnet" "polaris" {
  vpc_id            = var.range_vpc_id
  cidr_block        = var.polaris_subnet_cidr
  availability_zone = var.availability_zone

  map_public_ip_on_launch = false

  tags = {
    Name    = "${local.name_prefix}-subnet"
    Project = "polaris"
    Purpose = "bake"
  }
}

# Dedicated route table that bypasses the range Network Firewall (which only
# allowlists GCP/Cortex IPs, not Docker Hub / apt archives). For the bake
# phase we need generic internet egress so `docker build` and `apt install`
# work. Egress path: POLARIS subnet -> NAT gateway -> IGW.
resource "aws_route_table" "polaris" {
  vpc_id = var.range_vpc_id

  tags = {
    Name    = "${local.name_prefix}-rt"
    Project = "polaris"
  }
}

resource "aws_route" "polaris_default" {
  route_table_id         = aws_route_table.polaris.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = var.nat_gateway_id
}

# Keep portal-to-range reachability (so the Shifter portal terminal UI +
# Guacamole, which live in the portal VPC, can hit the kali container's
# published ports).
resource "aws_route" "polaris_portal_peering" {
  route_table_id            = aws_route_table.polaris.id
  destination_cidr_block    = var.portal_vpc_cidr
  vpc_peering_connection_id = var.portal_peering_id
}

resource "aws_route_table_association" "polaris" {
  subnet_id      = aws_subnet.polaris.id
  route_table_id = aws_route_table.polaris.id
}

#------------------------------------------------------------------------------
# Security group — match the normal shifter range pattern: allow anything
# from the VPC CIDR and anything from the portal VPC (over peering).
#------------------------------------------------------------------------------
resource "aws_security_group" "polaris" {
  name        = "${local.name_prefix}-sg"
  description = "POLARIS bake range - allow intra-VPC and portal-peering ingress"
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

#------------------------------------------------------------------------------
# IAM — instance profile with SSM Session Manager + S3 read on the bake bucket
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

#------------------------------------------------------------------------------
# EC2 instance — one m5.2xlarge running the full polaris docker-compose stack
#------------------------------------------------------------------------------
resource "aws_instance" "polaris" {
  ami                    = var.ubuntu_ami_id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.polaris.id
  private_ip             = var.polaris_instance_private_ip
  vpc_security_group_ids = [aws_security_group.polaris.id]
  iam_instance_profile   = aws_iam_instance_profile.polaris.name

  associate_public_ip_address = false

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    tarball_s3_uri      = var.build_tarball_s3_uri
    kali_authorized_key = var.kali_authorized_key
  })

  user_data_replace_on_change = true

  root_block_device {
    volume_size           = 50
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true
  }

  tags = {
    Name    = "polaris-range"
    Project = "polaris"
    Purpose = "bake-range"
  }
}

#------------------------------------------------------------------------------
# A2 Windows Domain Controller — Windows Server 2022, AD DS for BOREAS.LOCAL
#
# Lives alongside the polaris docker-compose VM in the same /28 subnet so
# the compose `dns` container can resolve dc01.boreas.local to this VM's
# private IP and the docker bridge MASQUERADE path lets Kali reach it.
#
# First-boot user_data promotes the box to a BOREAS.LOCAL forest and
# reboots. Post-promotion AD content (OUs, users, groups, SPNs, DCSync ACL,
# badgelogs + admin_flag shares) is applied by `a2_setup.ps1` via SSM Run
# Command — that script is idempotent and safe to re-run if anything drifts.
#------------------------------------------------------------------------------
resource "aws_instance" "a2_dc" {
  ami                    = var.a2_dc_ami_id
  instance_type          = var.a2_instance_type
  subnet_id              = aws_subnet.polaris.id
  private_ip             = var.a2_private_ip
  vpc_security_group_ids = [aws_security_group.polaris.id]
  iam_instance_profile   = aws_iam_instance_profile.polaris.name

  associate_public_ip_address = false

  get_password_data = false

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 3
  }

  user_data = templatefile("${path.module}/a2_user_data.ps1.tpl", {
    admin_password = var.a2_administrator_password
  })

  user_data_replace_on_change = true

  root_block_device {
    volume_size           = 80
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true
  }

  tags = {
    Name    = "polaris-a2-dc"
    Project = "polaris"
    Purpose = "boreas.local AD DC"
    Role    = "dc"
  }
}
