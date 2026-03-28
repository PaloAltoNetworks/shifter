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

resource "aws_vpc_security_group_egress_rule" "ngfw_mgmt_all" {
  security_group_id = aws_security_group.ngfw_mgmt.id
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

resource "aws_secretsmanager_secret" "ngfw_ssh_key" {
  name                    = "shifter/dev/ngfw/playground/ssh-key"
  description             = "SSH private key for playground NGFW"
  recovery_window_in_days = 0

  tags = {
    Name = "tssummit-ngfw-ssh-key"
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
  key          = "bootstrap/ngfw/playground/config/init-cfg.txt"
  content_type = "text/plain"

  content = <<-EOT
type=dhcp-client
hostname=ngfw-playground
dns-primary=8.8.8.8
dns-secondary=8.8.4.4
panorama-server=cloud
vm-series-auto-registration-pin-id=${var.ngfw_scm_pin_id}
vm-series-auto-registration-pin-value=${var.ngfw_scm_pin_value}
EOT
}

resource "aws_s3_object" "ngfw_authcodes" {
  bucket       = var.ngfw_bootstrap_bucket
  key          = "bootstrap/ngfw/playground/license/authcodes"
  content_type = "text/plain"
  content      = var.ngfw_authcode
}

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
    aws_s3_object.ngfw_init_cfg,
    aws_s3_object.ngfw_authcodes,
    aws_secretsmanager_secret_version.ngfw_ssh_key,
  ]
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
    Name = "tssummit-workstation"
  }
}
