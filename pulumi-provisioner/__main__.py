"""Pulumi program entry point for Shifter range provisioning.

This is the main Pulumi program that gets executed when running `pulumi up`.
It loads configuration and creates a complete range using the RangeStack component.
"""

import pulumi

from components import RangeStack
from config import load_config


def main() -> None:
    """Main entry point for Pulumi program."""
    # Load configuration from Pulumi config and database
    config = load_config()

    # Create the range stack
    range_stack = RangeStack(
        f"range-{config.range_id}",
        config=config,
    )

    # Export outputs for the container entrypoint to read
    pulumi.export("subnet_id", range_stack.subnet_id)
    pulumi.export("subnet_cidr", range_stack.subnet_cidr)

    # Export instance details
    instances_output = []
    for i, inst in enumerate(range_stack.instances):
        inst_config = config.instances[i]
        instances_output.append(
            {
                "role": inst_config.role,
                "os": inst_config.os_type,
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
                "ssh_key_secret_arn": inst.ssh_key_secret_arn,
            }
        )

    pulumi.export("instances", instances_output)


# Run the main function
main()
