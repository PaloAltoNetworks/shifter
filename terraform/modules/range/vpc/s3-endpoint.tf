# S3 Gateway Endpoint for Range VPC
#
# Enables direct S3 access for Kali and Victim instances without
# routing through Network Firewall. Required for agent installer downloads.
#
# Gateway endpoints are free and route traffic within AWS network.
# Traffic to S3 bypasses firewall because prefix list routes have
# higher specificity than the 0.0.0.0/0 route to firewall.

# ------------------------------------------------------------------------------
# S3 Gateway Endpoint
# ------------------------------------------------------------------------------

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"

  # Associate with private route table (used by victim/kali subnets)
  route_table_ids = [aws_route_table.private.id]

  # Restrict access to agent S3 bucket if specified
  policy = var.agent_s3_bucket_arn != "" ? jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowAgentBucketAccess"
        Effect    = "Allow"
        Principal = "*"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.agent_s3_bucket_arn,
          "${var.agent_s3_bucket_arn}/*"
        ]
      }
    ]
  }) : null # null = default policy (allow all S3)

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-s3-endpoint"
  })
}
