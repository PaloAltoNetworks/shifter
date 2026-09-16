output "bundle_outputs" {
  description = "Non-secret provider values consumed by the AWS bundle renderer."
  value = {
    cluster_name                    = module.eks.cluster_name
    cluster_endpoint                = module.eks.cluster_endpoint
    vpc_id                          = module.eks.vpc_id
    private_subnet_ids              = module.eks.private_subnet_ids
    workload_role_arns              = module.eks.workload_role_arns
    workload_identity_subjects      = module.eks.workload_identity_subjects
    secret_arns                     = module.eks.secret_arns
    ingress_certificate_arn         = module.eks.ingress_certificate_arn
    ingress_certificate_dns_records = module.eks.ingress_certificate_validation_records
    ingress_waf_acl_arn             = module.eks.ingress_waf_acl_arn
  }
}

output "cluster_ca_certificate" {
  description = "Sensitive CA material for short-lived kubeconfig generation."
  value       = module.eks.cluster_ca_certificate
  sensitive   = true
}

output "cluster_name" {
  description = "EKS cluster name consumed by the lifecycle owner."
  value       = module.eks.cluster_name
}

output "cluster_access_role_arn" {
  description = "Protected short-lived deployment role authorized through an EKS access entry."
  value       = var.deployment_role_arn
}

output "certificate_arn" {
  description = "ACM certificate ARN consumed by ingress configuration."
  value       = module.eks.ingress_certificate_arn
}

output "waf_acl_arn" {
  description = "Regional WAF ACL ARN consumed by ingress configuration."
  value       = module.eks.ingress_waf_acl_arn
}

output "workload_role_arns" {
  description = "Exact service-account workload roles keyed by process."
  value       = module.eks.workload_role_arns
}

output "runtime_env" {
  description = "Management-plane runtime bindings merged with the assembled provisioner Job environment, consumed by the AWS renderer."
  value       = module.eks_provisioner_env.runtime_env
  sensitive   = true
}

output "ingress_source_cidrs" {
  description = "EKS public-subnet CIDRs from which ALB target traffic reaches pods."
  value       = var.public_subnet_cidrs
}

output "edge_client_cidrs" {
  description = "Validated public client CIDRs consumed by the ALB inbound restriction."
  value       = var.edge_client_cidrs
}

output "provider_api_cidrs" {
  description = "Validated AWS API CIDRs consumed by chart network policy."
  value       = var.provider_api_cidrs
}

output "private_service_cidrs" {
  description = "Private EKS VPC CIDRs consumed by chart network policy."
  value       = [var.vpc_cidr]
}

output "kubernetes_api_cidrs" {
  description = "Private cluster API reachability CIDRs consumed by chart network policy."
  value       = var.private_subnet_cidrs
}
