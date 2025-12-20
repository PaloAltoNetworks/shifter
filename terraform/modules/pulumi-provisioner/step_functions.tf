# ------------------------------------------------------------------------------
# Step Functions State Machines
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# Provision Range State Machine
# ------------------------------------------------------------------------------

resource "aws_sfn_state_machine" "provision_range_pulumi" {
  name     = "${var.name_prefix}-provision-range-pulumi"
  role_arn = aws_iam_role.step_functions.arn

  definition = templatefile("${path.module}/state_machines/provision_range_pulumi.asl.json", {
    ecs_cluster_arn       = aws_ecs_cluster.pulumi.arn
    task_definition_arn   = aws_ecs_task_definition.pulumi_provisioner.arn
    ecs_security_group_id = aws_security_group.ecs_task.id
    private_subnet_ids    = jsonencode(var.private_subnet_ids)
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-provision-range-pulumi"
  })
}

# ------------------------------------------------------------------------------
# Destroy Range State Machine
# ------------------------------------------------------------------------------

resource "aws_sfn_state_machine" "destroy_range_pulumi" {
  name     = "${var.name_prefix}-destroy-range-pulumi"
  role_arn = aws_iam_role.step_functions.arn

  definition = templatefile("${path.module}/state_machines/destroy_range_pulumi.asl.json", {
    ecs_cluster_arn       = aws_ecs_cluster.pulumi.arn
    task_definition_arn   = aws_ecs_task_definition.pulumi_provisioner.arn
    ecs_security_group_id = aws_security_group.ecs_task.id
    private_subnet_ids    = jsonencode(var.private_subnet_ids)
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-destroy-range-pulumi"
  })
}
