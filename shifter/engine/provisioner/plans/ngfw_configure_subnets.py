"""NGFW Configure Subnets Plan for adding subnet address objects and rules.

This plan configures the NGFW with:
- Static routes for each subnet (via VPC gateway)
- Address objects for all subnets in a range
- Security rules based on connected_to relationships (bidirectional)
  - Rules attach ALERT_PROFILE_GROUP for threat detection without blocking
  - Rules use XDR-Forward log-setting for cloud logging

All configuration is done in a single commit for efficiency.

Commands are executed via SSHExecutor to the NGFW management interface.
"""

from typing import ClassVar

from plans.base import SetupStep
from plans.ngfw_provision import ALERT_PROFILE_GROUP


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


def build_configure_input(
    subnets: list[dict],
    range_id: int,
    route_next_hop_ip: str,
    stale_routes_to_delete: list[str] | None = None,
    ssm_endpoints_subnet_cidr: str = "",
    route_interface: str = "ethernet1/1",
) -> str:
    """Build PAN-OS configure commands for routes, addresses and security rules.

    Args:
        subnets: List of dicts with 'name', 'cidr', and 'connected_to' keys.
        range_id: Range ID for unique naming.
        route_next_hop_ip: Next-hop IP address for static route configuration.
        stale_routes_to_delete: Optional list of existing route names to delete first.
            Used to clean up stale routes from destroyed ranges that reused CIDRs.
        ssm_endpoints_subnet_cidr: SSM/Bedrock endpoints subnet CIDR. When set,
            adds a route and allow-all rule so Bedrock traffic passes through NGFW.
        route_interface: PAN-OS interface to use for the static routes.

    Returns:
        Multi-line string with configure commands and single commit.
    """
    lines = ["configure"]

    # Revert any pending changes from previous failed attempts
    # This clears the candidate config to avoid accumulating stale routes
    lines.append("revert config")

    # Delete any stale routes that conflict with our CIDRs (from recycled allocations)
    if stale_routes_to_delete:
        for route_name in stale_routes_to_delete:
            lines.append(f"delete network virtual-router default routing-table ip static-route {route_name}")

    # Add static routes for each subnet (routes must exist for traffic to flow)
    for subnet in subnets:
        route_name = f"range-{range_id}-{subnet['name']}"
        cidr = subnet["cidr"]
        lines.append(
            f"set network virtual-router default routing-table ip static-route "
            f"{route_name} destination {cidr} interface {route_interface} "
            f"nexthop ip-address {route_next_hop_ip}"
        )

    # Add static route for SSM/Bedrock endpoints subnet so NGFW can forward traffic
    if ssm_endpoints_subnet_cidr:
        endpoints_route = f"range-{range_id}-endpoints"
        lines.append(
            f"set network virtual-router default routing-table ip static-route "
            f"{endpoints_route} destination {ssm_endpoints_subnet_cidr} interface {route_interface} "
            f"nexthop ip-address {route_next_hop_ip}"
        )

    # Add address objects for each subnet
    for subnet in subnets:
        addr_name = f"range-{range_id}-{subnet['name']}"
        cidr = subnet["cidr"]
        lines.append(f"set address {addr_name} ip-netmask {cidr}")

    # Add address object for endpoints subnet
    if ssm_endpoints_subnet_cidr:
        lines.append(f"set address range-{range_id}-endpoints ip-netmask {ssm_endpoints_subnet_cidr}")

    # Add bidirectional security rules for each connected pair
    # Rules use 'ranges' zone (created during NGFW provisioning)
    # Profile-group attaches alert-only threat detection (created during NGFW provisioning)
    for subnet_a, subnet_b in build_connected_pairs(subnets):
        addr_a = f"range-{range_id}-{subnet_a}"
        addr_b = f"range-{range_id}-{subnet_b}"

        # Rule A → B
        rule_ab = f"range-{range_id}-{subnet_a}-to-{subnet_b}"
        lines.append(
            f"set rulebase security rules {rule_ab} "
            f"from ranges to ranges source {addr_a} destination {addr_b} "
            "application any service any action allow "
            f"log-end yes log-setting XDR-Forward profile-setting group {ALERT_PROFILE_GROUP}"
        )

        # Rule B → A
        rule_ba = f"range-{range_id}-{subnet_b}-to-{subnet_a}"
        lines.append(
            f"set rulebase security rules {rule_ba} "
            f"from ranges to ranges source {addr_b} destination {addr_a} "
            "application any service any action allow "
            f"log-end yes log-setting XDR-Forward profile-setting group {ALERT_PROFILE_GROUP}"
        )

    # Add allow-all rules from each range subnet to/from endpoints subnet
    # This ensures Bedrock/SSM/STS traffic passes through NGFW with logging
    if ssm_endpoints_subnet_cidr:
        endpoints_addr = f"range-{range_id}-endpoints"
        for subnet in subnets:
            addr_name = f"range-{range_id}-{subnet['name']}"

            # Subnet → Endpoints
            rule_to = f"range-{range_id}-{subnet['name']}-to-endpoints"
            lines.append(
                f"set rulebase security rules {rule_to} "
                f"from ranges to ranges source {addr_name} destination {endpoints_addr} "
                "application any service any action allow "
                f"log-end yes log-setting XDR-Forward profile-setting group {ALERT_PROFILE_GROUP}"
            )

            # Endpoints → Subnet (return traffic)
            rule_from = f"range-{range_id}-endpoints-to-{subnet['name']}"
            lines.append(
                f"set rulebase security rules {rule_from} "
                f"from ranges to ranges source {endpoints_addr} destination {addr_name} "
                "application any service any action allow "
                f"log-end yes log-setting XDR-Forward profile-setting group {ALERT_PROFILE_GROUP}"
            )

    lines.append("commit")
    lines.append("exit")
    return "\n".join(lines)


def build_remove_input(subnets: list[dict], range_id: int, has_endpoints: bool = False) -> str:
    """Build PAN-OS configure commands to remove routes, addresses and rules.

    Deletion order: rules first (reference addresses), then addresses, then routes.

    Args:
        subnets: List of subnet dicts with 'name' and 'connected_to'.
        range_id: Range ID for naming.
        has_endpoints: Whether endpoints subnet config was added (route, address, rules).

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

    # Delete endpoints security rules
    if has_endpoints:
        for subnet in subnets:
            rule_to = f"range-{range_id}-{subnet['name']}-to-endpoints"
            rule_from = f"range-{range_id}-endpoints-to-{subnet['name']}"
            lines.append(f"delete rulebase security rules {rule_to}")
            lines.append(f"delete rulebase security rules {rule_from}")

    # Delete address objects
    for subnet in subnets:
        lines.append(f"delete address range-{range_id}-{subnet['name']}")

    # Delete endpoints address object
    if has_endpoints:
        lines.append(f"delete address range-{range_id}-endpoints")

    # Delete static routes
    for subnet in subnets:
        route_name = f"range-{range_id}-{subnet['name']}"
        lines.append(f"delete network virtual-router default routing-table ip static-route {route_name}")

    # Delete endpoints static route
    if has_endpoints:
        lines.append(f"delete network virtual-router default routing-table ip static-route range-{range_id}-endpoints")

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

    def get_steps(
        self,
        subnets: list[dict],
        range_id: int,
        route_next_hop_ip: str,
        stale_routes_to_delete: list[str] | None = None,
        ssm_endpoints_subnet_cidr: str = "",
        route_interface: str = "ethernet1/1",
    ) -> list[SetupStep]:
        """Build steps with dynamic stdin_input for the given subnets.

        Args:
            subnets: List of subnet dicts with 'name', 'cidr', 'connected_to'.
            range_id: Range ID for unique naming.
            route_next_hop_ip: Next-hop IP address for static route configuration.
            stale_routes_to_delete: Optional list of stale route names to delete first.
            ssm_endpoints_subnet_cidr: SSM/Bedrock endpoints subnet CIDR for NGFW routing.
            route_interface: PAN-OS interface to use for the static routes.

        Returns:
            List with single SetupStep containing all configure commands.
        """
        stdin_input = build_configure_input(
            subnets,
            range_id,
            route_next_hop_ip,
            stale_routes_to_delete,
            ssm_endpoints_subnet_cidr,
            route_interface,
        )
        return [
            SetupStep(
                name="configure_subnets",
                script="",
                stdin_input=stdin_input,
                timeout_seconds=300,  # 5 min for config + commit
                poll_for_job=True,  # Commit may be async for larger configs
            ),
        ]


class NGFWRemoveSubnetsPlan:
    """Plan for removing subnet address objects and rules from the NGFW.

    Deletes PAN-OS security rules first, then address objects.
    All deletes are done in a single commit for efficiency.
    """

    name: ClassVar[str] = "ngfw_remove_subnets"

    steps: ClassVar[list[SetupStep]] = []

    def get_steps(self, subnets: list[dict], range_id: int, has_endpoints: bool = False) -> list[SetupStep]:
        """Build steps with dynamic stdin_input for removing subnets.

        Args:
            subnets: List of subnet dicts with 'name' and 'connected_to'.
            range_id: Range ID for naming.
            has_endpoints: Whether endpoints subnet config was added.

        Returns:
            List with single SetupStep containing all delete commands.
        """
        stdin_input = build_remove_input(subnets, range_id, has_endpoints)
        return [
            SetupStep(
                name="remove_subnets",
                script="",
                stdin_input=stdin_input,
                timeout_seconds=300,
            ),
        ]
