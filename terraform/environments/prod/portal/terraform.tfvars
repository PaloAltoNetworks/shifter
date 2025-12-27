# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

environment        = "prod"
aws_region         = "us-east-2"
log_retention_days = 90

tags = {
  Project     = "shifter"
  Environment = "prod"
  ManagedBy   = "terraform"
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

vpc_cidr           = "10.0.0.0/16"
az_count           = 2
enable_nat_gateway = true

# ------------------------------------------------------------------------------
# RDS
# ------------------------------------------------------------------------------

db_name                  = "shifter"
db_username              = "shifter_admin"
db_engine_version        = "16"
db_instance_class        = "db.t3.large"
db_allocated_storage     = 20
db_max_allocated_storage = 100
db_multi_az              = false
db_backup_retention_days = 7
db_deletion_protection   = true
db_skip_final_snapshot   = false

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

ec2_instance_type    = "t3.xlarge"
ec2_root_volume_size = 50

# ------------------------------------------------------------------------------
# ALB
# ------------------------------------------------------------------------------

domain_name       = "shifter.keplerops.com"
app_port          = 8000
health_check_path = "/health"

# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

cognito_domain_prefix = "shifter-portal"
allowed_email_domains = ["paloaltonetworks.com"]
allowed_emails        = []

# ------------------------------------------------------------------------------
# S3
# ------------------------------------------------------------------------------

user_storage_bucket = "shifter-user-storage-7a3f9c2e"

# ------------------------------------------------------------------------------
# Provisioner
# ------------------------------------------------------------------------------

# Ubuntu 22.04 victim with Claude Code configured for Bedrock, Apache, MySQL, Docker, PHP, Samba, FTP
victim_ami_id        = "ami-0bf29d084387fdafa"
victim_instance_type = "t3.medium"

# Kali Linux 2025.3.0 with SSM, kali-linux-headless, Claude Code configured for Bedrock
kali_ami_id        = "ami-0a88afb7ba55dc486"
kali_instance_type = "t3.medium"

# ------------------------------------------------------------------------------
# Autoscaling
# ------------------------------------------------------------------------------

# Disabled for prod - single instance mode until validated in dev
enable_autoscaling   = false
asg_min_size         = 2
asg_max_size         = 5
asg_desired_capacity = 2
scale_up_threshold   = 70
scale_down_threshold = 30

# ------------------------------------------------------------------------------
# Redis
# ------------------------------------------------------------------------------

redis_node_type      = "cache.t3.micro"
redis_engine_version = "7.1"

# ------------------------------------------------------------------------------
# Log Aggregation
# ------------------------------------------------------------------------------

# Disabled for initial deployment - enable when ready for XDR integration
enable_log_aggregation = false

# ------------------------------------------------------------------------------
# Phase 5: Additional Log Sources
# ------------------------------------------------------------------------------

enable_alb_access_logs = true
enable_vpc_flow_logs   = true
enable_rds_log_exports = true
enable_waf_logging     = true

# ------------------------------------------------------------------------------
# Pulumi Provisioner
# ------------------------------------------------------------------------------

pulumi_container_tag = "latest"

# Windows Server 2022 victim with XAMPP, Claude Code (system path), Python, Git, IIS, FTP, OpenSSH - Sysprepped v3
windows_ami_id = "ami-02138efa7887f3218"

# Windows Server 2022 DC - internal.shifter domain, DC01, DNS forwarder to 169.254.169.253, OpenSSH
# Admin password: Sh1fterDC2024! (set before domain promotion, matches dc_domain_password)
dc_ami_id      = "ami-00b60259bc2f34052"
dc_domain_name = "internal.shifter"
# nosec B105 - Ephemeral isolated range, not a production credential
dc_domain_password = "Sh1fterDC2024!" # pragma: allowlist secret

# ------------------------------------------------------------------------------
# CI Testing (not used by Terraform, extracted by quality.yml workflow)
# ------------------------------------------------------------------------------

django_secret_key_ci = "ci-test-key-prod-not-for-production"
