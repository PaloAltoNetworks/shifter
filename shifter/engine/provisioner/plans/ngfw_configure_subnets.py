"""NGFW Configure Subnets Plan for adding subnet address objects and rules.

This plan configures the NGFW with:
- Address objects for all subnets in a range
- Security rules based on connected_to relationships (bidirectional)

All configuration is done in a single commit for efficiency.

Commands are executed via SSHExecutor to the NGFW management interface.
"""

from typing import ClassVar

from plans.base import SetupStep


def build_connected_pairs(subnets: list[dict]) -> list[tuple[str, str]]:
    """Build deduplicated list of connected subnet pairs.

    Connection is symmetric: if A lists B OR B lists A, they're connected
    bidirectionally. Uses frozenset for O(1) deduplication.

    Args:
        subnets: List of subnet dicts with 'name' and 'connected_to' keys.

    Returns:
        List of (subnet_a, subnet_b) tuples, sorted alphabetically,
        with no duplicates.
    """
    subnet_names = {s["name"] for s in subnets}
    seen: set[frozenset[str]] = set()
    pairs: list[tuple[str, str]] = []

    for subnet in subnets:
        src = subnet["name"]
        for dst in subnet.get("connected_to", []):
            if dst not in subnet_names:
                continue  # Skip invalid references
            pair_key = frozenset([src, dst])
            if pair_key not in seen:
                seen.add(pair_key)
                # Sort for consistent naming
                a, b = sorted([src, dst])
                pairs.append((a, b))

    return pairs


def build_configure_input(subnets: list[dict], range_id: int) -> str:
    """Build PAN-OS configure commands for addresses and security rules.

    Args:
        subnets: List of dicts with 'name', 'cidr', and 'connected_to' keys.
        range_id: Range ID for unique naming.

    Returns:
        Multi-line string with configure commands and single commit.
    """
    lines = ["configure"]

    # Add address objects for each subnet
    for subnet in subnets:
        addr_name = f"range-{range_id}-{subnet['name']}"
        cidr = subnet["cidr"]
        lines.append(f"set address {addr_name} ip-netmask {cidr}")

    # Add bidirectional security rules for each connected pair
    for subnet_a, subnet_b in build_connected_pairs(subnets):
        addr_a = f"range-{range_id}-{subnet_a}"
        addr_b = f"range-{range_id}-{subnet_b}"

        # Rule A → B
        rule_ab = f"range-{range_id}-{subnet_a}-to-{subnet_b}"
        lines.append(
            f"set rulebase security rules {rule_ab} "
            f"from any to any source {addr_a} destination {addr_b} "
            "application any service any action allow "
            "log-end yes log-setting XDR-Forward"
        )

        # Rule B → A
        rule_ba = f"range-{range_id}-{subnet_b}-to-{subnet_a}"
        lines.append(
            f"set rulebase security rules {rule_ba} "
            f"from any to any source {addr_b} destination {addr_a} "
            "application any service any action allow "
            "log-end yes log-setting XDR-Forward"
        )

    lines.append("commit")
    lines.append("exit")
    return "\n".join(lines)


def build_remove_input(subnets: list[dict], range_id: int) -> str:
    """Build PAN-OS configure commands to remove addresses and rules.

    Rules deleted first since they reference addresses.

    Args:
        subnets: List of subnet dicts with 'name' and 'connected_to'.
        range_id: Range ID for naming.

    Returns:
        Multi-line string with delete commands and single commit.
    """
    lines = ["configure"]

    # Delete rules first (they reference addresses)
    for subnet_a, subnet_b in build_connected_pairs(subnets):
        rule_ab = f"range-{range_id}-{subnet_a}-to-{subnet_b}"
        rule_ba = f"range-{range_id}-{subnet_b}-to-{subnet_a}"
        lines.append(f"delete rulebase security rules {rule_ab}")
        lines.append(f"delete rulebase security rules {rule_ba}")

    # Delete address objects
    for subnet in subnets:
        lines.append(f"delete address range-{range_id}-{subnet['name']}")

    lines.append("commit")
    lines.append("exit")
    return "\n".join(lines)


class NGFWConfigureSubnetsPlan:
    """Plan for configuring subnet address objects and rules on the NGFW.

    Creates PAN-OS address objects and security rules for each subnet
    in a range. All config is done in a single commit for efficiency.

    The stdin_input is dynamically built from the subnets list and range_id.
    """

    name: ClassVar[str] = "ngfw_configure_subnets"

    # Steps are built dynamically since stdin_input depends on subnet count
    steps: ClassVar[list[SetupStep]] = []

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_config",
        script="show config running | match range-",
        timeout_seconds=30,
        is_verification=True,
    )

    def get_steps(self, subnets: list[dict], range_id: int) -> list[SetupStep]:
        """Build steps with dynamic stdin_input for the given subnets.

        Args:
            subnets: List of subnet dicts with 'name', 'cidr', 'connected_to'.
            range_id: Range ID for unique naming.

        Returns:
            List with single SetupStep containing all configure commands.
        """
        stdin_input = build_configure_input(subnets, range_id)
        return [
            SetupStep(
                name="configure_subnets",
                script="",
                stdin_input=stdin_input,
                timeout_seconds=300,  # 5 min for config + commit
            ),
        ]


class NGFWRemoveSubnetsPlan:
    """Plan for removing subnet address objects and rules from the NGFW.

    Deletes PAN-OS security rules first, then address objects.
    All deletes are done in a single commit for efficiency.
    """

    name: ClassVar[str] = "ngfw_remove_subnets"

    steps: ClassVar[list[SetupStep]] = []

    def get_steps(self, subnets: list[dict], range_id: int) -> list[SetupStep]:
        """Build steps with dynamic stdin_input for removing subnets.

        Args:
            subnets: List of subnet dicts with 'name' and 'connected_to'.
            range_id: Range ID for naming.

        Returns:
            List with single SetupStep containing all delete commands.
        """
        stdin_input = build_remove_input(subnets, range_id)
        return [
            SetupStep(
                name="remove_subnets",
                script="",
                stdin_input=stdin_input,
                timeout_seconds=300,
            ),
        ]
