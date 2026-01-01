# S3 Gateway Endpoint for Range VPC
#
# Enables S3 access for victim instances to download agent installers via presigned URLs.
# Gateway endpoints route traffic directly to S3 within AWS network, bypassing the
# Network Firewall. This is required because the firewall domain allowlist doesn't
# include S3 domains by default.
#
# Gateway endpoints are free and do not create additional network paths that could
# be exploited - they only route S3 API traffic.

# ------------------------------------------------------------------------------
# S3 Gateway Endpoint
# ------------------------------------------------------------------------------

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"

  # Associate with private route table (used by victim/kali subnets)
  route_table_ids = [aws_route_table.private.id]

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-s3-endpoint"
  })
}
