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

# AMI IDs are now managed via SSM Parameter Store (/shifter/ami/*)
# See shifter/packer/ for AMI build configuration

victim_instance_type = "t3.medium"
kali_instance_type   = "t3.medium"

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

redis_node_type          = "cache.t3.micro"
redis_engine_version     = "7.1"
redis_enable_replication = true

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
# Guacamole
# ------------------------------------------------------------------------------

guacd_image_tag                = "1.5.5"
guacamole_client_image_tag     = "1.5.5"
guacd_cpu                      = 512
guacd_memory                   = 1024
guacamole_client_cpu           = 512
guacamole_client_memory        = 1024
guacd_desired_count            = 2
guacamole_client_desired_count = 2

# Database (production settings)
guacamole_db_instance_class        = "db.t3.small"
guacamole_db_allocated_storage     = 20
guacamole_db_max_allocated_storage = 100
guacamole_db_engine_version        = "16"
guacamole_db_multi_az              = true
guacamole_db_backup_retention_days = 14
guacamole_db_deletion_protection   = true
guacamole_db_skip_final_snapshot   = false

# Autoscaling (disabled for initial testing)
guacamole_enable_autoscaling       = false
guacamole_autoscaling_min_capacity = 2
guacamole_autoscaling_max_capacity = 8
guacamole_autoscaling_cpu_target   = 70

# Secrets
guacamole_secrets_recovery_window_days = 7

# ------------------------------------------------------------------------------
# CI Testing (not used by Terraform, extracted by quality.yml workflow)
# ------------------------------------------------------------------------------

django_secret_key_ci = "ci-test-key-prod-not-for-production"
