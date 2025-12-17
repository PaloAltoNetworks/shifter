# Range VPC module outputs

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC"
  value       = aws_vpc.this.cidr_block
}

output "internet_gateway_id" {
  description = "ID of the internet gateway"
  value       = aws_internet_gateway.this.id
}

# ------------------------------------------------------------------------------
# Route Tables
# ------------------------------------------------------------------------------

output "private_route_table_id" {
  description = "ID of the private route table (for user subnet associations)"
  value       = aws_route_table.private.id
}

# DEPRECATED: Use private_route_table_id instead
output "public_route_table_id" {
  description = "DEPRECATED: Use private_route_table_id. Kept for backward compatibility."
  value       = aws_route_table.private.id
}

# ------------------------------------------------------------------------------
# Security Groups
# ------------------------------------------------------------------------------

output "victim_security_group_id" {
  description = "ID of the security group for victim EC2 instances"
  value       = aws_security_group.victim.id
}

output "kali_security_group_id" {
  description = "ID of the security group for Kali attack instances"
  value       = aws_security_group.kali.id
}

# ------------------------------------------------------------------------------
# Network Firewall
# ------------------------------------------------------------------------------

output "nat_gateway_id" {
  description = "ID of the NAT Gateway"
  value       = aws_nat_gateway.this.id
}

output "firewall_endpoint_id" {
  description = "ID of the Network Firewall endpoint (null if firewall disabled)"
  value       = var.enable_network_firewall ? one(one(aws_networkfirewall_firewall.this[0].firewall_status).sync_states).attachment[0].endpoint_id : null
}

output "firewall_arn" {
  description = "ARN of the Network Firewall (null if firewall disabled)"
  value       = var.enable_network_firewall ? aws_networkfirewall_firewall.this[0].arn : null
}
