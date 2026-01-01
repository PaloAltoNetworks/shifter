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

    def run_provision(self, orchestrator):
        """Post-Pulumi provisioning via SetupOrchestrator.

        Wait for SSH, verify device cert, configure XDR logging.

        Args:
            orchestrator: SetupOrchestrator instance to execute provisioning plans

        Returns:
            Result from orchestrator
        """
        from plans.ngfw_provision import NGFWProvisionPlan
        from plans.gwlb_setup import GWLBSetupPlan

        # Run NGFW provision plan (wait for SSH, configure XDR)
        provision_plan = NGFWProvisionPlan()
        provision_result = orchestrator.orchestrate(provision_plan, self)

        if not provision_result.success:
            return provision_result

        # Run GWLB setup plan (register target)
        gwlb_plan = GWLBSetupPlan()
        gwlb_result = orchestrator.orchestrate(gwlb_plan, self)

        return gwlb_result

    def run_deprovision(self, orchestrator):
        """Cleanup with license deactivation.

        Deactivates VM-Series license before termination.

        Args:
            orchestrator: SetupOrchestrator instance to execute deprovision plan

        Returns:
            Result from orchestrator
        """
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        deprovision_plan = NGFWDeprovisionPlan()
        return orchestrator.orchestrate(deprovision_plan, self)

    def run_ops(self, operation: str, orchestrator, **kwargs):
        """Runtime operations via OpsOrchestrator.

        Operations: start, stop, add-route, remove-route, reconcile, sweep

        Args:
            operation: Operation name (start, stop, add-route, remove-route, reconcile, sweep)
            orchestrator: OpsOrchestrator instance to execute ops plans
            **kwargs: Additional parameters for the operation

        Returns:
            Result from orchestrator

        Raises:
            ValueError: If unknown operation requested
        """
        operation_plans = {
            "start": "plans.ngfw_start.NGFWStartPlan",
            "stop": "plans.ngfw_stop.NGFWStopPlan",
            "add-route": "plans.gwlb_add_route.GWLBAddRoutePlan",
            "remove-route": "plans.gwlb_remove_route.GWLBRemoveRoutePlan",
            "reconcile": "plans.ngfw_reconcile.NGFWReconcilePlan",
            "sweep": "plans.user_ngfw_stack_sweep.UserNGFWStackSweepPlan",
        }

        if operation not in operation_plans:
            raise ValueError(f"Unknown operation: {operation}. Valid operations: {list(operation_plans.keys())}")

        # Dynamic import of plan class
        plan_path = operation_plans[operation]
        module_path, class_name = plan_path.rsplit(".", 1)

        import importlib
        module = importlib.import_module(module_path)
        plan_class = getattr(module, class_name)

        plan = plan_class()
        return orchestrator.orchestrate(plan, self, **kwargs)
