locals {
  # First 8 characters of instance UUID for key pair naming
  instance_uuid_short = substr(var.instance_uuid, 0, 8)

  # Bootstrap S3 prefix
  bootstrap_prefix = "bootstrap/ngfw/${var.instance_uuid}"

  # Hostname for NGFW
  hostname = "ngfw-user-${var.user_id}"

  # Common tags applied to all resources
  common_tags = {
    "shifter:user_id"       = tostring(var.user_id)
    "shifter:environment"   = var.environment
    "shifter:request_uuid"  = var.request_uuid
    "shifter:instance_uuid" = var.instance_uuid
    "shifter:system"        = "shifter"
    "shifter:component"     = "ngfw"
    "ManagedBy"             = "terraform"
  }
}

# Management ENI
resource "aws_network_interface" "mgmt" {
  subnet_id       = var.subnet_id
  security_groups = [var.mgmt_security_group_id]
  description     = "NGFW management interface for user ${var.user_id}"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-mgmt"
  })
}

# Data ENI with source_dest_check disabled for traffic inspection
resource "aws_network_interface" "data" {
  subnet_id         = var.subnet_id
  security_groups   = [var.data_security_group_id]
  source_dest_check = false # Required for traffic inspection
  description       = "NGFW data interface for user ${var.user_id}"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-data"
  })
}

# RSA 4096 SSH key pair for post-boot configuration
resource "tls_private_key" "ssh" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

# EC2 Key Pair
resource "aws_key_pair" "ngfw" {
  key_name   = "ngfw-${local.instance_uuid_short}"
  public_key = tls_private_key.ssh.public_key_openssh

  tags = local.common_tags
}

# Secrets Manager secret for SSH private key
resource "aws_secretsmanager_secret" "ssh_key" {
  name                    = "shifter/${var.environment}/ngfw/${var.instance_uuid}/ssh-key"
  description             = "SSH private key for NGFW instance ${var.instance_uuid}"
  recovery_window_in_days = 0 # Immediate delete for cleanup
  kms_key_id              = var.secrets_kms_key_arn

  tags = local.common_tags
}

# Secret version with private key value
resource "aws_secretsmanager_secret_version" "ssh_key" {
  secret_id     = aws_secretsmanager_secret.ssh_key.id
  secret_string = tls_private_key.ssh.private_key_pem
}

# Bootstrap init-cfg.txt
resource "aws_s3_object" "init_cfg" {
  bucket       = var.bootstrap_bucket
  key          = "${local.bootstrap_prefix}/config/init-cfg.txt"
  content_type = "text/plain"

  content = <<-EOT
type=dhcp-client
hostname=${local.hostname}
dns-primary=8.8.8.8
dns-secondary=8.8.4.4
panorama-server=cloud
vm-series-auto-registration-pin-id=${var.scm_pin_id}
vm-series-auto-registration-pin-value=${var.scm_pin_value}
%{if var.scm_folder_name != ""}dgname=${var.scm_folder_name}
%{endif}
EOT
}

# License authcodes file
resource "aws_s3_object" "authcodes" {
  bucket       = var.bootstrap_bucket
  key          = "${local.bootstrap_prefix}/license/authcodes"
  content_type = "text/plain"
  content      = var.authcode
}

# Empty content/.keep placeholder (required by bootstrap)
resource "aws_s3_object" "content_placeholder" {
  bucket  = var.bootstrap_bucket
  key     = "${local.bootstrap_prefix}/content/.keep"
  content = ""
}

# Empty software/.keep placeholder (required by bootstrap)
resource "aws_s3_object" "software_placeholder" {
  bucket  = var.bootstrap_bucket
  key     = "${local.bootstrap_prefix}/software/.keep"
  content = ""
}

# VM-Series NGFW EC2 Instance
resource "aws_instance" "ngfw" {
  ami                  = var.ami_id
  instance_type        = var.instance_type
  key_name             = aws_key_pair.ngfw.key_name
  iam_instance_profile = var.instance_profile_name

  # User data for VM-Series bootstrap
  user_data = "vmseries-bootstrap-aws-s3bucket=${var.bootstrap_bucket}/${local.bootstrap_prefix}"

  # Attach ENIs
  network_interface {
    device_index         = 0
    network_interface_id = aws_network_interface.mgmt.id
  }

  network_interface {
    device_index         = 1
    network_interface_id = aws_network_interface.data.id
  }

  tags = merge(local.common_tags, {
    Name = var.name_prefix
  })

  depends_on = [
    aws_network_interface.mgmt,
    aws_network_interface.data,
    aws_s3_object.init_cfg,
    aws_s3_object.authcodes,
    aws_secretsmanager_secret_version.ssh_key,
  ]
}
