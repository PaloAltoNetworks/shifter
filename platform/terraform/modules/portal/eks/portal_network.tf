# Portal data-plane peering (ADR-044-R6).
#
# The portal app + provisioner run as pods in this EKS VPC and reach the shared
# portal data plane (RDS PostgreSQL, Redis) that lives in the portal VPC. The
# legacy ECS/EC2 runtime that used to run in the portal VPC (and was the sole
# in-VPC ingress source for RDS/Redis) was retired, so the two planes are now
# joined by this VPC peering and RDS/Redis admit the EKS VPC CIDR.
#
# The portal VPC and its private route tables are name-discoverable, so no
# producer publish step is required (mirrors range_network.tf and the
# eks-provisioner-env consumer). Apply order is range -> portal -> eks.

data "aws_vpc" "portal" {
  tags = {
    Name = "${var.environment}-portal-vpc"
  }
}

data "aws_route_tables" "portal_private" {
  vpc_id = data.aws_vpc.portal.id

  filter {
    name   = "tag:Name"
    values = ["${var.environment}-portal-private-rt-*"]
  }
}

resource "aws_vpc_peering_connection" "portal" {
  vpc_id      = aws_vpc.this.id
  peer_vpc_id = data.aws_vpc.portal.id
  auto_accept = true
  tags        = merge(var.tags, { Name = "${var.cluster_name}-portal-data-plane" })

  lifecycle {
    precondition {
      condition = (
        cidrhost("${cidrhost(data.aws_vpc.portal.cidr_block, 0)}/${split("/", var.vpc_cidr)[1]}", 0) != cidrhost(var.vpc_cidr, 0) &&
        cidrhost("${cidrhost(var.vpc_cidr, 0)}/${split("/", data.aws_vpc.portal.cidr_block)[1]}", 0) != cidrhost(data.aws_vpc.portal.cidr_block, 0)
      )
      error_message = "Portal data-plane peering requires disjoint EKS and portal networks."
    }
  }
}

# Portal-side return routes: every portal private route table reaches the EKS
# node/pod subnets through the peering. Complete matrix over (portal RT x EKS
# private subnet CIDR); the EKS-side routes to the portal VPC CIDR live on
# aws_route_table.private (network.tf).
resource "aws_route" "portal_to_eks" {
  for_each = {
    for pair in setproduct(
      data.aws_route_tables.portal_private.ids,
      [for s in aws_subnet.private : s.cidr_block],
    ) : "${pair[0]}:${pair[1]}" => { route_table_id = pair[0], cidr = pair[1] }
  }

  route_table_id            = each.value.route_table_id
  destination_cidr_block    = each.value.cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.portal.id
}
