"""NGFW Add Rule Plan for creating security rules on the firewall.

This plan creates a PAN-OS security rule allowing traffic between
address objects (subnets). Used by CMS to configure routing policies.

Commands are executed via SSHExecutor to the NGFW management interface.
"""

from typing import Any, ClassVar

from plans.base import SetupStep

# PAN-OS configure mode commands for adding a security rule
# Variables: {{ rule_name }}, {{ src_address }}, {{ dst_address }}
ADD_RULE_INPUT = (
    "configure\n"
    "set rulebase security rules {{ rule_name }} from any to any source {{ src_address }} "
    "destination {{ dst_address }} application any service any action allow log-end yes "
    "log-setting XDR-Forward\n"
    "commit\n"
    "exit\n"
)


class NGFWAddRulePlan:
    """Plan for creating a security rule on the NGFW.

    Creates a PAN-OS security rule allowing traffic from source to destination.
    Both source and destination must be existing address objects.

    Steps:
    1. Create security rule with source/destination addresses

    Uses SSHExecutor to send CLI commands.
    """

    name: ClassVar[str] = "ngfw_add_rule"

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="add_rule",
            script="",
            stdin_input=ADD_RULE_INPUT,
            timeout_seconds=120,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_rule",
        script="show running security-policy | match {{ rule_name }}",
        timeout_seconds=30,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for rule creation.

        Args:
            instance: Object with rule_name, src_address, dst_address,
                     and management_ip attributes

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        rule_name = getattr(instance, "rule_name", None)
        if not rule_name:
            raise ValueError("Instance missing required 'rule_name' attribute")

        src_address = getattr(instance, "src_address", None)
        if not src_address:
            raise ValueError("Instance missing required 'src_address' attribute")

        dst_address = getattr(instance, "dst_address", None)
        if not dst_address:
            raise ValueError("Instance missing required 'dst_address' attribute")

        management_ip = getattr(instance, "management_ip", None)
        if not management_ip:
            raise ValueError("Instance missing required 'management_ip' attribute")

        return {
            "rule_name": rule_name,
            "src_address": src_address,
            "dst_address": dst_address,
            "management_ip": management_ip,
        }
