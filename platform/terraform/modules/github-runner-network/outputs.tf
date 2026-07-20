output "vpc_id" {
  description = "ID of the dedicated runner VPC."
  value       = aws_vpc.this.id
}

output "runner_subnet_id" {
  description = "ID of the private runner subnet (egress via NAT)."
  value       = aws_subnet.runner.id
}

output "vpc_cidr" {
  description = "CIDR block of the runner VPC."
  value       = aws_vpc.this.cidr_block
}

output "availability_zone" {
  description = "Availability zone the runner and NAT subnets live in."
  value       = local.primary_az
}

output "nat_gateway_id" {
  description = "ID of the NAT gateway providing runner egress."
  value       = aws_nat_gateway.this.id
}
