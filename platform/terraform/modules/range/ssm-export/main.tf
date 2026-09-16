# Range SSM export (ADR-044-R6)
#
# The range stack owns its topology (VPC/subnet/route-table/security-group IDs,
# endpoint IDs, ARNs). Those values are opaque and not discoverable by a native
# `data.aws_*` name lookup, so the range stack — as their owner — publishes them
# to SSM Parameter Store as an explicit cross-stack contract. The AWS EKS control
# plane reads `/shifter/<env>/range/*` and composes the provisioner Job env from
# it (plus native data sources for the name-discoverable portal infra and the
# existing `/shifter/ami/*` params). This replaces reaching into the range's
# whole Terraform state via `terraform_remote_state`.
#
# Non-secret only: every value here is an identifier, ARN, CIDR, or mode string.
# Secret payloads never transit this module (ADR-044-R2).

locals {
  ps_prefix = "/shifter/${var.environment}/range"

  common_tags = merge(var.tags, {
    Module = "range-ssm-export"
  })

  # SSM String parameters reject an empty value, and an empty value carries no
  # information anyway (a disabled optional resource). Skip them; the EKS
  # consumer defaults an absent key to "" to mirror the portal root's
  # `x != null ? x : ""` handling.
  published = {
    for key, value in var.parameters : key => value if value != ""
  }
}

resource "aws_ssm_parameter" "range" {
  for_each = local.published

  name        = "${local.ps_prefix}/${each.key}"
  description = "Range topology value published for cross-stack provisioner-env assembly (ADR-044-R6)"
  type        = "String"
  value       = each.value

  tags = local.common_tags
}
