variable "aws_profile" {
  description = "AWS CLI/shared-config profile for Terraform. Set to aws-dev for the no-SSO aws-dev account; leave null to use the ambient AWS credential chain."
  type        = string
  default     = null
  nullable    = true
}

variable "aws_region" {
  description = "AWS region for the Polaris standalone range."
  type        = string
  default     = "us-east-2"
}

variable "name_prefix" {
  description = "Prefix for Terraform-created Polaris AWS resources."
  type        = string
  default     = "polaris"
}

variable "deployment_purpose" {
  description = "Default AWS tag Purpose value."
  type        = string
  default     = "standalone-range"
}

variable "range_indices" {
  description = "String indices of the POLARIS ranges to provision. Each index gets its own /28 subnet + polaris VM + A2 DC. Default is a single range so a plain `terraform apply` still produces one working range."
  type        = list(string)
  default     = ["0"]

  validation {
    condition     = length(var.range_indices) == length(toset(var.range_indices))
    error_message = "range_indices must be unique."
  }
}

variable "polaris_cidr_block" {
  description = "Base CIDR allocated to POLARIS. Carved into /28 subnets via cidrsubnet(block, 4, i), so a /24 yields 16 ranges. Leave empty to derive a high /24 from the target VPC CIDR, e.g. 172.31.240.0/24 in the aws-dev default VPC."
  type        = string
  default     = ""
}

variable "range_vpc_id" {
  description = "Target VPC to attach POLARIS subnets to. Leave empty to use the account's default VPC."
  type        = string
  default     = ""
}

variable "availability_zone" {
  description = "AZ for the POLARIS subnets."
  type        = string
  default     = "us-east-2a"
}

variable "egress_route_target" {
  description = "Default route target for each Polaris subnet: igw for default-VPC public SSM egress, nat for the old private range-VPC bake path."
  type        = string
  default     = "igw"

  validation {
    condition     = contains(["igw", "nat"], var.egress_route_target)
    error_message = "egress_route_target must be either igw or nat."
  }
}

variable "internet_gateway_id" {
  description = "Internet gateway for igw egress mode. Leave empty to discover the IGW attached to the target VPC."
  type        = string
  default     = ""
}

variable "nat_gateway_id" {
  description = "NAT gateway for nat egress mode. Required only when egress_route_target is nat."
  type        = string
  default     = ""
}

variable "portal_vpc_cidr" {
  description = "Optional portal VPC CIDR reachable via VPC peering, also allowed to reach host-published SSH/RDP when set. Leave empty for standalone SSM-only management."
  type        = string
  default     = ""
}

variable "portal_peering_id" {
  description = "Optional VPC peering connection from the Polaris VPC to the portal VPC. Leave empty for standalone default-VPC mode."
  type        = string
  default     = ""
}

variable "management_ingress_cidrs" {
  description = "Optional CIDRs allowed to reach host-published SSH/RDP on the Polaris VM and A2 DC. Leave empty for SSM-only management."
  type        = list(string)
  default     = []
}

variable "map_public_ip_on_launch" {
  description = "Whether Polaris-created subnets should assign public IPs by default."
  type        = bool
  default     = true
}

variable "associate_public_ip_address" {
  description = "Whether the Polaris and A2 instances should receive public IPs."
  type        = bool
  default     = true
}

variable "publish_kali_host_ports" {
  description = "Publish a14-kali SSH/RDP on the Polaris EC2 host. Keep false for standalone SSM-only mode; set true only when portal/Guacamole ingress is configured."
  type        = bool
  default     = false
}

variable "ubuntu_ami_id" {
  description = "Ubuntu base AMI (each host just runs Docker + the polaris docker-compose stack). Leave empty to use the latest public Ubuntu 24.04 Noble amd64 AMI in the selected region."
  type        = string
  default     = ""
}

variable "instance_type" {
  description = "EC2 instance type. Kali GUI + 17 compose containers need plenty of headroom."
  type        = string
  default     = "m5.2xlarge"
}

variable "build_tarball_s3_uri" {
  description = "S3 URI of the polaris build tarball uploaded by the operator."
  type        = string

  validation {
    condition     = trimspace(var.build_tarball_s3_uri) != ""
    error_message = "build_tarball_s3_uri must be set to the uploaded Polaris build tarball S3 URI."
  }
}

variable "build_tarball_bucket" {
  description = "S3 bucket holding the polaris build tarball (used to grant IAM read to the instance)."
  type        = string

  validation {
    condition     = trimspace(var.build_tarball_bucket) != ""
    error_message = "build_tarball_bucket must be set to the S3 bucket holding the Polaris build tarball."
  }
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
  description = "Windows Server 2022 Full Base from Amazon. Leave empty to use the latest public Windows Server 2022 Full Base AMI in the selected region."
  type        = string
  default     = ""
}

variable "a2_instance_type" {
  description = "EC2 instance type for the A2 Windows DCs. t3.large (2 vCPU, 8 GB RAM) is the smallest that keeps AD DS + DNS responsive under Kerberoast + secretsdump load."
  type        = string
  default     = "t3.large"
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
