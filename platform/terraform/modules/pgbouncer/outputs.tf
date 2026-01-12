# ------------------------------------------------------------------------------
# PgBouncer Module Outputs
# ------------------------------------------------------------------------------

output "service_discovery_endpoint" {
  description = "Service discovery DNS endpoint for PgBouncer"
  value       = "portal-db.pgbouncer.${var.environment}.internal"
}

output "service_discovery_namespace_id" {
  description = "ID of the service discovery namespace"
  value       = aws_service_discovery_private_dns_namespace.pgbouncer.id
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = aws_ecs_cluster.pgbouncer.arn
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = aws_ecs_service.pgbouncer.name
}

output "security_group_id" {
  description = "ID of the PgBouncer security group"
  value       = aws_security_group.pgbouncer.id
}

output "log_group_name" {
  description = "Name of the CloudWatch log group"
  value       = aws_cloudwatch_log_group.pgbouncer.name
}

output "port" {
  description = "PgBouncer listening port"
  value       = 5432
}
