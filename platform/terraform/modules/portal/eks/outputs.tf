output "cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "Private EKS API endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_ca_certificate" {
  description = "Base64-encoded cluster CA data used to create short-lived kubeconfigs."
  value       = aws_eks_cluster.this.certificate_authority[0].data
  sensitive   = true
}

output "oidc_provider_arn" {
  description = "EKS workload identity OIDC provider ARN."
  value       = aws_iam_openid_connect_provider.cluster.arn
}

output "workload_role_arns" {
  description = "IAM role ARN keyed by process-specific workload identity, including the dedicated cluster-autoscaler role."
  value = merge(
    { for name, role in aws_iam_role.workload : name => role.arn },
    { "cluster-autoscaler" = aws_iam_role.cluster_autoscaler.arn },
  )
}

output "workload_role_names" {
  description = "IAM role name keyed by process-specific workload identity (for downstream policy attachment)."
  value       = { for name, role in aws_iam_role.workload : name => role.name }
}

output "workload_role_ids" {
  description = "IAM role id keyed by process-specific workload identity (for downstream inline-policy attachment)."
  value       = { for name, role in aws_iam_role.workload : name => role.id }
}

output "workload_identity_subjects" {
  description = "Exact Kubernetes subjects keyed by process."
  value = {
    for name, identity in var.workload_identities :
    name => "system:serviceaccount:${identity.namespace}:${identity.service_account}"
  }
}

output "vpc_id" {
  description = "EKS-owned VPC ID."
  value       = aws_vpc.this.id
}

output "portal_vpc_cidr" {
  description = "CIDR of the peered portal VPC that hosts the shared RDS/Redis data plane (ADR-044-R6)."
  value       = data.aws_vpc.portal.cidr_block
}

output "portal_db_address" {
  description = "Endpoint address of the shared portal RDS instance (guacamole PostgreSQL host)."
  value       = data.aws_db_instance.portal.address
}

output "portal_db_port" {
  description = "Endpoint port of the shared portal RDS instance."
  value       = data.aws_db_instance.portal.port
}

output "private_subnet_ids" {
  description = "Private node and pod subnet IDs."
  value       = [for subnet in aws_subnet.private : subnet.id]
}

output "service_ipv4_cidr" {
  description = "Cluster service (ClusterIP) CIDR. In-cluster clients reach the Kubernetes API at the kubernetes.default ClusterIP in this range, so it is the launcher's real API-egress target and the range the broad provider-API egress must exclude (#1826)."
  value       = aws_eks_cluster.this.kubernetes_network_config[0].service_ipv4_cidr
}

output "secret_arns" {
  description = "Secret-container ARNs keyed by logical name."
  value       = { for name, secret in aws_secretsmanager_secret.platform : name => secret.arn }
}

output "ingress_certificate_arn" {
  description = "Regional ACM certificate ARN for ingress."
  value       = aws_acm_certificate.ingress.arn
}

output "ingress_certificate_validation_records" {
  description = "DNS records that must be published to validate the ingress certificate."
  value = [
    for option in aws_acm_certificate.ingress.domain_validation_options : {
      name  = option.resource_record_name
      type  = option.resource_record_type
      value = option.resource_record_value
    }
  ]
}

output "ingress_waf_acl_arn" {
  description = "Regional WAF ACL ARN for the ingress load balancer."
  value       = aws_wafv2_web_acl.ingress.arn
}

output "runtime_plugin_node_group_asg" {
  description = "Auto Scaling group of the runtime-plugin pool; the trusted labeler labels only its nodes. Empty when the pool is disabled."
  value       = var.enable_runtime_plugins ? aws_eks_node_group.runtime_plugins[0].resources[0].autoscaling_groups[0].name : ""
}
