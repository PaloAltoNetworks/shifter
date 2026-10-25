variable "model_broker" {
  description = "Optional private model broker intent rendered from installation settings."
  type = object({
    enabled                 = optional(bool, false)
    hostname                = optional(string, "")
    admitted_subnets        = optional(list(string), [])
    tls_secret_name         = optional(string, "")
    control_tls_secret_name = optional(string, "")
    trust_configmap_name    = optional(string, "")
    invocation_models       = optional(map(string), {})
  })
  default = {}
}

module "model_broker" {
  count                    = var.model_broker.enabled ? 1 : 0
  source                   = "../eks-model-broker"
  settings                 = var.model_broker
  cluster_name             = var.cluster_name
  region                   = var.aws_region
  permissions_boundary_arn = var.permissions_boundary_arn
  oidc_provider_arn        = aws_iam_openid_connect_provider.cluster.arn
  oidc_issuer              = aws_eks_cluster.this.identity[0].oidc[0].issuer
  provisioner_subject      = aws_iam_role.workload["provisioner"].arn
  vpc_id                   = aws_vpc.this.id
  vpc_cidr                 = var.vpc_cidr
  private_subnets          = { for zone, subnet in aws_subnet.private : zone => { id = subnet.id, cidr = subnet.cidr_block } }
  range_vpc_id             = local.range_network["vpc_id"]
  range_vpc_cidr           = local.range_network["vpc_cidr"]
  tags                     = var.tags
}

resource "aws_vpc_security_group_ingress_rule" "model_broker" {
  count                        = var.model_broker.enabled ? 1 : 0
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = module.model_broker[0].listener_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 8443
  to_port                      = 8443
  description                  = "Private model NLB to broker targets; NetworkPolicy admits only broker pods"
}

output "model_broker" {
  description = "Applied optional private model broker deployment."
  value       = var.model_broker.enabled ? module.model_broker[0].deployment : null
}
