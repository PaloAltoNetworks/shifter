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
        ngfw_mgmt_security_group_id=config.mgmt_security_group_id,
        ngfw_data_security_group_id=config.data_security_group_id,
        ami_id=config.ami_id,
        bootstrap_bucket=config.bootstrap_bucket,
        scm_pin_id=config.scm_pin_id,
        scm_pin_value=config.scm_pin_value,
        scm_folder_name=config.scm_folder_name,
        authcode=config.authcode,
        request_uuid=config.request_id,
        instance_uuid=config.instance_uuid,
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

    # Build lookup for subnet UUIDs from config
    subnet_uuid_lookup = {s.name: s.uuid for s in config.subnets}

    # Export subnets dict with per-subnet details including UUID for DB correlation
    subnets_output: dict[str, dict[str, pulumi.Output[str] | str]] = {}
    for subnet_name, network in range_stack.networks.items():
        subnets_output[subnet_name] = {
            "uuid": subnet_uuid_lookup.get(subnet_name, ""),
            "subnet_id": network.subnet_id,
            "subnet_cidr": network.subnet_cidr,
            "security_group_id": network.security_group_id,
            "route_table_id": network.route_table_id,
            "gwlb_endpoint_id": network.gwlb_endpoint_id,
        }
    pulumi.export("subnets", subnets_output)

    # Build lookup for instance UUIDs from config
    instance_uuid_lookup: dict[tuple[str, str], str] = {}
    for subnet_config in config.subnets:
        for inst in subnet_config.instances:
            instance_uuid_lookup[(subnet_config.name, inst.role)] = inst.uuid

    # Export instance details with UUID for DB correlation
    # range_stack.instances is list[tuple[InstanceComponent, str]]
    instances_output = []
    for inst, subnet_name in range_stack.instances:
        instances_output.append(
            {
                "uuid": instance_uuid_lookup.get((subnet_name, inst.role), ""),
                "role": inst.role,
                "os": inst.os_type,
                "subnet_name": subnet_name,
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
                "ssh_key_secret_arn": inst.ssh_key_secret_arn,
            }
        )

    pulumi.export("instances", instances_output)


# Run the main function
main()
