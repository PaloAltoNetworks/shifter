# NAT Gateway for Range VPC
#
# Provides outbound internet access for private subnets via Network Firewall.
# Single NAT Gateway for cost optimization (can be per-AZ for HA).

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  # Use first AZ for infrastructure subnets
  primary_az = data.aws_availability_zones.available.names[0]
}

# ------------------------------------------------------------------------------
# NAT Gateway Subnet (10.1.0.16/28)
# ------------------------------------------------------------------------------

resource "aws_subnet" "nat" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 12, 1) # 10.1.0.16/28
  availability_zone       = local.primary_az
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat-subnet"
    Tier = "public"
  })
}

# ------------------------------------------------------------------------------
# NAT Gateway
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_19:EIP attached to NAT Gateway, not EC2 - see #222
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat-eip"
  })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.nat.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat"
  })

  depends_on = [aws_internet_gateway.this]
}

# ------------------------------------------------------------------------------
# NAT Subnet Route Table
# ------------------------------------------------------------------------------

resource "aws_route_table" "nat" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat-rt"
  })
}

# Outbound to internet via IGW
resource "aws_route" "nat_to_igw" {
  route_table_id         = aws_route_table.nat.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

# Return traffic from internet goes through firewall for inspection
resource "aws_route" "nat_to_firewall" {
  count = var.enable_network_firewall ? 1 : 0

  route_table_id         = aws_route_table.nat.id
  destination_cidr_block = var.vpc_cidr
  vpc_endpoint_id        = one(one(aws_networkfirewall_firewall.this[0].firewall_status).sync_states).attachment[0].endpoint_id
}

resource "aws_route_table_association" "nat" {
  subnet_id      = aws_subnet.nat.id
  route_table_id = aws_route_table.nat.id
}
