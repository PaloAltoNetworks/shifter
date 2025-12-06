# Portal module outputs

output "vpc_id" {
  description = "ID of the portal VPC"
  value       = aws_vpc.portal.id
}

output "vpc_cidr" {
  description = "CIDR block of the portal VPC"
  value       = aws_vpc.portal.cidr_block
}

output "public_subnet_ids" {
  description = "IDs of public subnets"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of private subnets (for RDS, ECS)"
  value       = aws_subnet.private[*].id
}

output "internet_gateway_id" {
  description = "ID of the internet gateway"
  value       = aws_internet_gateway.portal.id
}

output "nat_gateway_id" {
  description = "ID of the NAT gateway (if enabled)"
  value       = var.enable_nat_gateway ? aws_nat_gateway.portal[0].id : null
}

output "availability_zones" {
  description = "Availability zones used"
  value       = local.azs
}
