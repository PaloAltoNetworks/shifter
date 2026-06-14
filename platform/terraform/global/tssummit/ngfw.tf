# ------------------------------------------------------------------------------
# VM-Series NGFW - Playground
# ------------------------------------------------------------------------------
# Multi-interface firewall with ENIs in untrust, management, server, and
# workstation subnets. Bootstrap registers with Strata Cloud Manager.
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# Data Sources
# ------------------------------------------------------------------------------

data "aws_subnet" "dev_server" {
  id = var.ngfw_server_subnet_id
}

# Default route table for VPC endpoint association
data "aws_route_table" "default" {
  vpc_id = data.aws_vpc.default.id

  filter {
    name   = "association.main"
    values = ["true"]
  }
}

# S3 gateway endpoint - required for NGFW bootstrap (management ENI has no public IP)
resource "aws_vpc_endpoint" "s3" {
  vpc_id          = data.aws_vpc.default.id
  service_name    = "com.amazonaws.us-east-2.s3"
  route_table_ids = [data.aws_route_table.default.id]

  tags = {
    Name = "tssummit-s3-endpoint"
  }
}

# ------------------------------------------------------------------------------
# Subnets (us-east-2b, replacing former us-east-2a subnets)
# ------------------------------------------------------------------------------

resource "aws_subnet" "untrust" {
  vpc_id            = data.aws_vpc.default.id
  cidr_block        = "172.31.48.0/24"
  availability_zone = "us-east-2b"

  tags = {
    Name = "untrust"
  }
}

resource "aws_subnet" "management" {
  vpc_id                  = data.aws_vpc.default.id
  cidr_block              = "172.31.49.0/24"
  availability_zone       = "us-east-2b"
  map_public_ip_on_launch = true

  tags = {
    Name = "management"
  }
}

resource "aws_subnet" "endpoint" {
  vpc_id            = data.aws_vpc.default.id
  cidr_block        = "172.31.50.0/24"
  availability_zone = "us-east-2b"

  tags = {
    Name = "endpoint"
  }
}

# ------------------------------------------------------------------------------
# Security Groups
# ------------------------------------------------------------------------------

resource "aws_security_group" "ngfw_mgmt" {
  name        = "tssummit-ngfw-mgmt"
  description = "NGFW management - SSH and HTTPS"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "tssummit-ngfw-mgmt"
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

resource "aws_vpc_security_group_ingress_rule" "ngfw_mgmt_https" {
  security_group_id = aws_security_group.ngfw_mgmt.id
  description       = "HTTPS from VPC"
  from_port         = 443
  to_port           = 443
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
  description       = "NGFW management interface egress (all protocols)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "ngfw_data" {
  name        = "tssummit-ngfw-data"
  description = "NGFW data interfaces - all traffic"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "tssummit-ngfw-data"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ngfw_data_all" {
  security_group_id = aws_security_group.ngfw_data.id
  description       = "NGFW data interfaces ingress (all protocols; NGFW enforces policy)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "ngfw_data_all" {
  security_group_id = aws_security_group.ngfw_data.id
  description       = "NGFW data interfaces egress (all protocols; NGFW enforces policy)"
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
    Name = "tssummit-ngfw-mgmt"
  }
}

resource "aws_network_interface" "ngfw_untrust" {
  subnet_id         = aws_subnet.untrust.id
  security_groups   = [aws_security_group.ngfw_data.id]
  source_dest_check = false
  description       = "NGFW untrust interface"

  tags = {
    Name = "tssummit-ngfw-untrust"
  }
}

resource "aws_network_interface" "ngfw_server" {
  subnet_id         = var.ngfw_server_subnet_id
  security_groups   = [aws_security_group.ngfw_data.id]
  source_dest_check = false
  description       = "NGFW server interface"

  tags = {
    Name = "tssummit-ngfw-server"
  }
}

resource "aws_network_interface" "ngfw_workstation" {
  subnet_id         = aws_subnet.endpoint.id
  security_groups   = [aws_security_group.ngfw_data.id]
  source_dest_check = false
  description       = "NGFW workstation interface"

  tags = {
    Name = "tssummit-ngfw-workstation"
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
  key_name   = "tssummit-ngfw"
  public_key = tls_private_key.ngfw.public_key_openssh

  tags = {
    Name = "tssummit-ngfw"
  }
}

data "aws_caller_identity" "ngfw_ssh_kms" {}

resource "aws_kms_key" "ngfw_ssh_key" {
  description             = "CMK for tssummit playground NGFW SSH-key secret (CKV_AWS_149)"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EnableRootAccountAdmin"
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.ngfw_ssh_kms.account_id}:root" }
      Action    = "kms:*"
      Resource  = "*"
    }]
  })

  tags = {
    Name = "tssummit-ngfw-ssh-key-cmk"
  }
}

resource "aws_kms_alias" "ngfw_ssh_key" {
  name          = "alias/tssummit-ngfw-ssh-key"
  target_key_id = aws_kms_key.ngfw_ssh_key.key_id
}

resource "aws_secretsmanager_secret" "ngfw_ssh_key" {
  name                    = "shifter/dev/ngfw/playground/ssh-key"
  description             = "SSH private key for playground NGFW"
  recovery_window_in_days = 0
  kms_key_id              = aws_kms_key.ngfw_ssh_key.arn

  tags = {
    Name = "tssummit-ngfw-ssh-key"
  }
}

resource "aws_secretsmanager_secret_version" "ngfw_ssh_key" {
  secret_id     = aws_secretsmanager_secret.ngfw_ssh_key.id
  secret_string = tls_private_key.ngfw.private_key_pem
}

# Secret-bearing NGFW bootstrap files under config/ and license/ are staged
# outside Terraform so their contents do not enter source, plan, or state.
resource "aws_s3_object" "ngfw_content_placeholder" {
  bucket  = var.ngfw_bootstrap_bucket
  key     = "bootstrap/ngfw/playground/content/.keep"
  content = ""
}

resource "aws_s3_object" "ngfw_software_placeholder" {
  bucket  = var.ngfw_bootstrap_bucket
  key     = "bootstrap/ngfw/playground/software/.keep"
  content = ""
}

# ------------------------------------------------------------------------------
# EC2 Instance
# ------------------------------------------------------------------------------

resource "aws_instance" "ngfw" {
  monitoring    = true
  ebs_optimized = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }
  root_block_device {
    encrypted = true
  }
  ami                  = var.ngfw_ami_id
  instance_type        = var.ngfw_instance_type
  key_name             = aws_key_pair.ngfw.key_name
  iam_instance_profile = var.ngfw_instance_profile

  user_data = "vmseries-bootstrap-aws-s3bucket=${var.ngfw_bootstrap_bucket}/bootstrap/ngfw/playground"

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
    Name = "tssummit-ngfw"
  }

  depends_on = [
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
    Name = "tssummit-server"
  }
}

resource "aws_route_table_association" "server" {
  subnet_id      = var.ngfw_server_subnet_id
  route_table_id = aws_route_table.server.id
}

resource "aws_route_table" "endpoint" {
  vpc_id = data.aws_vpc.default.id

  route {
    cidr_block           = "0.0.0.0/0"
    network_interface_id = aws_network_interface.ngfw_workstation.id
  }

  tags = {
    Name = "tssummit-endpoint"
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
    Name = "tssummit-ngfw-mgmt"
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
    Name = "tssummit-ngfw-untrust"
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
  name        = "tssummit-workstation"
  description = "Workstation - RDP and SSM"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "tssummit-workstation"
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
  cidr_ipv4         = data.aws_subnet.dev_server.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "workstation_all" {
  security_group_id = aws_security_group.workstation.id
  description       = "Workstation egress (all protocols)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "workstation" {
  monitoring    = true
  ebs_optimized = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }
  root_block_device {
    encrypted = true
  }
  ami                    = var.workstation_ami_id
  instance_type          = var.workstation_instance_type
  subnet_id              = aws_subnet.endpoint.id
  vpc_security_group_ids = [aws_security_group.workstation.id]
  key_name               = var.key_name

  tags = {
    Name = "tssummit-workstation"
  }
}

# ------------------------------------------------------------------------------
# Windows Desktop (endpoint subnet)
# ------------------------------------------------------------------------------

resource "aws_security_group" "windows_desktop" {
  name        = "windowsDesktop"
  description = "Windows Desktop SG"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "windows_desktop_rdp_rfc1918_10" {
  security_group_id = aws_security_group.windows_desktop.id
  description       = "RDP from RFC1918 10.0.0.0/8 (workshop lateral movement scenario)"
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "10.0.0.0/8"
}

resource "aws_vpc_security_group_ingress_rule" "windows_desktop_rdp_rfc1918_172" {
  security_group_id = aws_security_group.windows_desktop.id
  description       = "RDP from RFC1918 172.16.0.0/12 (workshop lateral movement scenario)"
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "172.16.0.0/12"
}

resource "aws_vpc_security_group_ingress_rule" "windows_desktop_rdp_rfc1918_192" {
  security_group_id = aws_security_group.windows_desktop.id
  description       = "RDP from RFC1918 192.168.0.0/16 (workshop lateral movement scenario)"
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
  cidr_ipv4         = data.aws_subnet.dev_server.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "windows_desktop_all" {
  security_group_id = aws_security_group.windows_desktop.id
  description       = "Windows desktop egress (all protocols)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "windows_desktop" {
  monitoring    = true
  ebs_optimized = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }
  root_block_device {
    encrypted = true
  }
  ami                    = var.windows_desktop_ami_id
  instance_type          = var.windows_desktop_instance_type
  subnet_id              = aws_subnet.endpoint.id
  vpc_security_group_ids = [aws_security_group.windows_desktop.id]
  key_name               = "windowsDesktop"

  tags = {
    Name = "WinDesktopTeam1"
  }

  lifecycle {
    ignore_changes = [user_data]
  }
}

# ------------------------------------------------------------------------------
# Windows Server (server subnet)
# ------------------------------------------------------------------------------

resource "aws_security_group" "windows_server" {
  name        = "windowsServer_xpanse_ar_053"
  description = "copied from rule windowsServer by Xpanse Active Response module"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "windows_server_rdp_rfc1918_10" {
  security_group_id = aws_security_group.windows_server.id
  description       = "RDP from RFC1918 10.0.0.0/8 (workshop lateral movement scenario)"
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "10.0.0.0/8"
}

resource "aws_vpc_security_group_ingress_rule" "windows_server_rdp_rfc1918_172" {
  security_group_id = aws_security_group.windows_server.id
  description       = "RDP from RFC1918 172.16.0.0/12 (workshop lateral movement scenario)"
  from_port         = 3389
  to_port           = 3389
  ip_protocol       = "tcp"
  cidr_ipv4         = "172.16.0.0/12"
}

resource "aws_vpc_security_group_ingress_rule" "windows_server_rdp_rfc1918_192" {
  security_group_id = aws_security_group.windows_server.id
  description       = "RDP from RFC1918 192.168.0.0/16 (workshop lateral movement scenario)"
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

resource "aws_vpc_security_group_egress_rule" "windows_server_all" {
  security_group_id = aws_security_group.windows_server.id
  description       = "Windows server egress (all protocols)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "windows_server" {
  monitoring    = true
  ebs_optimized = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }
  root_block_device {
    encrypted = true
  }
  ami                    = var.windows_server_ami_id
  instance_type          = var.windows_server_instance_type
  subnet_id              = var.ngfw_server_subnet_id
  vpc_security_group_ids = [aws_security_group.windows_server.id]
  key_name               = "windowsServer"

  tags = {
    Name = "WinServerTeam1"
  }

  lifecycle {
    ignore_changes = [user_data]
  }
}

# ------------------------------------------------------------------------------
# ZTNA Connector (server subnet)
# ------------------------------------------------------------------------------

resource "aws_security_group" "ztna_connector" {
  name        = "tssummit-ztna-connector-security-group"
  description = "ZTNA Connector Allow Egress SG"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "tssummit-ztna-connector Public Security Group"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ztna_from_endpoint" {
  security_group_id = aws_security_group.ztna_connector.id
  description       = "All from endpoint subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.endpoint.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "ztna_all" {
  security_group_id = aws_security_group.ztna_connector.id
  description       = "ZTNA connector egress (all protocols)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------------------------
# Webserver Sensitive Data / Phishing (server subnet)
# ------------------------------------------------------------------------------

resource "aws_security_group" "webserver_sensitivedata" {
  name        = "tssummit-webserver-sensitivedata"
  description = "tssummit-webserver-sensitivedata"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "sensitivedata_http" {
  security_group_id = aws_security_group.webserver_sensitivedata.id
  description       = "Allow port 80 from anywhere"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "sensitivedata_tcp_from_ztna" {
  security_group_id            = aws_security_group.webserver_sensitivedata.id
  description                  = "TCP From ZTNA"
  from_port                    = 0
  to_port                      = 65535
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.ztna_connector.id
}

resource "aws_vpc_security_group_ingress_rule" "sensitivedata_ssh" {
  security_group_id = aws_security_group.webserver_sensitivedata.id
  description       = "SSH from operator IP (workshop bootstrap)"
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
  cidr_ipv4         = "99.232.4.249/32"
}

resource "aws_vpc_security_group_ingress_rule" "sensitivedata_from_endpoint" {
  security_group_id = aws_security_group.webserver_sensitivedata.id
  description       = "All from endpoint subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.endpoint.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "sensitivedata_all" {
  security_group_id = aws_security_group.webserver_sensitivedata.id
  description       = "Sensitive-data webserver egress (all protocols)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}
