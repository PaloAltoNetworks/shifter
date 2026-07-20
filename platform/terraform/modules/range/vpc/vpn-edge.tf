# Shared public placement subnet for request-owned OpenVPN NLBs.
# Termination and credentials remain per range; this subnet carries only the
# provider-managed public load-balancer nodes.

resource "aws_subnet" "vpn_edge" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 11, 2) # 10.1.0.64/27
  availability_zone       = local.primary_az
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpn-edge-subnet"
    Tier = "public"
  })
}

resource "aws_route_table" "vpn_edge" {
  vpc_id = aws_vpc.this.id
  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpn-edge-rt"
  })
}

resource "aws_route" "vpn_edge_to_igw" {
  route_table_id         = aws_route_table.vpn_edge.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "vpn_edge" {
  subnet_id      = aws_subnet.vpn_edge.id
  route_table_id = aws_route_table.vpn_edge.id
}
