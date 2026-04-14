#------------------------------------------------------------------------------
# Per-range resources. Every entry in var.range_indices produces its own
# /28 subnet, route table, polaris VM, and A2 DC — instance .10 and .11
# inside the /28 respectively. The local.range_subnets map defined in
# main.tf builds the CIDR + IP plan via cidrsubnet()/cidrhost().
#
# Resource addresses use the range index as the for_each key so state
# stays stable across add/remove of other indices — i.e. removing index
# "1" does not renumber "2".
#------------------------------------------------------------------------------

resource "aws_subnet" "polaris" {
  for_each = local.range_subnets

  vpc_id            = var.range_vpc_id
  cidr_block        = each.value.cidr
  availability_zone = var.availability_zone

  map_public_ip_on_launch = false

  tags = {
    Name    = "${local.name_prefix}-subnet-${each.key}"
    Project = "polaris"
    Purpose = "bake"
    Range   = each.key
  }
}

# Dedicated route table per range that bypasses the range Network Firewall
# (which only allowlists GCP/Cortex IPs, not Docker Hub / apt archives).
# Egress path: POLARIS subnet -> NAT gateway -> IGW.
resource "aws_route_table" "polaris" {
  for_each = local.range_subnets

  vpc_id = var.range_vpc_id

  tags = {
    Name    = "${local.name_prefix}-rt-${each.key}"
    Project = "polaris"
    Range   = each.key
  }
}

resource "aws_route" "polaris_default" {
  for_each = local.range_subnets

  route_table_id         = aws_route_table.polaris[each.key].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = var.nat_gateway_id
}

# Keep portal-to-range reachability (so the Shifter portal terminal UI +
# Guacamole can hit the kali container's published ports).
resource "aws_route" "polaris_portal_peering" {
  for_each = local.range_subnets

  route_table_id            = aws_route_table.polaris[each.key].id
  destination_cidr_block    = var.portal_vpc_cidr
  vpc_peering_connection_id = var.portal_peering_id
}

resource "aws_route_table_association" "polaris" {
  for_each = local.range_subnets

  subnet_id      = aws_subnet.polaris[each.key].id
  route_table_id = aws_route_table.polaris[each.key].id
}

#------------------------------------------------------------------------------
# Per-range security group. Matches the shifter provisioner pattern at
# shifter/engine/provisioner/terraform/modules/range/main.tf:82-165:
#
# - intra-subnet rule scoped to `each.value.cidr` (the /28), NOT the whole
#   range VPC CIDR — so range 1's kali cannot reach range 0's DC at L3
#   even though both sit inside 10.1.0.0/16
# - portal ssh (22) + rdp (3389) ingress from var.portal_vpc_cidr, so the
#   Shifter portal terminal + Guacamole can still key-auth + RDP in
# - egress all — cold docker build needs apt.kali.org, docker hub, pypi
#
# Name suffix `-${each.key}` keeps SG names unique per VPC so all N ranges
# can coexist. Running this for 110 ranges creates 110 SGs, well inside
# the default AWS SG-per-VPC quota (typically 2500).
#------------------------------------------------------------------------------
resource "aws_security_group" "polaris" {
  for_each = local.range_subnets

  vpc_id      = var.range_vpc_id
  name        = "${local.name_prefix}-sg-${each.key}"
  description = "POLARIS range ${each.key} - intra-${each.value.cidr} + portal-peering only"

  ingress {
    description = "Intra-range /28 traffic (polaris VM to A2 DC and docker host-network Kali)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [each.value.cidr]
  }

  ingress {
    description = "SSH from portal VPC (terminal UI key-auth)"
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
    Name    = "${local.name_prefix}-sg-${each.key}"
    Project = "polaris"
    Range   = each.key
  }

  lifecycle {
    create_before_destroy = true
  }
}

#------------------------------------------------------------------------------
# Polaris VM — Ubuntu running the polaris docker-compose stack.
#------------------------------------------------------------------------------
resource "aws_instance" "polaris" {
  for_each = local.range_subnets

  ami                    = var.ubuntu_ami_id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.polaris[each.key].id
  private_ip             = each.value.polaris_ip
  vpc_security_group_ids = [aws_security_group.polaris[each.key].id]
  iam_instance_profile   = aws_iam_instance_profile.polaris.name

  associate_public_ip_address = false

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    tarball_s3_uri      = var.build_tarball_s3_uri
    kali_authorized_key = var.kali_authorized_key
    a2_private_ip       = each.value.a2_ip
  })

  user_data_replace_on_change = true

  root_block_device {
    volume_size           = 50
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true
  }

  tags = {
    Name    = "polaris-range-${each.key}"
    Project = "polaris"
    Purpose = "bake-range"
    Range   = each.key
  }
}

#------------------------------------------------------------------------------
# A2 Windows Server 2022 DC — BOREAS.LOCAL forest per range.
#
# One DC per range because AD DS cannot be containerized on Linux and every
# forest in these ranges is an isolated island (no trust, no replication).
# Duplicate domain name (boreas.local) + NetBIOS name (BOREAS) are safe
# because each range's DNS container only knows its own dc01, and the range
# subnets don't cross-route at the L3 layer.
#
# First-boot user_data just sets the Administrator password and turns on
# RDP; the full Install-ADDSForest + a2_setup.ps1 flow runs post-apply via
# a2_cold_bootstrap.sh against each instance in parallel.
#------------------------------------------------------------------------------
resource "aws_instance" "a2_dc" {
  for_each = local.range_subnets

  ami                    = var.a2_dc_ami_id
  instance_type          = var.a2_instance_type
  subnet_id              = aws_subnet.polaris[each.key].id
  private_ip             = each.value.a2_ip
  vpc_security_group_ids = [aws_security_group.polaris[each.key].id]
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
    Name    = "polaris-a2-dc-${each.key}"
    Project = "polaris"
    Purpose = "boreas.local AD DC"
    Role    = "dc"
    Range   = each.key
  }
}
