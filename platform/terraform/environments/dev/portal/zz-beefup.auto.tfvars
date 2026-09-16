# Event beef-up: Toronto AI Security Workshop CTF (2026-07-21), ~30 concurrent participants.
#
# These override the sizing rendered into local.auto.tfvars from the TF_VARS_DEV_PORTAL
# deploy secret. Terraform loads *.auto.tfvars in lexical order, so "zz-" wins over
# "local.auto.tfvars". Kept as a committed file (not the secret) so it is reviewable and
# survives future applies. Post-event: fold into the deploy secret or delete this file.

# --- Portal: 5 larger instances; worker pool sized for t3.xlarge (4 vCPU) ---
ec2_instance_type    = "t3.xlarge"
asg_min_size         = 5
asg_desired_capacity = 5
asg_max_size         = 8
portal_web_workers   = 4

# --- Portal RDS ---
db_instance_class = "db.m5.xlarge"

# --- Redis ---
redis_node_type = "cache.m6g.large"

# --- Guacamole: scale the guacd proxy tier for concurrent RDP/SSH sessions ---
guacamole_enable_autoscaling       = true
guacamole_autoscaling_min_capacity = 2
guacamole_autoscaling_max_capacity = 6
guacd_cpu                          = 2048
guacd_memory                       = 4096
guacamole_client_cpu               = 2048
guacamole_client_memory            = 4096
guacamole_db_instance_class        = "db.t3.medium"
