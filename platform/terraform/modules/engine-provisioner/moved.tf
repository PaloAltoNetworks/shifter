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
