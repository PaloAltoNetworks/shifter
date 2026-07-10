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

output "public_subnet_cidrs" {
  description = "CIDR blocks of public subnets."
  value       = aws_subnet.public[*].cidr_block
}

output "alb_ingress_subnet_cidrs" {
  description = <<-EOT
    CIDR blocks of the ALB ingress tier (the `public` subnets), the only
    CIDR source the portal target-service security groups (Django:8000,
    Guacamole client:8080) may admit. AWS Network Firewall breaks SG
    referencing across the routed inspection path, so the inspected
    ALB->target flow needs a CIDR rule; this output scopes that rule to the
    ALB tier and deliberately EXCLUDES the public-workload tier where CTFd
    lives (#911 NET-2 / #933). Consume this, never `public_subnet_cidrs`,
    for target-service ingress.
  EOT
  value       = aws_subnet.public[*].cidr_block
}

output "public_workload_subnet_ids" {
  description = "IDs of the public-workload subnets (CTFd and future standalone public EC2). Separate from the ALB ingress tier so target-service SGs do not admit these workloads."
  value       = aws_subnet.public_workload[*].id
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

output "gateway_endpoint_ids" {
  description = "Map of private-tier gateway VPC endpoint service key to endpoint ID."
  value       = { for service, endpoint in aws_vpc_endpoint.gateway : service => endpoint.id }
}

output "interface_endpoint_ids" {
  description = "Map of private-tier interface VPC endpoint service key to endpoint ID."
  value       = { for service, endpoint in aws_vpc_endpoint.interface : service => endpoint.id }
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

output "firewall_arn" {
  description = "ARN of the portal Network Firewall. Empty string when inspection is disabled."
  value       = var.enable_portal_inspection ? aws_networkfirewall_firewall.portal[0].arn : ""
}

output "public_route_table_ids" {
  description = "IDs of the per-AZ public route tables, ordered by availability_zones."
  value       = aws_route_table.public[*].id
}

output "firewall_route_table_ids" {
  description = "IDs of the per-AZ firewall route tables, ordered by availability_zones. Empty list when inspection is disabled."
  value       = aws_route_table.firewall[*].id
}

output "private_subnet_cidrs" {
  description = "CIDR blocks of the per-AZ private subnets, ordered by availability_zones."
  value       = aws_subnet.private[*].cidr_block
}

output "firewall_subnet_cidrs" {
  description = "CIDR blocks of the per-AZ firewall subnets, ordered by availability_zones. Empty list when inspection is disabled."
  value       = aws_subnet.firewall[*].cidr_block
}
