"""UserNGFWStack - Composed stack for persistent per-user NGFW lifecycle.

This stack composes NGFWComponent + GWLBComponent to provide:
- Persistent NGFW EC2 instance with management and data ENIs
- Gateway Load Balancer for traffic steering
- VPC Endpoint Service for range connectivity
"""

from typing import Optional

import pulumi
from pulumi import Output

from components.ngfw_component import NGFWComponent
from components.gwlb_component import GWLBComponent


class UserNGFWStack(pulumi.ComponentResource):
    """Composed stack for user NGFW with GWLB.

    Creates:
    - NGFWComponent: EC2 instance with dual ENIs for NGFW
    - GWLBComponent: Gateway Load Balancer with endpoint service

    The NGFW data ENI is registered as a target in the GWLB target group.
    """

    def __init__(
        self,
        name: str,
        user_id: int,
        vpc_id: str,
        ngfw_subnet_id: str,
        ngfw_security_group_id: str,
        ami_id: str,
        bootstrap_bucket: str,
        instance_type: str = "m5.xlarge",
        environment: str = "dev",
        instance_profile_name: Optional[str] = None,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        """Initialize UserNGFWStack.

        Args:
            name: Resource name
            user_id: User ID for this NGFW stack
            vpc_id: VPC ID where resources are created
            ngfw_subnet_id: Subnet ID for NGFW ENIs
            ngfw_security_group_id: Security group ID for NGFW
            ami_id: VM-Series AMI ID
            bootstrap_bucket: S3 bucket for bootstrap configuration
            instance_type: EC2 instance type (default: m5.xlarge)
            environment: Environment name for tagging
            instance_profile_name: IAM instance profile name (optional)
            opts: Pulumi resource options
        """
        super().__init__("shifter:stacks:UserNGFWStack", name, None, opts)

        self.user_id = user_id

        # Create NGFW Component
        self.ngfw = NGFWComponent(
            f"{name}-ngfw",
            user_id=user_id,
            subnet_id=ngfw_subnet_id,
            security_group_id=ngfw_security_group_id,
            ami_id=ami_id,
            bootstrap_bucket=bootstrap_bucket,
            instance_type=instance_type,
            environment=environment,
            instance_profile_name=instance_profile_name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create GWLB Component
        self.gwlb = GWLBComponent(
            f"{name}-gwlb",
            user_id=user_id,
            subnet_ids=[ngfw_subnet_id],
            vpc_id=vpc_id,
            environment=environment,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Expose outputs from child components
        self.instance_id = self.ngfw.instance_id
        self.management_ip = self.ngfw.management_ip
        self.dataplane_ip = self.ngfw.dataplane_ip
        self.data_eni_id = self.ngfw.data_eni.id

        self.gwlb_arn = self.gwlb.gwlb_arn
        self.target_group_arn = self.gwlb.target_group_arn
        self.service_name = self.gwlb.service_name

        # Register outputs
        self.register_outputs({
            "user_id": user_id,
            "instance_id": self.instance_id,
            "management_ip": self.management_ip,
            "dataplane_ip": self.dataplane_ip,
            "data_eni_id": self.data_eni_id,
            "gwlb_arn": self.gwlb_arn,
            "target_group_arn": self.target_group_arn,
            "service_name": self.service_name,
        })

    def get_outputs(self) -> dict:
        """Get stack outputs as a dictionary.

        Returns:
            Dict with all stack outputs
        """
        return {
            "user_id": self.user_id,
            "instance_id": self.instance_id,
            "management_ip": self.management_ip,
            "dataplane_ip": self.dataplane_ip,
            "data_eni_id": self.data_eni_id,
            "gwlb_arn": self.gwlb_arn,
            "target_group_arn": self.target_group_arn,
            "service_name": self.service_name,
        }
