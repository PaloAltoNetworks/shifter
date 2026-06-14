team_name = "Team5"

# Subnet CIDRs
server_subnet_cidr     = "172.31.68.0/24"
untrust_subnet_cidr    = "172.31.69.0/24"
management_subnet_cidr = "172.31.70.0/24"
endpoint_subnet_cidr   = "172.31.71.0/24"

ssh_allowed_cidrs = {
  "SSH access - user 1" = "142.181.57.73/32"
  "SSH access - user 2" = "124.238.149.39/32"
}

# NGFW
ngfw_ami_id           = "ami-065e27477b191614c" # PAN-OS 11.2.8
ngfw_bootstrap_bucket = "shifter-dev-user-storage-e3462f0c"

# Instances
webserver_ami_id       = "ami-0a7c3c31d7446e13d"
workstation_ami_id     = "ami-0687d1d5a48fca4df"
windows_server_ami_id  = "ami-0687d1d5a48fca4df"
windows_desktop_ami_id = "ami-0607d4beefbf087ae"

# AI App
ai_app_subnet_cidr = "172.31.103.0/28"
ai_app_ami_id      = "ami-0532dbf55f276647e"
