"""Pulumi program entry point for Shifter provisioning.

This is the main Pulumi program that gets executed when running `pulumi up`.
It detects the stack type from config and creates the appropriate resources:
- Range stack: Creates cyber range with attacker/victim instances
- NGFW stack: Creates VM-Series NGFW with GWLB for traffic inspection
"""

import pulumi

from config import load_config, load_ngfw_config
from stacks import RangeStack
from stacks.user_ngfw_stack import UserNGFWStack


def main() -> None:
    """Main entry point for Pulumi program.

    Detects stack type from Pulumi config:
    - If requestId is set: NGFW provisioning
    - If rangeId is set: Range provisioning
    """
    config = pulumi.Config()

    # Check which type of stack to create based on config
    request_id = config.get("requestId")

    if request_id:
        # NGFW provisioning path
        _provision_ngfw()
    else:
        # Range provisioning path (existing behavior)
        _provision_range()


def _provision_ngfw() -> None:
    """Provision NGFW stack (UserNGFWStack)."""
    config = load_ngfw_config()

    # Create the NGFW stack
    ngfw_stack = UserNGFWStack(
        f"ngfw-{config.request_id}",
        user_id=config.user_id,
        vpc_id=config.vpc_id,
        ngfw_subnet_id=config.subnet_id,
        ngfw_security_group_id=config.security_group_id,
        ami_id=config.ami_id,
        bootstrap_bucket=config.bootstrap_bucket,
        scm_pin_id=config.scm_pin_id,
        scm_pin_value=config.scm_pin_value,
        scm_folder_name=config.scm_folder_name,
        authcode=config.authcode,
        instance_type=config.instance_type,
        environment=config.environment,
        instance_profile_name=config.instance_profile_name or None,
    )

    # Export outputs for main.py to read after pulumi up
    pulumi.export("instance_id", ngfw_stack.instance_id)
    pulumi.export("management_ip", ngfw_stack.management_ip)
    pulumi.export("dataplane_ip", ngfw_stack.dataplane_ip)
    pulumi.export("gwlb_arn", ngfw_stack.gwlb_arn)
    pulumi.export("target_group_arn", ngfw_stack.target_group_arn)
    pulumi.export("service_name", ngfw_stack.service_name)


def _provision_range() -> None:
    """Provision Range stack (RangeStack)."""
    config = load_config()

    # Create the range stack
    range_stack = RangeStack(
        f"range-{config.range_id}",
        config=config,
    )

    # Export outputs for the container entrypoint to read
    pulumi.export("subnet_id", range_stack.subnet_id)
    pulumi.export("subnet_cidr", range_stack.subnet_cidr)

    # Export instance details using stored role/os_type from each instance
    # (not index-based lookup - instance order may differ from config order)
    instances_output = []
    for inst in range_stack.instances:
        instances_output.append(
            {
                "role": inst.role,
                "os": inst.os_type,
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
                "ssh_key_secret_arn": inst.ssh_key_secret_arn,
            }
        )

    pulumi.export("instances", instances_output)


# Run the main function
main()
