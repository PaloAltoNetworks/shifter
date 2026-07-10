# Redis module outputs

output "redis_endpoint" {
  description = "Redis endpoint address"
  value       = var.enable_replication ? aws_elasticache_replication_group.ha[0].primary_endpoint_address : aws_elasticache_cluster.single_node[0].cache_nodes[0].address
}

output "redis_port" {
  description = "Redis port"
  value       = var.enable_replication ? aws_elasticache_replication_group.ha[0].port : aws_elasticache_cluster.single_node[0].cache_nodes[0].port
}

output "security_group_id" {
  description = "ID of the Redis security group"
  value       = aws_security_group.this.id
}

output "redis_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the Redis AUTH token. Empty on the single-node path (no AUTH); set on the replication-group / in-transit-encryption path (#938)."
  value       = var.enable_replication ? aws_secretsmanager_secret.redis_auth[0].arn : ""
}

output "redis_tls_enabled" {
  description = "Whether the active Redis path uses in-transit encryption + AUTH. True for the replication-group path (#938), false for the single-node plaintext path."
  value       = var.enable_replication
}
