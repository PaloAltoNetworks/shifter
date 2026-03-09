"""NGFW Add Address Plan for creating address objects on the firewall.

This plan creates a PAN-OS address object representing a subnet CIDR.
Used by CMS to configure routing policies between logical subnets.

Commands are executed via SSHExecutor to the NGFW management interface.
"""

from typing import Any, ClassVar

from engine.provisioner.plans.base import SetupStep

# PAN-OS configure mode commands for adding an address object
# Variables: {{ name }}, {{ cidr }}
ADD_ADDRESS_INPUT = """configure
set address {{ name }} ip-netmask {{ cidr }}
commit
exit
"""


class NGFWAddAddressPlan:
    """Plan for creating an address object on the NGFW.

    Creates a PAN-OS address object that can be referenced in security rules.

    Steps:
    1. Create address object with name and CIDR

    Uses SSHExecutor to send CLI commands.
    """

    name: ClassVar[str] = "ngfw_add_address"

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="add_address",
            script="",
            stdin_input=ADD_ADDRESS_INPUT,
            timeout_seconds=120,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_address",
        script="show config running | match {{ name }}",
        timeout_seconds=30,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for address creation.

        Args:
            instance: Object with name, cidr, and management_ip attributes

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        name = getattr(instance, "name", None)
        if not name:
            raise ValueError("Instance missing required 'name' attribute")

        cidr = getattr(instance, "cidr", None)
        if not cidr:
            raise ValueError("Instance missing required 'cidr' attribute")

        management_ip = getattr(instance, "management_ip", None)
        if not management_ip:
            raise ValueError("Instance missing required 'management_ip' attribute")

        return {
            "name": name,
            "cidr": cidr,
            "management_ip": management_ip,
        }
