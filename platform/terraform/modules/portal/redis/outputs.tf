# Redis module outputs

output "redis_endpoint" {
  description = "Address of the Redis cluster endpoint"
  value       = aws_elasticache_cluster.this.cache_nodes[0].address
}

output "redis_port" {
  description = "Port of the Redis cluster"
  value       = aws_elasticache_cluster.this.cache_nodes[0].port
}

output "security_group_id" {
  description = "ID of the Redis security group"
  value       = aws_security_group.this.id
}
