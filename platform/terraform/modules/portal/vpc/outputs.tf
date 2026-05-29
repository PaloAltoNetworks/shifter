# VPC module outputs

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC"
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "IDs of public subnets"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of private subnets"
  value       = aws_subnet.private[*].id
}

output "internet_gateway_id" {
  description = "ID of the internet gateway"
  value       = aws_internet_gateway.this.id
}

output "nat_gateway_id" {
  description = "ID of the NAT gateway (if enabled)"
  value       = var.enable_nat_gateway ? aws_nat_gateway.this[0].id : null
}

output "availability_zones" {
  description = "Availability zones used"
  value       = local.azs
}

output "private_route_table_ids" {
  description = "IDs of the per-AZ private route tables (ordered by availability_zones)."
  value       = aws_route_table.private[*].id
}

output "flow_logs_log_group_name" {
  description = "Name of the CloudWatch log group for VPC flow logs"
  value       = var.enable_flow_logs ? aws_cloudwatch_log_group.flow_logs[0].name : ""
}

# ------------------------------------------------------------------------------
# Portal east-west inspection (#122)
# ------------------------------------------------------------------------------

output "inspection_enabled" {
  description = "Whether the portal east-west inspection boundary is enabled."
  value       = var.enable_portal_inspection
}

output "firewall_endpoint_ids_by_az" {
  description = "Map of availability_zone -> portal Network Firewall endpoint ID. Empty map when inspection is disabled."
  value       = var.enable_portal_inspection ? local.firewall_endpoint_ids_by_az : {}
}

output "firewall_log_group_name" {
  description = "Name of the CloudWatch log group receiving Network Firewall FLOW / ALERT logs. Empty string when inspection is disabled."
  value       = var.enable_portal_inspection ? aws_cloudwatch_log_group.firewall[0].name : ""
}
