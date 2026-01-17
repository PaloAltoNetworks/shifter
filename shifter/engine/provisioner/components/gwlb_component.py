"""Gateway Load Balancer component for UserNGFW traffic steering.

This component creates GWLB infrastructure for routing traffic from
range subnets through the NGFW:
- Gateway Load Balancer
- Target group with GENEVE protocol (port 6081)
- Listener
- VPC Endpoint Service
"""

import logging

import pulumi
import pulumi_aws as aws

logger = logging.getLogger(__name__)


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
        request_uuid: str,
        instance_uuid: str,
        environment: str = "dev",
        opts: pulumi.ResourceOptions | None = None,
    ):
        """Create GWLB infrastructure.

        Args:
            name: Pulumi resource name prefix.
            user_id: User ID for tagging.
            subnet_ids: List of subnet IDs for GWLB placement.
            vpc_id: VPC ID for the target group.
            request_uuid: UUID of the provisioning request (for tagging/correlation).
            instance_uuid: UUID of the associated NGFW instance (for lifecycle grouping).
            environment: Environment name for tagging.
            opts: Pulumi resource options.

        Raises:
            ValueError: If required uuid parameters are missing.
        """
        super().__init__("shifter:ngfw:GWLBComponent", name, None, opts)

        logger.debug(
            "__init__: name=%s user_id=%s instance_uuid=%s request_uuid=%s",
            name,
            user_id,
            instance_uuid,
            request_uuid,
        )

        # Validate required UUID parameters
        if not request_uuid:
            raise ValueError("request_uuid is required for GWLBComponent")
        if not instance_uuid:
            raise ValueError("instance_uuid is required for GWLBComponent")

        # Store instance_uuid for output building
        self._instance_uuid = instance_uuid

        # Build common tags using shared helper
        from components.tags import build_common_tags

        tags = build_common_tags(
            user_id=user_id,
            environment=environment,
            request_uuid=request_uuid,
            unit_type="instance",
            unit_uuid=instance_uuid,
            component="gwlb",
        )
        tags["Name"] = name

        # Generate short names for AWS resources (max 32 chars for LB/TG)
        # Use first 8 chars of instance_uuid for uniqueness
        short_id = instance_uuid[:8] if instance_uuid else "unknown"
        short_lb_name = f"ngfw-{short_id}-gwlb"  # 18 chars
        short_tg_name = f"ngfw-{short_id}-tg"  # 15 chars

        # Create Gateway Load Balancer
        self.gwlb = aws.lb.LoadBalancer(
            f"{name}-gwlb",
            name=short_lb_name,
            load_balancer_type="gateway",
            subnets=subnet_ids,
            tags=tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create target group with GENEVE protocol (port 6081)
        self.target_group = aws.lb.TargetGroup(
            f"{name}-tg",
            name=short_tg_name,
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

        # Create VPC Endpoint Service with auto-accept (same account)
        self.endpoint_service = aws.ec2.VpcEndpointService(
            f"{name}-vpce-svc",
            acceptance_required=False,
            gateway_load_balancer_arns=[self.gwlb.arn],
            tags=tags,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.gwlb]),
        )

        # Export outputs
        self.gwlb_arn = self.gwlb.arn
        self.target_group_arn = self.target_group.arn
        self.service_name = self.endpoint_service.service_name

        logger.info(
            "__init__: created GWLBComponent name=%s user_id=%s instance_uuid=%s",
            name,
            user_id,
            instance_uuid,
        )

        # Register outputs
        self.register_outputs(
            {
                "gwlbArn": self.gwlb_arn,
                "targetGroupArn": self.target_group_arn,
                "serviceName": self.service_name,
            }
        )

    @property
    def uuid(self) -> str:
        """Return the associated NGFW instance UUID for correlation."""
        return self._instance_uuid
