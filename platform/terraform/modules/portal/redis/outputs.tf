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
