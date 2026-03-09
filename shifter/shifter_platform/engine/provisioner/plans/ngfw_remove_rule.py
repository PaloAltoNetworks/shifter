"""NGFW Remove Rule Plan for deleting security rules from the firewall.

This plan deletes a PAN-OS security rule.
Used by CMS when tearing down routing policies.

Commands are executed via SSHExecutor to the NGFW management interface.
"""

from typing import Any, ClassVar

from engine.provisioner.plans.base import SetupStep

# PAN-OS configure mode commands for removing a security rule
# Variables: {{ rule_name }}
REMOVE_RULE_INPUT = """configure
delete rulebase security rules {{ rule_name }}
commit
exit
"""


class NGFWRemoveRulePlan:
    """Plan for deleting a security rule from the NGFW.

    Removes a PAN-OS security rule by name.

    Steps:
    1. Delete security rule by name

    Uses SSHExecutor to send CLI commands.
    """

    name: ClassVar[str] = "ngfw_remove_rule"

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="remove_rule",
            script="",
            stdin_input=REMOVE_RULE_INPUT,
            timeout_seconds=120,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_rule_removed",
        script="show running security-policy | match {{ rule_name }}",
        timeout_seconds=30,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for rule deletion.

        Args:
            instance: Object with rule_name and management_ip attributes

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        rule_name = getattr(instance, "rule_name", None)
        if not rule_name:
            raise ValueError("Instance missing required 'rule_name' attribute")

        management_ip = getattr(instance, "management_ip", None)
        if not management_ip:
            raise ValueError("Instance missing required 'management_ip' attribute")

        return {
            "rule_name": rule_name,
            "management_ip": management_ip,
        }
