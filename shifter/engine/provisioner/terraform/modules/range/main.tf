locals {
  # Common tags applied to all resources
  common_tags = {
    "shifter:user_id"      = tostring(var.user_id)
    "shifter:range_id"     = tostring(var.range_id)
    "shifter:environment"  = var.environment
    "shifter:request_uuid" = var.request_uuid
    "shifter:system"       = "shifter"
    "ManagedBy"            = "terraform"
  }

  # Build map of subnet name -> subnet config for lookups
  subnet_map = { for s in var.subnets : s.name => s }

  # Flatten instances across all subnets for resource creation
  all_instances = flatten([
    for subnet in var.subnets : [
      for inst in subnet.instances : {
        key           = "${subnet.name}-${inst.role}-${inst.uuid}"
        subnet_name   = subnet.name
        subnet_uuid   = subnet.uuid
        subnet_cidr   = subnet.cidr
        instance_uuid = inst.uuid
        role          = inst.role
        os_type       = inst.os_type
        instance_type = inst.instance_type
        agent_url     = inst.agent_presigned_url
        join_domain   = inst.join_domain
      }
    ]
  ])

  # Map for instance lookups by key
  instance_map = { for inst in local.all_instances : inst.key => inst }

  # Get all connected pairs (bidirectional, deduplicated)
  # Build pairs from connected_to lists
  raw_pairs = flatten([
    for subnet in var.subnets : [
      for other_name in subnet.connected_to : {
        from = subnet.name
        to   = other_name
      }
    ]
  ])

  # Deduplicate pairs by sorting names alphabetically
  # sort() works on strings and returns them in lexicographic order
  connected_pairs = distinct([
    for pair in local.raw_pairs : {
      a = sort([pair.from, pair.to])[0]
      b = sort([pair.from, pair.to])[1]
    }
  ])

  # DC instances for SSM parameter creation
  dc_instances = [for inst in local.all_instances : inst if inst.role == "dc"]
}

#------------------------------------------------------------------------------
# Subnets
#------------------------------------------------------------------------------
resource "aws_subnet" "range" {
  for_each = local.subnet_map

  vpc_id            = var.vpc_id
  cidr_block        = each.value.cidr
  availability_zone = var.availability_zone

  tags = merge(local.common_tags, {
    Name                   = "shifter-${each.key}-${var.user_id}"
    "shifter:subnet_name"  = each.key
    "shifter:subnet_uuid"  = each.value.uuid
  })
}

#------------------------------------------------------------------------------
# Security Groups (one per subnet)
#------------------------------------------------------------------------------
resource "aws_security_group" "subnet" {
  for_each = local.subnet_map

  vpc_id      = var.vpc_id
  name        = "shifter-${each.key}-${var.range_id}-sg"
  description = "Security group for ${each.key} subnet in range ${var.range_id}"

  # Allow all intra-subnet traffic
  ingress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = [each.value.cidr]
    description = "Allow all intra-subnet traffic"
  }

  # Allow all outbound traffic
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = merge(local.common_tags, {
    Name = "shifter-${each.key}-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# Dynamic ingress rules for connected subnets (NGFW does actual filtering)
# If subnet A has connected_to: ["B"], this creates an ingress rule on B's SG allowing traffic from A
resource "aws_security_group_rule" "connected_subnet" {
  for_each = {
    for pair in flatten([
      for subnet in var.subnets : [
        for connected_name in subnet.connected_to : {
          key             = "${connected_name}-from-${subnet.name}"
          security_group  = connected_name
          source_cidr     = subnet.cidr
          source_name     = subnet.name
        } if contains(keys(local.subnet_map), connected_name)
      ]
    ]) : pair.key => pair
  }

  type              = "ingress"
  security_group_id = aws_security_group.subnet[each.value.security_group].id
  protocol          = "-1"
  from_port         = 0
  to_port           = 0
  cidr_blocks       = [each.value.source_cidr]
  description       = "Allow from subnet ${each.value.source_name} (filtered by NGFW)"
}

# SSH ingress from portal VPC
resource "aws_security_group_rule" "portal_ssh" {
  for_each = var.portal_vpc_cidr != "" ? local.subnet_map : {}

  type              = "ingress"
  security_group_id = aws_security_group.subnet[each.key].id
  protocol          = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_blocks       = [var.portal_vpc_cidr]
  description       = "Allow SSH from portal"
}

# RDP ingress from portal VPC
resource "aws_security_group_rule" "portal_rdp" {
  for_each = var.portal_vpc_cidr != "" ? local.subnet_map : {}

  type              = "ingress"
  security_group_id = aws_security_group.subnet[each.key].id
  protocol          = "tcp"
  from_port         = 3389
  to_port           = 3389
  cidr_blocks       = [var.portal_vpc_cidr]
  description       = "Allow RDP from portal"
}

#------------------------------------------------------------------------------
# Route Tables (one per subnet)
#------------------------------------------------------------------------------
resource "aws_route_table" "subnet" {
  for_each = local.subnet_map

  vpc_id = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "shifter-${each.key}-rt"
  })
}

resource "aws_route_table_association" "subnet" {
  for_each = local.subnet_map

  subnet_id      = aws_subnet.range[each.key].id
  route_table_id = aws_route_table.subnet[each.key].id
}

# Portal route (via VPC peering)
resource "aws_route" "portal" {
  for_each = var.portal_vpc_cidr != "" && var.portal_vpc_peering_id != "" ? local.subnet_map : {}

  route_table_id            = aws_route_table.subnet[each.key].id
  destination_cidr_block    = var.portal_vpc_cidr
  vpc_peering_connection_id = var.portal_vpc_peering_id
}

# Internet route (via AWS Network Firewall)
resource "aws_route" "firewall" {
  for_each = var.firewall_endpoint_id != "" ? local.subnet_map : {}

  route_table_id         = aws_route_table.subnet[each.key].id
  destination_cidr_block = "0.0.0.0/0"
  vpc_endpoint_id        = var.firewall_endpoint_id
}

# S3 endpoint association
resource "aws_vpc_endpoint_route_table_association" "s3" {
  for_each = var.s3_endpoint_id != "" ? local.subnet_map : {}

  vpc_endpoint_id = var.s3_endpoint_id
  route_table_id  = aws_route_table.subnet[each.key].id
}

# Inter-subnet routes via NGFW (all subnets route to all other subnets via NGFW)
resource "aws_route" "ngfw" {
  for_each = var.ngfw_data_eni_id != "" ? {
    for pair in flatten([
      for subnet_a in var.subnets : [
        for subnet_b in var.subnets : {
          key         = "${subnet_a.name}-to-${subnet_b.name}"
          from_subnet = subnet_a.name
          to_cidr     = subnet_b.cidr
        } if subnet_a.name != subnet_b.name
      ]
    ]) : pair.key => pair
  } : {}

  route_table_id         = aws_route_table.subnet[each.value.from_subnet].id
  destination_cidr_block = each.value.to_cidr
  network_interface_id   = var.ngfw_data_eni_id

  depends_on = [aws_route_table.subnet]
}

#------------------------------------------------------------------------------
# SSH Key Pairs (one per instance)
#------------------------------------------------------------------------------
resource "tls_private_key" "instance" {
  for_each = local.instance_map

  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_secretsmanager_secret" "ssh_key" {
  for_each = local.instance_map

  name                    = "shifter/${var.environment}/range/${var.range_id}/${each.value.role}-${substr(each.value.instance_uuid, 0, 8)}-ssh-key"
  description             = "SSH private key for ${each.value.role} instance ${each.value.instance_uuid}"
  recovery_window_in_days = 0 # Immediate delete for cleanup

  tags = merge(local.common_tags, {
    "shifter:instance_uuid" = each.value.instance_uuid
    "shifter:role"          = each.value.role
  })
}

resource "aws_secretsmanager_secret_version" "ssh_key" {
  for_each = local.instance_map

  secret_id     = aws_secretsmanager_secret.ssh_key[each.key].id
  secret_string = tls_private_key.instance[each.key].private_key_pem
}

#------------------------------------------------------------------------------
# DC SSM Parameter (for domain join - populated by Ansible after DC boots)
#------------------------------------------------------------------------------
resource "aws_ssm_parameter" "dc_config" {
  count = length(local.dc_instances) > 0 ? 1 : 0

  name        = "/shifter/${var.environment}/range/${var.range_id}/dc-config"
  type        = "SecureString"
  value       = "{}" # Empty JSON, populated by Ansible after DC verification
  description = "Domain controller configuration for range ${var.range_id}"

  tags = local.common_tags
}

#------------------------------------------------------------------------------
# EC2 Instances
#------------------------------------------------------------------------------
resource "aws_instance" "range" {
  for_each = local.instance_map

  ami           = lookup({
    "kali"    = var.kali_ami_id
    "ubuntu"  = var.victim_ami_id
    "windows" = each.value.role == "dc" ? var.dc_ami_id : var.windows_ami_id
  }, each.value.os_type, var.victim_ami_id)

  instance_type          = each.value.instance_type
  subnet_id              = aws_subnet.range[each.value.subnet_name].id
  vpc_security_group_ids = [aws_security_group.subnet[each.value.subnet_name].id]
  iam_instance_profile   = var.instance_profile_name != "" ? var.instance_profile_name : null

  # User data based on role and OS
  user_data_base64 = base64encode(
    each.value.role == "attacker" ? templatefile("${path.module}/templates/kali.sh.tpl", {
      hostname   = "shifter-kali-${var.range_id}"
      public_key = tls_private_key.instance[each.key].public_key_openssh
    }) :
    each.value.role == "dc" ? templatefile("${path.module}/templates/dc_windows.ps1.tpl", {}) :
    each.value.os_type == "windows" ? templatefile("${path.module}/templates/victim_windows.ps1.tpl", {}) :
    templatefile("${path.module}/templates/victim_linux.sh.tpl", {})
  )

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1
  }

  tags = merge(local.common_tags, {
    Name                    = "shifter-${each.value.role}-${var.range_id}"
    "shifter:role"          = each.value.role
    "shifter:os"            = each.value.os_type
    "shifter:instance_uuid" = each.value.instance_uuid
    "shifter:subnet_name"   = each.value.subnet_name
  })

  depends_on = [
    aws_secretsmanager_secret_version.ssh_key,
    aws_security_group.subnet,
    aws_subnet.range,
  ]
}
