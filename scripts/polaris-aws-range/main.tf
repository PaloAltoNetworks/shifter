#------------------------------------------------------------------------------
# POLARIS test range — N parallel standalone ranges in a target AWS VPC.
# The default operator path is the aws-dev default VPC with public-IP SSM
# egress; the older private range-VPC/NAT path remains available by setting
# range_vpc_id, polaris_cidr_block, egress_route_target="nat", nat_gateway_id,
# and optional portal peering/ingress values.
#
# Each range gets an Ubuntu polaris VM running the docker-compose stack plus
# a Windows Server 2022 DC for BOREAS.LOCAL. Every range lives in its own /28
# subnet with pinned private IPs (.10 polaris, .11 DC) so compose zone files
# and the a2_setup.ps1 contract work unchanged for any N.
#
# Shared resources (security group, IAM role, instance profile) live in
# shared.tf so a single copy drives all N ranges — bypasses the per-VPC
# SG-name + per-account IAM-name uniqueness constraints that otherwise
# would block a second range in the same account.
#
# Per-range resources live in ranges.tf and use for_each on
# var.range_indices so each index gets its own subnet/route table/instance
# pair without resource-address drift on apply.
#
# This is a manual "user range" — cyberscript/provisioner is bypassed; DB
# records are populated by scripts/polaris-aws-range/register_range.py once
# the VMs are up.
#------------------------------------------------------------------------------

locals {
  name_prefix = var.name_prefix

  target_vpc_id        = trimspace(var.range_vpc_id) != "" ? var.range_vpc_id : data.aws_vpc.default.id
  target_vpc_cidr      = data.aws_vpc.target.cidr_block
  polaris_cidr_block   = trimspace(var.polaris_cidr_block) != "" ? var.polaris_cidr_block : cidrsubnet(local.target_vpc_cidr, 8, 240)
  ubuntu_ami_id        = trimspace(var.ubuntu_ami_id) != "" ? var.ubuntu_ami_id : data.aws_ami.ubuntu_noble.id
  a2_dc_ami_id         = trimspace(var.a2_dc_ami_id) != "" ? var.a2_dc_ami_id : data.aws_ami.windows_2022.id
  internet_gateway_id  = trimspace(var.internet_gateway_id) != "" ? var.internet_gateway_id : one(data.aws_internet_gateway.target[*].id)
  aws_cli_profile_args = trimspace(coalesce(var.aws_profile, "")) == "" ? "" : "--profile ${var.aws_profile} "

  # Per-range subnet + IP plan. For each range index, carve a /28 out of
  # var.polaris_cidr_block and pin polaris .10 / a2 .11 inside it.
  range_subnets = {
    for idx in var.range_indices : idx => {
      cidr       = cidrsubnet(local.polaris_cidr_block, 4, tonumber(idx))
      polaris_ip = cidrhost(cidrsubnet(local.polaris_cidr_block, 4, tonumber(idx)), 10)
      a2_ip      = cidrhost(cidrsubnet(local.polaris_cidr_block, 4, tonumber(idx)), 11)
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_vpc" "target" {
  id = local.target_vpc_id
}

data "aws_internet_gateway" "target" {
  count = var.egress_route_target == "igw" && trimspace(var.internet_gateway_id) == "" ? 1 : 0

  filter {
    name   = "attachment.vpc-id"
    values = [local.target_vpc_id]
  }
}

data "aws_ami" "ubuntu_noble" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_ami" "windows_2022" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Windows_Server-2022-English-Full-Base-*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
