# Historical moved blocks: pulumi → engine resource identifier rename

moved {
  from = aws_s3_bucket.pulumi_state
  to   = aws_s3_bucket.engine_state
}

moved {
  from = aws_s3_bucket_versioning.pulumi_state
  to   = aws_s3_bucket_versioning.engine_state
}

moved {
  from = aws_s3_bucket_server_side_encryption_configuration.pulumi_state
  to   = aws_s3_bucket_server_side_encryption_configuration.engine_state
}

moved {
  from = aws_s3_bucket_public_access_block.pulumi_state
  to   = aws_s3_bucket_public_access_block.engine_state
}

moved {
  from = aws_s3_bucket_lifecycle_configuration.pulumi_state
  to   = aws_s3_bucket_lifecycle_configuration.engine_state
}

moved {
  from = aws_kms_key.pulumi_secrets
  to   = aws_kms_key.engine_secrets
}

moved {
  from = aws_kms_alias.pulumi_secrets
  to   = aws_kms_alias.engine_secrets
}

moved {
  from = aws_dynamodb_table.pulumi_locks
  to   = aws_dynamodb_table.engine_locks
}
