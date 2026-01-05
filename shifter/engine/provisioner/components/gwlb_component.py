"""Gateway Load Balancer component for UserNGFW traffic steering.

This component creates GWLB infrastructure for routing traffic from
range subnets through the NGFW:
- Gateway Load Balancer
- Target group with GENEVE protocol (port 6081)
- Listener
- VPC Endpoint Service
"""

import pulumi
import pulumi_aws as aws


class GWLBComponent(pulumi.ComponentResource):
    """Creates Gateway Load Balancer infrastructure for NGFW.

    Attributes:
        gwlb: The Gateway Load Balancer resource.
        target_group: The target group for NGFW instances.
        listener: The GWLB listener.
        endpoint_service: The VPC Endpoint Service.
        gwlb_arn: ARN of the Gateway Load Balancer.
        target_group_arn: ARN of the target group.
        service_name: Service name for VPC endpoints.
    """

    gwlb: aws.lb.LoadBalancer
    target_group: aws.lb.TargetGroup
    listener: aws.lb.Listener
    endpoint_service: aws.ec2.VpcEndpointService
    gwlb_arn: pulumi.Output[str]
    target_group_arn: pulumi.Output[str]
    service_name: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        user_id: int,
        subnet_ids: list[str],
        vpc_id: str,
        environment: str = "dev",
        opts: pulumi.ResourceOptions | None = None,
    ):
        """Create GWLB infrastructure.

        Args:
            name: Pulumi resource name prefix.
            user_id: User ID for tagging.
            subnet_ids: List of subnet IDs for GWLB placement.
            vpc_id: VPC ID for the target group.
            environment: Environment name for tagging.
            opts: Pulumi resource options.
        """
        super().__init__("shifter:ngfw:GWLBComponent", name, None, opts)

        tags = {
            "Name": f"{name}",
            "shifter:user_id": str(user_id),
            "shifter:environment": environment,
            "shifter:component": "gwlb",
        }

        # Create Gateway Load Balancer
        self.gwlb = aws.lb.LoadBalancer(
            f"{name}-gwlb",
            load_balancer_type="gateway",
            subnets=subnet_ids,
            tags=tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create target group with GENEVE protocol (port 6081)
        self.target_group = aws.lb.TargetGroup(
            f"{name}-tg",
            port=6081,
            protocol="GENEVE",
            vpc_id=vpc_id,
            target_type="instance",
            health_check=aws.lb.TargetGroupHealthCheckArgs(
                port="443",
                protocol="HTTPS",
                healthy_threshold=2,
                unhealthy_threshold=2,
                timeout=5,
                interval=10,
            ),
            tags=tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create listener
        self.listener = aws.lb.Listener(
            f"{name}-listener",
            load_balancer_arn=self.gwlb.arn,
            default_actions=[
                aws.lb.ListenerDefaultActionArgs(
                    type="forward",
                    target_group_arn=self.target_group.arn,
                )
            ],
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.gwlb, self.target_group]),
        )

        # Create VPC Endpoint Service with acceptance required
        self.endpoint_service = aws.ec2.VpcEndpointService(
            f"{name}-vpce-svc",
            acceptance_required=True,
            gateway_load_balancer_arns=[self.gwlb.arn],
            tags=tags,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.gwlb]),
        )

        # Export outputs
        self.gwlb_arn = self.gwlb.arn
        self.target_group_arn = self.target_group.arn
        self.service_name = self.endpoint_service.service_name

        # Register outputs
        self.register_outputs(
            {
                "gwlbArn": self.gwlb_arn,
                "targetGroupArn": self.target_group_arn,
                "serviceName": self.service_name,
            }
        )
