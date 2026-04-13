variable "range_vpc_id" {
  description = "Dev range VPC to attach the POLARIS test subnet to."
  type        = string
  default     = "vpc-094a142a8c363541c"
}

variable "polaris_subnet_cidr" {
  description = "/28 block inside the range VPC for the POLARIS test subnet. Keep well clear of the /28 allocator range (starts from 10.1.2.0/28)."
  type        = string
  default     = "10.1.100.0/28"
}

variable "availability_zone" {
  description = "AZ for the POLARIS test subnet (matches existing range infrastructure)."
  type        = string
  default     = "us-east-2a"
}

variable "nat_gateway_id" {
  description = "Existing dev range NAT gateway. Used to give the POLARIS bake subnet direct NAT egress (bypass the domain-filtered Network Firewall so docker hub / apt repos work during bake)."
  type        = string
  default     = "nat-0728570128ae96bfc"
}

variable "portal_vpc_cidr" {
  description = "Portal VPC CIDR reachable via VPC peering (so the Shifter portal terminal UI + Guacamole can reach the POLARIS kali box)."
  type        = string
  default     = "10.0.0.0/16"
}

variable "portal_peering_id" {
  description = "VPC peering connection from the range VPC to the portal VPC."
  type        = string
  default     = "pcx-0060068d711a534f4"
}

variable "ubuntu_ami_id" {
  description = "Ubuntu base AMI (each host just runs Docker + the polaris docker-compose stack)."
  type        = string
  default     = "ami-01c08a65f35fbc399" # shifter-ubuntu-1773805749
}

variable "instance_type" {
  description = "EC2 instance type. Kali GUI + 17 compose containers need plenty of headroom."
  type        = string
  default     = "m5.2xlarge"
}

variable "polaris_instance_private_ip" {
  description = "Pinned private IP inside the POLARIS subnet."
  type        = string
  default     = "10.1.100.10"
}

variable "build_tarball_s3_uri" {
  description = "S3 URI of the polaris build tarball uploaded by the operator."
  type        = string
  default     = "s3://shifter-polaris-bake-158151907940/polaris/build-v1.tar.gz"
}

variable "build_tarball_bucket" {
  description = "S3 bucket holding the polaris build tarball (used to grant IAM read to the instance)."
  type        = string
  default     = "shifter-polaris-bake-158151907940"
}

variable "ssh_public_key_ssm_name" {
  description = "SSM parameter name that holds the operator SSH public key (baked into kali authorized_keys). Leave empty to skip."
  type        = string
  default     = ""
}

variable "kali_authorized_key" {
  description = "OpenSSH public key the Shifter portal's Terminal UI uses as kali — injected into a14-kali's /home/kali/.ssh/authorized_keys by user_data. Must match the private key stored in the Secrets Manager entry register_range.py references. Plain pubkey is fine here (not secret)."
  type        = string
  default     = ""
}

variable "a2_dc_ami_id" {
  description = "Windows Server 2022 Full Base from Amazon. The shifter-dc-prebaked AMI is sysprep'd in a way that raced with first-boot SSM + user_data in testing — stock base AMI boots cleanly, then we install AD-Domain-Services via SSM RunCommand after the agent reports online."
  type        = string
  default     = "ami-08c41c6041bf318eb" # Windows_Server-2022-English-Full-Base-2026.03.11
}

variable "a2_instance_type" {
  description = "EC2 instance type for the A2 Windows DC. t3.large (2 vCPU, 8 GB RAM) is the smallest that keeps AD DS + DNS responsive under Kerberoast + secretsdump load."
  type        = string
  default     = "t3.large"
}

variable "a2_private_ip" {
  description = "Pinned private IP for the A2 Windows DC inside the polaris /28 subnet. Matches the dns zone file for dc01.boreas.local."
  type        = string
  default     = "10.1.100.11"
}

variable "a2_administrator_password" {
  description = "Plaintext password set on the Windows Administrator account at first boot, also used by the walkthrough smoketest + Shifter portal RDP connection (default matches shifter/shifter_platform/engine/services.py::get_rdp_connection_info for os_type=windows)."
  type        = string
  default     = "CortexSavesTheDay!"
  sensitive   = true
}

variable "a2_dsrm_password" {
  description = "Directory Services Restore Mode password. Only ever used during Install-ADDSForest; cannot be discovered from outside the box so the value is intentionally trivial."
  type        = string
  default     = "DsrmR3store!2026"
  sensitive   = true
}
