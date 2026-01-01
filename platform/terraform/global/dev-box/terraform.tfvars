aws_region        = "us-east-2"
instance_type     = "t3.xlarge"
root_volume_size  = 100
allowed_rdp_cidrs = []

# Portal VPC integration (optional - for direct DB access)
# Set these values to deploy in portal VPC instead of default VPC
# Get values from: AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform -chdir=../../../environments/dev/portal output
use_portal_vpc              = false
portal_vpc_id               = ""
portal_subnet_id            = ""
portal_db_security_group_id = ""
