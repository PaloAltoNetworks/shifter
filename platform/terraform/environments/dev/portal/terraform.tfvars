# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

environment        = "dev"
aws_region         = "us-east-2"
log_retention_days = 30

tags = {
  Project     = "shifter"
  Environment = "dev"
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
db_instance_class        = "db.t3.micro"
db_allocated_storage     = 20
db_max_allocated_storage = 50
db_multi_az              = false
db_backup_retention_days = 1
db_deletion_protection   = false
db_skip_final_snapshot   = true

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

ec2_instance_type    = "t3.large"
ec2_root_volume_size = 30

# ------------------------------------------------------------------------------
# ALB
# ------------------------------------------------------------------------------

# TODO: Update with your dev domain
domain_name       = "dev.shifter.keplerops.com"
app_port          = 8000
health_check_path = "/health"

# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

cognito_domain_prefix = "shifter-dev-portal"
allowed_email_domains = ["paloaltonetworks.com"]
allowed_emails        = []

# ------------------------------------------------------------------------------
# S3
# ------------------------------------------------------------------------------

user_storage_bucket = "shifter-dev-user-storage-e3462f0c"

# ------------------------------------------------------------------------------
# Provisioner
# ------------------------------------------------------------------------------

# AMI IDs are now managed via SSM Parameter Store (/shifter/ami/*)
# See shifter/packer/ for AMI build configuration

victim_instance_type = "t3.medium"
kali_instance_type   = "t3.medium"

# ------------------------------------------------------------------------------
# Autoscaling
# ------------------------------------------------------------------------------

# Disabled for dev - single instance mode
enable_autoscaling   = true
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

# Windows/DC AMIs also managed via SSM Parameter Store

dc_domain_name = "internal.shifter"
# nosec B105 - Ephemeral isolated range, not a production credential
dc_domain_password = "Sh1fterDC2024!" # pragma: allowlist secret

# ------------------------------------------------------------------------------
# CI Testing (not used by Terraform, extracted by quality.yml workflow)
# ------------------------------------------------------------------------------

django_secret_key_ci = "ci-test-key-dev-not-for-production"
