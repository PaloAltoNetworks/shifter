# ------------------------------------------------------------------------------
# VM-Series NGFW - Playground
# ------------------------------------------------------------------------------
# Multi-interface firewall with ENIs in untrust, management, server, and
# workstation subnets. Bootstrap registers with Strata Cloud Manager.
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# Data Sources
# ------------------------------------------------------------------------------

resource "aws_subnet" "server" {
  vpc_id            = data.aws_vpc.default.id
  cidr_block        = var.server_subnet_cidr
  availability_zone = "us-east-2b"

  tags = {
    Name = "${local.prefix}-server"
  }
}

# Default route table for VPC endpoint association
data "aws_route_table" "default" {
  vpc_id = data.aws_vpc.default.id

  filter {
    name   = "association.main"
    values = ["true"]
  }
}

# ------------------------------------------------------------------------------
# Subnets (us-east-2b, replacing former us-east-2a subnets)
# ------------------------------------------------------------------------------

resource "aws_subnet" "untrust" {
  vpc_id            = data.aws_vpc.default.id
  cidr_block        = var.untrust_subnet_cidr
  availability_zone = "us-east-2b"

  tags = {
    Name = "${local.prefix}-untrust"
  }
}

resource "aws_subnet" "management" {
  vpc_id                  = data.aws_vpc.default.id
  cidr_block              = var.management_subnet_cidr
  availability_zone       = "us-east-2b"
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.prefix}-management"
  }
}

resource "aws_subnet" "endpoint" {
  vpc_id            = data.aws_vpc.default.id
  cidr_block        = var.endpoint_subnet_cidr
  availability_zone = "us-east-2b"

  tags = {
    Name = "${local.prefix}-endpoint"
  }
}

# ------------------------------------------------------------------------------
# Security Groups
# ------------------------------------------------------------------------------

resource "aws_security_group" "ngfw_mgmt" {
  name        = "${local.prefix}-ngfw-mgmt"
  description = "NGFW management - SSH and HTTPS"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "${local.prefix}-ngfw-mgmt"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ngfw_mgmt_ssh" {
  security_group_id = aws_security_group.ngfw_mgmt.id
  description       = "SSH from VPC"
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
  cidr_ipv4         = data.aws_vpc.default.cidr_block
}

resource "aws_vpc_security_group_ingress_rule" "ngfw_mgmt_ssh_external" {
  security_group_id = aws_security_group.ngfw_mgmt.id
  description       = "SSH from Brad"
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
  cidr_ipv4         = "165.1.252.13/32"
}

resource "aws_vpc_security_group_ingress_rule" "ngfw_mgmt_https" {
  security_group_id = aws_security_group.ngfw_mgmt.id
  description       = "HTTPS from VPC"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = data.aws_vpc.default.cidr_block
}

resource "aws_vpc_security_group_ingress_rule" "ngfw_mgmt_https_external" {
  security_group_id = aws_security_group.ngfw_mgmt.id
  description       = "HTTPS from Brad"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "165.1.252.13/32"
}

resource "aws_vpc_security_group_ingress_rule" "ngfw_mgmt_ssh_workstation" {
  security_group_id = aws_security_group.ngfw_mgmt.id
  description       = "SSH from workstation"
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
  cidr_ipv4         = "173.181.31.170/32"
}

resource "aws_vpc_security_group_ingress_rule" "ngfw_mgmt_https_workstation" {
  security_group_id = aws_security_group.ngfw_mgmt.id
  description       = "HTTPS from workstation"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "173.181.31.170/32"
}

resource "aws_vpc_security_group_egress_rule" "ngfw_mgmt_all" {
  security_group_id = aws_security_group.ngfw_mgmt.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "ngfw_data" {
  name        = "${local.prefix}-ngfw-data"
  description = "NGFW data interfaces - all traffic"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "${local.prefix}-ngfw-data"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ngfw_data_all" {
  security_group_id = aws_security_group.ngfw_data.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "ngfw_data_all" {
  security_group_id = aws_security_group.ngfw_data.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------------------------
# ENIs
# ------------------------------------------------------------------------------

resource "aws_network_interface" "ngfw_mgmt" {
  subnet_id       = aws_subnet.management.id
  security_groups = [aws_security_group.ngfw_mgmt.id]
  description     = "NGFW management interface"

  tags = {
    Name = "${local.prefix}-ngfw-mgmt"
  }
}

resource "aws_network_interface" "ngfw_untrust" {
  subnet_id         = aws_subnet.untrust.id
  security_groups   = [aws_security_group.ngfw_data.id]
  source_dest_check = false
  description       = "NGFW untrust interface"

  tags = {
    Name = "${local.prefix}-ngfw-untrust"
  }
}

resource "aws_network_interface" "ngfw_server" {
  subnet_id         = aws_subnet.server.id
  security_groups   = [aws_security_group.ngfw_data.id]
  source_dest_check = false
  description       = "NGFW server interface"

  tags = {
    Name = "${local.prefix}-ngfw-server"
  }
}

resource "aws_network_interface" "ngfw_workstation" {
  subnet_id         = aws_subnet.endpoint.id
  security_groups   = [aws_security_group.ngfw_data.id]
  source_dest_check = false
  description       = "NGFW workstation interface"

  tags = {
    Name = "${local.prefix}-ngfw-workstation"
  }
}

# ------------------------------------------------------------------------------
# SSH Key Pair
# ------------------------------------------------------------------------------

resource "tls_private_key" "ngfw" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "ngfw" {
  key_name   = "${local.prefix}-ngfw"
  public_key = tls_private_key.ngfw.public_key_openssh

  tags = {
    Name = "${local.prefix}-ngfw"
  }
}

resource "aws_secretsmanager_secret" "ngfw_ssh_key" {
  name                    = "shifter/dev/ngfw/${var.team_name}/ssh-key"
  description             = "SSH private key for ${var.team_name} NGFW"
  recovery_window_in_days = 0

  tags = {
    Name = "${local.prefix}-ngfw-ssh-key"
  }
}

resource "aws_secretsmanager_secret_version" "ngfw_ssh_key" {
  secret_id     = aws_secretsmanager_secret.ngfw_ssh_key.id
  secret_string = tls_private_key.ngfw.private_key_pem
}

# ------------------------------------------------------------------------------
# Bootstrap (S3)
# ------------------------------------------------------------------------------

resource "aws_s3_object" "ngfw_init_cfg" {
  bucket       = var.ngfw_bootstrap_bucket
  key          = "bootstrap/ngfw/${var.team_name}/config/init-cfg.txt"
  content_type = "text/plain"

  content = <<-EOT
type=dhcp-client
hostname=ngfw-${var.team_name}
dns-primary=8.8.8.8
dns-secondary=8.8.4.4
panorama-server=cloud
vm-series-auto-registration-pin-id=${var.ngfw_scm_pin_id}
vm-series-auto-registration-pin-value=${var.ngfw_scm_pin_value}
plugin-op-commands-advance-routing=enable
EOT
}

resource "aws_s3_object" "ngfw_authcodes" {
  bucket       = var.ngfw_bootstrap_bucket
  key          = "bootstrap/ngfw/${var.team_name}/license/authcodes"
  content_type = "text/plain"
  content      = var.ngfw_authcode
}

resource "aws_s3_object" "ngfw_content_placeholder" {
  bucket  = var.ngfw_bootstrap_bucket
  key     = "bootstrap/ngfw/${var.team_name}/content/.keep"
  content = ""
}

resource "aws_s3_object" "ngfw_software_placeholder" {
  bucket  = var.ngfw_bootstrap_bucket
  key     = "bootstrap/ngfw/${var.team_name}/software/.keep"
  content = ""
}

# ------------------------------------------------------------------------------
# EC2 Instance
# ------------------------------------------------------------------------------

resource "aws_instance" "ngfw" {
  ami                  = var.ngfw_ami_id
  instance_type        = var.ngfw_instance_type
  key_name             = aws_key_pair.ngfw.key_name
  iam_instance_profile = var.ngfw_instance_profile

  user_data = "vmseries-bootstrap-aws-s3bucket=${var.ngfw_bootstrap_bucket}/bootstrap/ngfw/${var.team_name}"

  network_interface {
    device_index         = 0
    network_interface_id = aws_network_interface.ngfw_mgmt.id
  }

  network_interface {
    device_index         = 1
    network_interface_id = aws_network_interface.ngfw_untrust.id
  }

  network_interface {
    device_index         = 2
    network_interface_id = aws_network_interface.ngfw_server.id
  }

  network_interface {
    device_index         = 3
    network_interface_id = aws_network_interface.ngfw_workstation.id
  }

  tags = {
    Name = "${local.prefix}-ngfw"
  }

  depends_on = [
    aws_s3_object.ngfw_init_cfg,
    aws_s3_object.ngfw_authcodes,
    aws_secretsmanager_secret_version.ngfw_ssh_key,
  ]
}

# ------------------------------------------------------------------------------
# Route Tables - force server and endpoint traffic through NGFW
# ------------------------------------------------------------------------------

resource "aws_route_table" "server" {
  vpc_id = data.aws_vpc.default.id

  route {
    cidr_block           = "0.0.0.0/0"
    network_interface_id = aws_network_interface.ngfw_server.id
  }

  tags = {
    Name = "${local.prefix}-server"
  }
}

resource "aws_route_table_association" "server" {
  subnet_id      = aws_subnet.server.id
  route_table_id = aws_route_table.server.id
}

resource "aws_route_table" "endpoint" {
  vpc_id = data.aws_vpc.default.id

  route {
    cidr_block           = "0.0.0.0/0"
    network_interface_id = aws_network_interface.ngfw_workstation.id
  }

  tags = {
    Name = "${local.prefix}-endpoint"
  }
}

resource "aws_route_table_association" "endpoint" {
  subnet_id      = aws_subnet.endpoint.id
  route_table_id = aws_route_table.endpoint.id
}

# ------------------------------------------------------------------------------
# NGFW Management EIP
# ------------------------------------------------------------------------------

resource "aws_eip" "ngfw_mgmt" {
  domain = "vpc"

  tags = {
    Name = "${local.prefix}-ngfw-mgmt"
  }
}

resource "aws_eip_association" "ngfw_mgmt" {
  network_interface_id = aws_network_interface.ngfw_mgmt.id
  allocation_id        = aws_eip.ngfw_mgmt.id
}

# ------------------------------------------------------------------------------
# NGFW Untrust EIP
# ------------------------------------------------------------------------------

resource "aws_eip" "ngfw_untrust" {
  domain = "vpc"

  tags = {
    Name = "${local.prefix}-ngfw-untrust"
  }
}

resource "aws_eip_association" "ngfw_untrust" {
  network_interface_id = aws_network_interface.ngfw_untrust.id
  allocation_id        = aws_eip.ngfw_untrust.id
}

# ------------------------------------------------------------------------------
# Workstation (endpoint subnet)
# ------------------------------------------------------------------------------

resource "aws_security_group" "workstation" {
  name        = "${local.prefix}-workstation"
  description = "Workstation - RDP and SSM"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "${local.prefix}-workstation"
  }
}

resource "aws_vpc_security_group_ingress_rule" "workstation_rdp" {
  security_group_id = aws_security_group.workstation.id
  description       = "RDP from VPC"
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = data.aws_vpc.default.cidr_block
}

resource "aws_vpc_security_group_ingress_rule" "workstation_from_server" {
  security_group_id = aws_security_group.workstation.id
  description       = "All from server subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.server.cidr_block
}

resource "aws_vpc_security_group_ingress_rule" "workstation_from_endpoint" {
  security_group_id = aws_security_group.workstation.id
  description       = "All from endpoint subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.endpoint.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "workstation_all" {
  security_group_id = aws_security_group.workstation.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "workstation" {
  ami                    = var.workstation_ami_id
  instance_type          = var.workstation_instance_type
  subnet_id              = aws_subnet.endpoint.id
  vpc_security_group_ids = [aws_security_group.workstation.id]
  key_name               = var.key_name

  tags = {
    Name = "${local.prefix}-workstation"
  }
}

resource "aws_eip" "workstation" {
  domain = "vpc"

  tags = {
    Name = "${local.prefix}-workstation"
  }
}

resource "aws_eip_association" "workstation" {
  instance_id   = aws_instance.workstation.id
  allocation_id = aws_eip.workstation.id
}

# ------------------------------------------------------------------------------
# Windows Desktop (endpoint subnet)
# ------------------------------------------------------------------------------

resource "aws_security_group" "windows_desktop" {
  name        = "${local.prefix}-windows-desktop"
  description = "Windows Desktop SG"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "windows_desktop_rdp_rfc1918_10" {
  security_group_id = aws_security_group.windows_desktop.id
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "10.0.0.0/8"
}

resource "aws_vpc_security_group_ingress_rule" "windows_desktop_rdp_rfc1918_172" {
  security_group_id = aws_security_group.windows_desktop.id
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "172.16.0.0/12"
}

resource "aws_vpc_security_group_ingress_rule" "windows_desktop_rdp_rfc1918_192" {
  security_group_id = aws_security_group.windows_desktop.id
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "192.168.0.0/16"
}

resource "aws_vpc_security_group_ingress_rule" "windows_desktop_rdp_clement" {
  security_group_id = aws_security_group.windows_desktop.id
  description       = "Clement home IP to deploy lab"
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "24.48.68.139/32"
}

resource "aws_vpc_security_group_ingress_rule" "windows_desktop_from_server" {
  security_group_id = aws_security_group.windows_desktop.id
  description       = "All from server subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.server.cidr_block
}

resource "aws_vpc_security_group_ingress_rule" "windows_desktop_from_endpoint" {
  security_group_id = aws_security_group.windows_desktop.id
  description       = "All from endpoint subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.endpoint.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "windows_desktop_all" {
  security_group_id = aws_security_group.windows_desktop.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "windows_desktop" {
  ami                    = var.windows_desktop_ami_id
  instance_type          = var.windows_desktop_instance_type
  subnet_id              = aws_subnet.endpoint.id
  vpc_security_group_ids = [aws_security_group.windows_desktop.id]
  key_name               = "windowsDesktop"

  user_data = <<-EOF
    <powershell>
    Rename-Computer -NewName "WinDesktop${var.team_name}" -Force
    $username = "victimuser${lower(var.team_name)}"
    $password = ConvertTo-SecureString "Nature22" -AsPlainText -Force
    New-LocalUser -Name $username -Password $password -FullName $username -Description "Victim user"
    Add-LocalGroupMember -Group "Remote Desktop Users" -Member $username
    Restart-Computer -Force
    </powershell>
  EOF

  tags = {
    Name = "WinDesktop${var.team_name}"
  }

  lifecycle {
    ignore_changes = [user_data]
  }
}

resource "aws_eip" "windows_desktop" {
  domain = "vpc"

  tags = {
    Name = "${local.prefix}-windows-desktop"
  }
}

resource "aws_eip_association" "windows_desktop" {
  instance_id   = aws_instance.windows_desktop.id
  allocation_id = aws_eip.windows_desktop.id
}

# ------------------------------------------------------------------------------
# Windows Server (server subnet)
# ------------------------------------------------------------------------------

resource "aws_security_group" "windows_server" {
  name        = "${local.prefix}-windows-server"
  description = "Windows Server SG"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "windows_server_rdp_rfc1918_10" {
  security_group_id = aws_security_group.windows_server.id
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "10.0.0.0/8"
}

resource "aws_vpc_security_group_ingress_rule" "windows_server_rdp_rfc1918_172" {
  security_group_id = aws_security_group.windows_server.id
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "172.16.0.0/12"
}

resource "aws_vpc_security_group_ingress_rule" "windows_server_rdp_rfc1918_192" {
  security_group_id = aws_security_group.windows_server.id
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "192.168.0.0/16"
}

resource "aws_vpc_security_group_ingress_rule" "windows_server_rdp_clement" {
  security_group_id = aws_security_group.windows_server.id
  description       = "Clement home IP to deploy lab"
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "24.48.68.139/32"
}

resource "aws_vpc_security_group_ingress_rule" "windows_server_from_endpoint" {
  security_group_id = aws_security_group.windows_server.id
  description       = "All from endpoint subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.endpoint.cidr_block
}

resource "aws_vpc_security_group_ingress_rule" "windows_server_from_server" {
  security_group_id = aws_security_group.windows_server.id
  description       = "All from server subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.server.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "windows_server_all" {
  security_group_id = aws_security_group.windows_server.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "windows_server" {
  ami                    = var.windows_server_ami_id
  instance_type          = var.windows_server_instance_type
  subnet_id              = aws_subnet.server.id
  vpc_security_group_ids = [aws_security_group.windows_server.id]
  key_name               = "windowsServer"

  user_data = <<-EOF
    <powershell>
    Rename-Computer -NewName "WinServer${var.team_name}" -Force
    $username = "victimadmin${lower(var.team_name)}"
    $password = ConvertTo-SecureString "Welcome1!" -AsPlainText -Force
    New-LocalUser -Name $username -Password $password -FullName $username -Description "Victim admin"
    Add-LocalGroupMember -Group "Administrators" -Member $username
    Add-LocalGroupMember -Group "Remote Desktop Users" -Member $username
    Restart-Computer -Force
    </powershell>
  EOF

  tags = {
    Name = "WinServer${var.team_name}"
  }

  lifecycle {
    ignore_changes = [user_data]
  }
}

resource "aws_eip" "windows_server" {
  domain = "vpc"

  tags = {
    Name = "${local.prefix}-windows-server"
  }
}

resource "aws_eip_association" "windows_server" {
  instance_id   = aws_instance.windows_server.id
  allocation_id = aws_eip.windows_server.id
}

# ------------------------------------------------------------------------------
# ZTNA Connector (server subnet)
# ------------------------------------------------------------------------------

resource "aws_security_group" "ztna_connector" {
  name        = "${local.prefix}-ztna-connector-sg"
  description = "ZTNA Connector Allow Egress SG"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "${local.prefix}-ztna-connector"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ztna_from_endpoint" {
  security_group_id = aws_security_group.ztna_connector.id
  description       = "All from endpoint subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.endpoint.cidr_block
}

resource "aws_vpc_security_group_ingress_rule" "ztna_from_server" {
  security_group_id = aws_security_group.ztna_connector.id
  description       = "All from server subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.server.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "ztna_all" {
  security_group_id = aws_security_group.ztna_connector.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------------------------
# AI App (own subnet, direct IGW, bypasses NGFW)
# ------------------------------------------------------------------------------

resource "aws_subnet" "ai_app" {
  vpc_id            = data.aws_vpc.default.id
  cidr_block        = var.ai_app_subnet_cidr
  availability_zone = "us-east-2b"

  tags = {
    Name = "${local.prefix}-ai-app"
  }
}

resource "aws_security_group" "ai_app" {
  name        = "${local.prefix}-ai-app"
  description = "AI App - SSH and app port, allowlisted IPs"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "${local.prefix}-ai-app"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ai_app_ssh" {
  for_each = var.ai_app_allowed_cidrs

  security_group_id = aws_security_group.ai_app.id
  description       = each.key
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "ai_app_port" {
  for_each = var.ai_app_allowed_cidrs

  security_group_id = aws_security_group.ai_app.id
  description       = "${each.key} - app"
  from_port         = 8000
  to_port           = 8000
  ip_protocol       = "tcp"
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_egress_rule" "ai_app_all" {
  security_group_id = aws_security_group.ai_app.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "ai_app" {
  ami                    = var.ai_app_ami_id
  instance_type          = var.ai_app_instance_type
  subnet_id              = aws_subnet.ai_app.id
  vpc_security_group_ids = [aws_security_group.ai_app.id]

  tags = {
    Name = "${local.prefix}-AI-App"
  }
}

resource "aws_eip" "ai_app" {
  domain = "vpc"

  tags = {
    Name = "${local.prefix}-ai-app"
  }
}

resource "aws_eip_association" "ai_app" {
  instance_id   = aws_instance.ai_app.id
  allocation_id = aws_eip.ai_app.id
}
