team_name = "Team7"

# Subnet CIDRs
server_subnet_cidr     = "172.31.76.0/24"
untrust_subnet_cidr    = "172.31.77.0/24"
management_subnet_cidr = "172.31.78.0/24"
endpoint_subnet_cidr   = "172.31.79.0/24"

ssh_allowed_cidrs = {
  "SSH access - user 1" = "142.181.57.73/32"
  "SSH access - user 2" = "124.238.149.39/32"
}

# NGFW
ngfw_ami_id           = "ami-065e27477b191614c" # PAN-OS 11.2.8
ngfw_bootstrap_bucket = "shifter-dev-user-storage-e3462f0c"
ngfw_authcode         = "D6153905"
ngfw_scm_pin_id       = "cb5d90f7-5c19-41e2-a92a-a13b4e8dc60c"
ngfw_scm_pin_value    = "387db972a60d4f89a4251db70bf06c58"

# Instances
webserver_ami_id       = "ami-07062e2a343acc423"
workstation_ami_id     = "ami-058f0cf1cc0bc26b3"
windows_server_ami_id  = "ami-058f0cf1cc0bc26b3"
windows_desktop_ami_id = "ami-0607d4beefbf087ae"

# AI App
ai_app_subnet_cidr = "172.31.105.0/28"
ai_app_ami_id      = "ami-0532dbf55f276647e"
