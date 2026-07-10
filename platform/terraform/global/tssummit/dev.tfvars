ami_id    = "ami-08f28cdc690a5bc15"
subnet_id = "subnet-xxxxxxxxxxxxxxxxx" # public subnet in the target account

ssh_allowed_cidrs = {
  "SSH access - user 1" = "142.181.57.73/32"
  "SSH access - user 2" = "124.238.149.39/32"
}

ctfd_ami_id = "ami-0b0b78dcacbab728f"

# NGFW
ngfw_ami_id           = "ami-065e27477b191614c" # PAN-OS 11.2.8 (same as ranges)
ngfw_bootstrap_bucket = "shifter-dev-user-storage-xxxxxxxx"
ngfw_server_subnet_id = "subnet-xxxxxxxxxxxxxxxxx"

# Workstation
workstation_ami_id = "ami-058f0cf1cc0bc26b3"

# Windows Instances
windows_server_ami_id  = "ami-058f0cf1cc0bc26b3"
windows_desktop_ami_id = "ami-0607d4beefbf087ae"
