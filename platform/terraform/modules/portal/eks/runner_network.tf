# GitHub Actions runner -> EKS control-plane peering.
#
# The eks-deploy bundle step and the post-deploy smoke run on the self-hosted
# runner fleet, which lives in its own VPC (shifter-github-runner-vpc). The EKS
# API endpoint is private-only (endpoint_public_access = false) and its Route 53
# hosted zone is service-owned (OwningService eks.amazonaws.com), so it cannot be
# associated with the runner VPC and the runner cannot resolve the endpoint by
# name. Rather than open public ingress or stand up ~$180/mo Route 53 Resolver
# endpoints, the deploy reaches the API by IP: it resolves the control-plane ENI
# IPs via the AWS API and connects with tls-server-name set to the endpoint host.
# This peering plus the cluster-SG ingress rule below give the runner that private
# path with no public exposure. The runner VPC is name-discoverable, mirroring
# portal_network.tf.

data "aws_vpc" "runner" {
  tags = {
    Name = "shifter-github-runner-vpc"
  }
}

data "aws_route_tables" "runner" {
  vpc_id = data.aws_vpc.runner.id

  filter {
    name   = "tag:Name"
    values = ["shifter-github-runner-runner-rt"]
  }
}

resource "aws_vpc_peering_connection" "runner" {
  vpc_id      = aws_vpc.this.id
  peer_vpc_id = data.aws_vpc.runner.id
  auto_accept = true
  tags        = merge(var.tags, { Name = "${var.cluster_name}-github-runner" })

  lifecycle {
    precondition {
      condition = (
        cidrhost("${cidrhost(data.aws_vpc.runner.cidr_block, 0)}/${split("/", var.vpc_cidr)[1]}", 0) != cidrhost(var.vpc_cidr, 0) &&
        cidrhost("${cidrhost(var.vpc_cidr, 0)}/${split("/", data.aws_vpc.runner.cidr_block)[1]}", 0) != cidrhost(data.aws_vpc.runner.cidr_block, 0)
      )
      error_message = "Runner peering requires disjoint EKS and runner networks."
    }
  }
}

# Runner-side route: the runner subnet reaches the EKS VPC (control-plane ENIs +
# nodes) through the peering. The EKS-side return route to the runner CIDR lives
# on aws_route_table.private (network.tf).
resource "aws_route" "runner_to_eks" {
  for_each = toset(data.aws_route_tables.runner.ids)

  route_table_id            = each.value
  destination_cidr_block    = var.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.runner.id
}

# Let the runner reach the private Kubernetes API (443) on the cluster security
# group (the endpoint ENIs carry it). Scoped to the dedicated runner VPC CIDR;
# this is the only ingress the deploy/smoke path needs and adds no public access.
resource "aws_vpc_security_group_ingress_rule" "runner_to_api" {
  security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  description       = "GitHub Actions runner VPC to the private Kubernetes API"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = data.aws_vpc.runner.cidr_block
}
