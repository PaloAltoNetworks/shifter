# Provisioner Lambda Functions
#
# Creates Lambda functions for range provisioning:
# - create_subnet: Creates subnet in Range VPC
# - create_victim: Launches victim EC2 with XDR agent
# - create_kali: Sets up Kali attack environment (stub)
# - configure_librechat: Configures chat interface (stub)
# - cleanup: Deletes all range resources

data "aws_region" "current" {}

locals {
  lambda_runtime = "python3.12"

  # Common environment variables for all Lambdas
  common_env_vars = {
    DB_HOST      = var.db_host
    DB_PORT      = tostring(var.db_port)
    DB_NAME      = var.db_name
    DB_USER      = "provisioner_lambda"
    AWS_REGION   = data.aws_region.current.name
    ENVIRONMENT  = var.environment
    RANGE_VPC_ID = var.range_vpc_id
  }

  # Lambda source directories
  lambda_source_dir = "${path.module}/lambda"
}

# ------------------------------------------------------------------------------
# Lambda Layer for shared code and dependencies
# ------------------------------------------------------------------------------

data "archive_file" "shared_layer" {
  type        = "zip"
  source_dir  = "${local.lambda_source_dir}/shared"
  output_path = "${path.module}/.terraform/shared_layer.zip"
}

resource "aws_lambda_layer_version" "shared" {
  layer_name          = "${var.name_prefix}-provisioner-shared"
  filename            = data.archive_file.shared_layer.output_path
  source_code_hash    = data.archive_file.shared_layer.output_base64sha256
  compatible_runtimes = [local.lambda_runtime]

  description = "Shared utilities for provisioner Lambda functions"
}

# ------------------------------------------------------------------------------
# Create Subnet Lambda
# ------------------------------------------------------------------------------

data "archive_file" "create_subnet" {
  type        = "zip"
  source_dir  = "${local.lambda_source_dir}/create_subnet"
  output_path = "${path.module}/.terraform/create_subnet.zip"
}

resource "aws_lambda_function" "create_subnet" {
  function_name = "${var.name_prefix}-create-subnet"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.handler"
  runtime       = local.lambda_runtime
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = data.archive_file.create_subnet.output_path
  source_code_hash = data.archive_file.create_subnet.output_base64sha256

  layers = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.portal_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = merge(local.common_env_vars, {
      RANGE_ROUTE_TABLE_ID = var.range_route_table_id
      AVAILABILITY_ZONE    = var.availability_zone
    })
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-create-subnet"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Create Victim Lambda
# ------------------------------------------------------------------------------

data "archive_file" "create_victim" {
  type        = "zip"
  source_dir  = "${local.lambda_source_dir}/create_victim"
  output_path = "${path.module}/.terraform/create_victim.zip"
}

resource "aws_lambda_function" "create_victim" {
  function_name = "${var.name_prefix}-create-victim"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.handler"
  runtime       = local.lambda_runtime
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = data.archive_file.create_victim.output_path
  source_code_hash = data.archive_file.create_victim.output_base64sha256

  layers = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.portal_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = merge(local.common_env_vars, {
      VICTIM_AMI_ID            = var.victim_ami_id
      VICTIM_INSTANCE_TYPE     = var.victim_instance_type
      VICTIM_SECURITY_GROUP_ID = var.victim_security_group_id
      AGENT_S3_BUCKET          = var.agent_s3_bucket
    })
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-create-victim"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Create Kali Lambda (stub)
# ------------------------------------------------------------------------------

data "archive_file" "create_kali" {
  type        = "zip"
  source_dir  = "${local.lambda_source_dir}/create_kali"
  output_path = "${path.module}/.terraform/create_kali.zip"
}

resource "aws_lambda_function" "create_kali" {
  function_name = "${var.name_prefix}-create-kali"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.handler"
  runtime       = local.lambda_runtime
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = data.archive_file.create_kali.output_path
  source_code_hash = data.archive_file.create_kali.output_base64sha256

  layers = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.portal_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = local.common_env_vars
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-create-kali"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Configure LibreChat Lambda (stub)
# ------------------------------------------------------------------------------

data "archive_file" "configure_librechat" {
  type        = "zip"
  source_dir  = "${local.lambda_source_dir}/configure_librechat"
  output_path = "${path.module}/.terraform/configure_librechat.zip"
}

resource "aws_lambda_function" "configure_librechat" {
  function_name = "${var.name_prefix}-configure-librechat"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.handler"
  runtime       = local.lambda_runtime
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = data.archive_file.configure_librechat.output_path
  source_code_hash = data.archive_file.configure_librechat.output_base64sha256

  layers = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.portal_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = merge(local.common_env_vars, {
      LIBRECHAT_BASE_URL = var.librechat_base_url
    })
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-configure-librechat"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Cleanup Lambda
# ------------------------------------------------------------------------------

data "archive_file" "cleanup" {
  type        = "zip"
  source_dir  = "${local.lambda_source_dir}/cleanup"
  output_path = "${path.module}/.terraform/cleanup.zip"
}

resource "aws_lambda_function" "cleanup" {
  function_name = "${var.name_prefix}-cleanup"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.handler"
  runtime       = local.lambda_runtime
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = data.archive_file.cleanup.output_path
  source_code_hash = data.archive_file.cleanup.output_base64sha256

  layers = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.portal_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = local.common_env_vars
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-cleanup"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Find Stale Ranges Lambda
# ------------------------------------------------------------------------------

data "archive_file" "find_stale_ranges" {
  type        = "zip"
  source_dir  = "${local.lambda_source_dir}/find_stale_ranges"
  output_path = "${path.module}/.terraform/find_stale_ranges.zip"
}

resource "aws_lambda_function" "find_stale_ranges" {
  function_name = "${var.name_prefix}-find-stale-ranges"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.handler"
  runtime       = local.lambda_runtime
  timeout       = 60 # Shorter timeout for this lightweight function
  memory_size   = 128

  filename         = data.archive_file.find_stale_ranges.output_path
  source_code_hash = data.archive_file.find_stale_ranges.output_base64sha256

  layers = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.portal_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = local.common_env_vars
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-find-stale-ranges"
    Module = "provisioner"
  })
}
