# Generic guest management is independent of optional model access.
data "aws_ssm_parameters_by_path" "range_network" {
  path            = "/shifter/${var.environment}/range/"
  recursive       = true
  with_decryption = false
}

locals {
  range_network = {
    for name, value in zipmap(data.aws_ssm_parameters_by_path.range_network.names, nonsensitive(data.aws_ssm_parameters_by_path.range_network.values)) :
    trimprefix(name, "/shifter/${var.environment}/range/") => value
  }
}

resource "aws_vpc_peering_connection" "range" {
  vpc_id      = aws_vpc.this.id
  peer_vpc_id = local.range_network["vpc_id"]
  auto_accept = true
  tags        = merge(var.tags, { Name = "${var.cluster_name}-range-management" })
  lifecycle {
    precondition {
      condition = (
        cidrhost("${cidrhost(local.range_network["vpc_cidr"], 0)}/${split("/", var.vpc_cidr)[1]}", 0) != cidrhost(var.vpc_cidr, 0) &&
        cidrhost("${cidrhost(var.vpc_cidr, 0)}/${split("/", local.range_network["vpc_cidr"])[1]}", 0) != cidrhost(local.range_network["vpc_cidr"], 0)
      )
      error_message = "Range management requires disjoint platform and guest networks."
    }
  }
}

resource "aws_route" "range_to_management" {
  for_each                  = aws_subnet.private
  route_table_id            = local.range_network["private_route_table_id"]
  destination_cidr_block    = each.value.cidr_block
  vpc_peering_connection_id = aws_vpc_peering_connection.range.id
}

# Preserve existing applied peering and routes when upgrading the broker layout.
moved {
  from = module.model_broker[0].aws_vpc_peering_connection.range
  to   = aws_vpc_peering_connection.range
}
moved {
  from = module.model_broker[0].aws_route.range_to_broker
  to   = aws_route.range_to_management
}

output "private_subnet_cidrs" {
  description = "Applied EKS node and pod networks for guest management and participant gateways."
  value       = sort([for subnet in aws_subnet.private : subnet.cidr_block])
}
