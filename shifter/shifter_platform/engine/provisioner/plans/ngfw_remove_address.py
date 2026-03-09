"""NGFW Remove Address Plan for deleting address objects from the firewall.

This plan deletes a PAN-OS address object.
Used by CMS when tearing down routing policies.

Commands are executed via SSHExecutor to the NGFW management interface.
"""

from typing import Any, ClassVar

from engine.provisioner.plans.base import SetupStep

# PAN-OS configure mode commands for removing an address object
# Variables: {{ name }}
REMOVE_ADDRESS_INPUT = """configure
delete address {{ name }}
commit
exit
"""


class NGFWRemoveAddressPlan:
    """Plan for deleting an address object from the NGFW.

    Removes a PAN-OS address object. Will fail if the address is still
    referenced by a security rule.

    Steps:
    1. Delete address object by name

    Uses SSHExecutor to send CLI commands.
    """

    name: ClassVar[str] = "ngfw_remove_address"

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="remove_address",
            script="",
            stdin_input=REMOVE_ADDRESS_INPUT,
            timeout_seconds=120,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_address_removed",
        script="show config running | match {{ name }}",
        timeout_seconds=30,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for address deletion.

        Args:
            instance: Object with name and management_ip attributes

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        name = getattr(instance, "name", None)
        if not name:
            raise ValueError("Instance missing required 'name' attribute")

        management_ip = getattr(instance, "management_ip", None)
        if not management_ip:
            raise ValueError("Instance missing required 'management_ip' attribute")

        return {
            "name": name,
            "management_ip": management_ip,
        }
