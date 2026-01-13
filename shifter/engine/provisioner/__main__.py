"""Pulumi program entry point for Shifter provisioning.

This is the main Pulumi program that gets executed when running `pulumi up`.
It detects the stack type from config and creates the appropriate resources:
- Range stack: Creates cyber range with attacker/victim instances
- NGFW stack: Creates VM-Series NGFW with GWLB for traffic inspection
"""

from __future__ import annotations

import logging
from typing import Any

import pulumi

from config import load_config, load_ngfw_config
from stacks import RangeStack
from stacks.user_ngfw_stack import UserNGFWStack

logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point for Pulumi program.

    Detects stack type from Pulumi config:
    - If requestId is set: NGFW provisioning
    - If rangeId is set: Range provisioning
    """
    config = pulumi.Config()

    # Check which type of stack to create based on config
    request_id = config.get("requestId")
    range_id = config.get("rangeId")

    logger.debug("main: request_id=%s range_id=%s", request_id, range_id)

    if request_id:
        # NGFW provisioning path
        logger.info("main: dispatching to NGFW provisioning for request_id=%s", request_id)
        _provision_ngfw()
    else:
        # Range provisioning path (existing behavior)
        logger.info("main: dispatching to Range provisioning for range_id=%s", range_id)
        _provision_range()


def _provision_ngfw() -> None:
    """Provision NGFW stack (UserNGFWStack)."""
    config = load_ngfw_config()

    logger.debug(
        "_provision_ngfw: config loaded request_id=%s instance_uuid=%s user_id=%s",
        config.request_id,
        config.instance_uuid,
        config.user_id,
    )

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

    logger.info("_provision_ngfw: UserNGFWStack created for request_id=%s", config.request_id)

    # Export outputs for main.py to read after pulumi up
    # Keys must match what main.py reads via output_data.get()
    pulumi.export("ec2_instance_id", ngfw_stack.ec2_instance_id)
    pulumi.export("management_ip", ngfw_stack.management_ip)
    pulumi.export("dataplane_ip", ngfw_stack.dataplane_ip)
    pulumi.export("ssh_key_secret_arn", ngfw_stack.ssh_key_secret_arn)
    pulumi.export("gwlb_arn", ngfw_stack.gwlb_arn)
    pulumi.export("target_group_arn", ngfw_stack.target_group_arn)
    pulumi.export("service_name", ngfw_stack.service_name)

    logger.debug("_provision_ngfw: exports registered")


def _provision_range() -> None:
    """Provision Range stack (RangeStack)."""
    config = load_config()

    logger.debug(
        "_provision_range: config loaded range_id=%s request_uuid=%s subnet_count=%d",
        config.range_id,
        config.request_uuid,
        len(config.subnets),
    )

    # Create the range stack
    range_stack = RangeStack(
        f"range-{config.range_id}",
        config=config,
    )

    logger.info(
        "_provision_range: RangeStack created range_id=%s networks=%d instances=%d",
        config.range_id,
        len(range_stack.networks),
        len(range_stack.instances),
    )

    # Build lookup for subnet UUIDs from config
    subnet_uuid_lookup = {s.name: s.uuid for s in config.subnets}

    # Export subnets dict with per-subnet details including UUID for DB correlation
    subnets_output: dict[str, dict[str, pulumi.Output[str] | str]] = {}
    for subnet_name, network in range_stack.networks.items():
        subnet_uuid = subnet_uuid_lookup.get(subnet_name, "")
        if not subnet_uuid:
            logger.warning("_provision_range: missing UUID for subnet_name=%s in config", subnet_name)
        subnets_output[subnet_name] = {
            "uuid": subnet_uuid,
            "subnet_id": network.subnet_id,
            "subnet_cidr": network.subnet_cidr,
            "security_group_id": network.security_group_id,
            "route_table_id": network.route_table_id,
            "gwlb_endpoint_id": network.gwlb_endpoint_id,
        }
    pulumi.export("subnets", subnets_output)

    # Export instance details with UUID for DB correlation
    # range_stack.instances is list[tuple[InstanceComponent, str]]
    # InstanceComponent.uuid holds the instance UUID directly (no lookup needed)
    instances_output: list[dict[str, Any]] = []
    for inst, subnet_name in range_stack.instances:
        instances_output.append(
            {
                "uuid": inst.uuid,
                "role": inst.role,
                "os": inst.os_type,
                "subnet_name": subnet_name,
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
                "ssh_key_secret_arn": inst.ssh_key_secret_arn,
            }
        )

    pulumi.export("instances", instances_output)

    logger.debug(
        "_provision_range: exports registered subnets=%d instances=%d",
        len(subnets_output),
        len(instances_output),
    )


# Run the main function
main()
