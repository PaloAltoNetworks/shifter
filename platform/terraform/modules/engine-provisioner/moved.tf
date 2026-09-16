# Historical moved blocks: pulumi → engine resource identifier rename

moved {
  from = aws_ecs_cluster.pulumi
  to   = aws_ecs_cluster.engine
}

moved {
  from = aws_ecs_cluster_capacity_providers.pulumi
  to   = aws_ecs_cluster_capacity_providers.engine
}

moved {
  from = aws_ecs_task_definition.pulumi_provisioner
  to   = aws_ecs_task_definition.engine_provisioner
}

moved {
  from = aws_iam_role_policy.pulumi_state
  to   = aws_iam_role_policy.engine_state
}

# #1826: the substrate-neutral provisioner permission set moved into
# modules/provisioner-iam so the ECS task role and the EKS provisioner IRSA role
# share one definition. Relocate the live ECS resources into the module rather
# than destroy/recreate them (chains from the pulumi_state -> engine_state move).

moved {
  from = aws_iam_role_policy.engine_state
  to   = module.provisioner_iam.aws_iam_role_policy.engine_state
}

moved {
  from = aws_iam_policy.ec2_provisioning
  to   = module.provisioner_iam.aws_iam_policy.ec2_provisioning
}

moved {
  from = aws_iam_role_policy_attachment.ec2_provisioning
  to   = module.provisioner_iam.aws_iam_role_policy_attachment.ec2_provisioning
}

moved {
  from = aws_iam_policy.ec2_run_instances
  to   = module.provisioner_iam.aws_iam_policy.ec2_run_instances
}

moved {
  from = aws_iam_role_policy_attachment.ec2_run_instances
  to   = module.provisioner_iam.aws_iam_role_policy_attachment.ec2_run_instances
}

moved {
  from = aws_iam_policy.gwlb
  to   = module.provisioner_iam.aws_iam_policy.gwlb
}

moved {
  from = aws_iam_role_policy_attachment.gwlb
  to   = module.provisioner_iam.aws_iam_role_policy_attachment.gwlb
}

moved {
  from = aws_iam_role_policy.secrets_manager
  to   = module.provisioner_iam.aws_iam_role_policy.secrets_manager
}

moved {
  from = aws_iam_role_policy.rds_iam_auth
  to   = module.provisioner_iam.aws_iam_role_policy.rds_iam_auth
}

moved {
  from = aws_iam_role_policy.s3_agent
  to   = module.provisioner_iam.aws_iam_role_policy.s3_agent
}

moved {
  from = aws_iam_role_policy.vpc_endpoints
  to   = module.provisioner_iam.aws_iam_role_policy.vpc_endpoints
}

moved {
  from = aws_iam_role_policy.s3_bootstrap
  to   = module.provisioner_iam.aws_iam_role_policy.s3_bootstrap
}

moved {
  from = aws_iam_role_policy.ssm_parameters
  to   = module.provisioner_iam.aws_iam_role_policy.ssm_parameters
}

moved {
  from = aws_iam_role_policy.ssm_run_command
  to   = module.provisioner_iam.aws_iam_role_policy.ssm_run_command
}

moved {
  from = aws_iam_role_policy.kms
  to   = module.provisioner_iam.aws_iam_role_policy.kms
}

moved {
  from = aws_iam_role_policy.polaris_agent_role_management
  to   = module.provisioner_iam.aws_iam_role_policy.polaris_agent_role_management
}

moved {
  from = aws_iam_role_policy.vpn_gateway_role_management
  to   = module.provisioner_iam.aws_iam_role_policy.vpn_gateway_role_management
}
