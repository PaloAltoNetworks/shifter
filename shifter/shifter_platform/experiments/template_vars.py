"""Template variable parsing, validation, and resolution for experiment prompts.

Template variables use double-brace syntax: {{InstanceName.property}}

Supported properties:
  - ip: Private IP address of the instance
  - name: Display name of the instance

Example:
  "Attack the workstation at {{Workstation.ip}} using credentials from {{DC.ip}}"
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Match {{InstanceName.property}} — captures instance name and property
TEMPLATE_VAR_PATTERN = re.compile(r"\{\{(\w+)\.(\w+)\}\}")

# Allowed properties for template variables
ALLOWED_PROPERTIES = {"ip", "name"}


def extract_variables(template: str) -> list[tuple[str, str]]:
    """Extract all template variables from a string.

    Args:
        template: String potentially containing {{Instance.property}} variables.

    Returns:
        List of (instance_name, property) tuples.
    """
    return TEMPLATE_VAR_PATTERN.findall(template)


def validate_template(template: str, instance_names: set[str]) -> list[str]:
    """Validate all template variables reference valid instances and properties.

    Args:
        template: String with template variables.
        instance_names: Set of valid instance names from the scenario.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors: list[str] = []
    variables = extract_variables(template)

    for instance_name, prop in variables:
        if instance_name not in instance_names:
            errors.append(f"Unknown instance '{instance_name}' in template variable")
        if prop not in ALLOWED_PROPERTIES:
            errors.append(f"Unknown property '{prop}' — allowed: {ALLOWED_PROPERTIES}")

    return errors


def resolve_template(template: str, instance_data: dict[str, dict[str, Any]]) -> str:
    """Replace template variables with actual runtime values.

    Args:
        template: String with {{Instance.property}} variables.
        instance_data: Dict mapping instance names to their properties.
            Example: {"Workstation": {"ip": "10.1.1.5", "name": "Workstation"}}

    Returns:
        String with variables replaced by actual values.

    Raises:
        ValueError: If a variable cannot be resolved.
    """
    def replacer(match: re.Match) -> str:
        instance_name = match.group(1)
        prop = match.group(2)

        if instance_name not in instance_data:
            msg = f"Cannot resolve {{{{{instance_name}.{prop}}}}}: instance not found"
            logger.error("resolve_template: %s", msg)
            raise ValueError(msg)

        instance = instance_data[instance_name]
        if prop not in instance:
            msg = f"Cannot resolve {{{{{instance_name}.{prop}}}}}: property not found"
            logger.error("resolve_template: %s", msg)
            raise ValueError(msg)

        value = str(instance[prop])
        logger.debug("resolve_template: {{%s.%s}} -> %s", instance_name, prop, value)
        return value

    resolved = TEMPLATE_VAR_PATTERN.sub(replacer, template)
    logger.debug("resolve_template: resolved %d variables", len(extract_variables(template)))
    return resolved


def build_instance_data(provisioned_instances: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build template variable data from provisioned range instances.

    The provisioned_instances dict comes from Range.provisioned_instances,
    which maps instance names to their details after provisioning.

    Args:
        provisioned_instances: Dict from Range.provisioned_instances.
            Expected format: {"Workstation": {"private_ip": "10.1.1.5", ...}}

    Returns:
        Dict mapping instance names to template-resolvable properties.
    """
    result: dict[str, dict[str, Any]] = {}

    for name, details in provisioned_instances.items():
        if isinstance(details, dict):
            result[name] = {
                "ip": details.get("private_ip", ""),
                "name": name,
            }
        else:
            logger.warning("build_instance_data: unexpected format for instance %s", name)
            result[name] = {"ip": "", "name": name}

    logger.debug("build_instance_data: built data for %d instances", len(result))
    return result
