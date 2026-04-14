#------------------------------------------------------------------------------
# POLARIS test range — N parallel ranges inside the existing dev range VPC,
# each one an Ubuntu polaris VM running the docker-compose stack plus a
# Windows Server 2022 DC for BOREAS.LOCAL. Every range lives in its own
# /28 subnet with pinned private IPs (.10 polaris, .11 DC) so compose zone
# files and the a2_setup.ps1 contract work unchanged for any N.
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
  name_prefix = "polaris-bake"

  # Per-range subnet + IP plan. For each range index, carve a /28 out of
  # var.polaris_cidr_block and pin polaris .10 / a2 .11 inside it.
  range_subnets = {
    for idx in var.range_indices : idx => {
      cidr       = cidrsubnet(var.polaris_cidr_block, 4, tonumber(idx))
      polaris_ip = cidrhost(cidrsubnet(var.polaris_cidr_block, 4, tonumber(idx)), 10)
      a2_ip      = cidrhost(cidrsubnet(var.polaris_cidr_block, 4, tonumber(idx)), 11)
    }
  }
}
