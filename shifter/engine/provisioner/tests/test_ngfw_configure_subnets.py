"""Tests for NGFW Configure Subnets Plan.

Tests the PAN-OS command generation for:
- Static routes for each subnet
- Address objects for each subnet
- Security rules with XDR logging
- Route and address deletion on remove
"""

import pytest

from plans.ngfw_configure_subnets import (
    NGFWConfigureSubnetsPlan,
    NGFWRemoveSubnetsPlan,
    build_configure_input,
    build_connected_pairs,
    build_remove_input,
)


class TestBuildConnectedPairs:
    """Tests for build_connected_pairs function."""

    def test_single_connection(self):
        """A -> B produces one pair (A, B)."""
        subnets = [
            {"name": "attack", "connected_to": ["target"]},
            {"name": "target", "connected_to": []},
        ]
        pairs = build_connected_pairs(subnets)
        assert pairs == [("attack", "target")]

    def test_bidirectional_deduplication(self):
        """A -> B and B -> A should produce only one pair."""
        subnets = [
            {"name": "attack", "connected_to": ["target"]},
            {"name": "target", "connected_to": ["attack"]},
        ]
        pairs = build_connected_pairs(subnets)
        assert pairs == [("attack", "target")]

    def test_multiple_connections(self):
        """Multiple connections should all be captured."""
        subnets = [
            {"name": "attack", "connected_to": ["target", "victim"]},
            {"name": "target", "connected_to": []},
            {"name": "victim", "connected_to": []},
        ]
        pairs = build_connected_pairs(subnets)
        assert len(pairs) == 2
        assert ("attack", "target") in pairs
        assert ("attack", "victim") in pairs

    def test_invalid_reference_ignored(self):
        """References to non-existent subnets should be ignored."""
        subnets = [
            {"name": "attack", "connected_to": ["nonexistent"]},
        ]
        pairs = build_connected_pairs(subnets)
        assert pairs == []

    def test_alphabetical_ordering(self):
        """Pairs should be sorted alphabetically."""
        subnets = [
            {"name": "zebra", "connected_to": ["alpha"]},
            {"name": "alpha", "connected_to": []},
        ]
        pairs = build_connected_pairs(subnets)
        assert pairs == [("alpha", "zebra")]


class TestBuildConfigureInput:
    """Tests for build_configure_input function."""

    @pytest.fixture
    def sample_subnets(self):
        """Sample subnet configuration for testing."""
        return [
            {"name": "attack", "cidr": "10.1.2.0/28", "connected_to": ["target"]},
            {"name": "target", "cidr": "10.1.2.16/28", "connected_to": []},
        ]

    def test_creates_static_routes(self, sample_subnets):
        """Static routes should be created for each subnet."""
        result = build_configure_input(sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1")

        assert "set network virtual-router default routing-table ip static-route" in result
        assert "range-97-attack destination 10.1.2.0/28" in result
        assert "range-97-target destination 10.1.2.16/28" in result

    def test_routes_use_gateway_ip(self, sample_subnets):
        """Routes should use the provided VPC gateway IP as next-hop."""
        result = build_configure_input(sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1")

        assert "nexthop ip-address 10.1.4.1" in result

    def test_routes_use_ethernet1_1(self, sample_subnets):
        """Routes should use ethernet1/1 interface."""
        result = build_configure_input(sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1")

        assert "interface ethernet1/1" in result

    def test_creates_address_objects(self, sample_subnets):
        """Address objects should be created for each subnet."""
        result = build_configure_input(sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1")

        assert "set address range-97-attack ip-netmask 10.1.2.0/28" in result
        assert "set address range-97-target ip-netmask 10.1.2.16/28" in result

    def test_creates_security_rules_with_zones(self, sample_subnets):
        """Security rules should use 'ranges' zone."""
        result = build_configure_input(sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1")

        assert "from ranges to ranges" in result

    def test_security_rules_have_xdr_logging(self, sample_subnets):
        """Security rules should have XDR-Forward logging enabled."""
        result = build_configure_input(sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1")

        assert "log-setting XDR-Forward" in result
        assert "log-end yes" in result

    def test_bidirectional_rules(self, sample_subnets):
        """Security rules should be created in both directions."""
        result = build_configure_input(sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1")

        assert "range-97-attack-to-target" in result
        assert "range-97-target-to-attack" in result

    def test_starts_with_configure(self, sample_subnets):
        """Output should start with 'configure' command."""
        result = build_configure_input(sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1")

        lines = result.split("\n")
        assert lines[0] == "configure"

    def test_ends_with_commit_exit(self, sample_subnets):
        """Output should end with 'commit' and 'exit' commands."""
        result = build_configure_input(sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1")

        lines = result.split("\n")
        assert lines[-2] == "commit"
        assert lines[-1] == "exit"

    def test_deletes_stale_routes_when_provided(self, sample_subnets):
        """Stale routes should be deleted before adding new ones."""
        stale_routes = ["range-50-attack", "range-50-target"]
        result = build_configure_input(
            sample_subnets,
            range_id=97,
            vpc_gateway_ip="10.1.4.1",
            stale_routes_to_delete=stale_routes,
        )

        # Stale routes should be deleted
        assert "delete network virtual-router default routing-table ip static-route range-50-attack" in result
        assert "delete network virtual-router default routing-table ip static-route range-50-target" in result

        # Deletions should come before additions
        lines = result.split("\n")
        delete_indices = [i for i, line in enumerate(lines) if "delete" in line]
        set_indices = [i for i, line in enumerate(lines) if line.startswith("set ")]

        if delete_indices and set_indices:
            assert max(delete_indices) < min(set_indices), "Deletes should come before sets"

    def test_no_deletes_when_no_stale_routes(self, sample_subnets):
        """No delete commands when stale_routes_to_delete is None or empty."""
        result = build_configure_input(
            sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1", stale_routes_to_delete=None
        )
        assert "delete" not in result

        result = build_configure_input(
            sample_subnets, range_id=97, vpc_gateway_ip="10.1.4.1", stale_routes_to_delete=[]
        )
        assert "delete" not in result


class TestBuildRemoveInput:
    """Tests for build_remove_input function."""

    @pytest.fixture
    def sample_subnets(self):
        """Sample subnet configuration for testing."""
        return [
            {"name": "attack", "cidr": "10.1.2.0/28", "connected_to": ["target"]},
            {"name": "target", "cidr": "10.1.2.16/28", "connected_to": []},
        ]

    def test_deletes_security_rules(self, sample_subnets):
        """Security rules should be deleted."""
        result = build_remove_input(sample_subnets, range_id=97)

        assert "delete rulebase security rules range-97-attack-to-target" in result
        assert "delete rulebase security rules range-97-target-to-attack" in result

    def test_deletes_address_objects(self, sample_subnets):
        """Address objects should be deleted."""
        result = build_remove_input(sample_subnets, range_id=97)

        assert "delete address range-97-attack" in result
        assert "delete address range-97-target" in result

    def test_deletes_static_routes(self, sample_subnets):
        """Static routes should be deleted."""
        result = build_remove_input(sample_subnets, range_id=97)

        assert "delete network virtual-router default routing-table ip static-route range-97-attack" in result
        assert "delete network virtual-router default routing-table ip static-route range-97-target" in result

    def test_deletion_order(self, sample_subnets):
        """Rules should be deleted before addresses, addresses before routes."""
        result = build_remove_input(sample_subnets, range_id=97)
        lines = result.split("\n")

        # Find indices of different deletion types
        rule_indices = [i for i, line in enumerate(lines) if "delete rulebase security" in line]
        address_indices = [i for i, line in enumerate(lines) if "delete address" in line]
        route_indices = [i for i, line in enumerate(lines) if "delete network virtual-router" in line]

        # Rules should come before addresses
        assert max(rule_indices) < min(address_indices), "Rules should be deleted before addresses"

        # Addresses should come before routes
        assert max(address_indices) < min(route_indices), "Addresses should be deleted before routes"

    def test_ends_with_commit_exit(self, sample_subnets):
        """Output should end with 'commit' and 'exit' commands."""
        result = build_remove_input(sample_subnets, range_id=97)

        lines = result.split("\n")
        assert lines[-2] == "commit"
        assert lines[-1] == "exit"


class TestNGFWConfigureSubnetsPlan:
    """Tests for NGFWConfigureSubnetsPlan class."""

    def test_get_steps_returns_one_step(self):
        """get_steps should return a single step."""
        plan = NGFWConfigureSubnetsPlan()
        subnets = [{"name": "attack", "cidr": "10.1.2.0/28", "connected_to": []}]
        steps = plan.get_steps(subnets, range_id=1, vpc_gateway_ip="10.1.4.1")

        assert len(steps) == 1
        assert steps[0].name == "configure_subnets"

    def test_step_has_stdin_input(self):
        """Step should have stdin_input with the configure commands."""
        plan = NGFWConfigureSubnetsPlan()
        subnets = [{"name": "attack", "cidr": "10.1.2.0/28", "connected_to": []}]
        steps = plan.get_steps(subnets, range_id=1, vpc_gateway_ip="10.1.4.1")

        assert steps[0].stdin_input is not None
        assert "configure" in steps[0].stdin_input
        assert "commit" in steps[0].stdin_input

    def test_step_has_empty_script(self):
        """Step should have empty script (commands are via stdin)."""
        plan = NGFWConfigureSubnetsPlan()
        subnets = [{"name": "attack", "cidr": "10.1.2.0/28", "connected_to": []}]
        steps = plan.get_steps(subnets, range_id=1, vpc_gateway_ip="10.1.4.1")

        assert steps[0].script == ""


class TestNGFWRemoveSubnetsPlan:
    """Tests for NGFWRemoveSubnetsPlan class."""

    def test_get_steps_returns_one_step(self):
        """get_steps should return a single step."""
        plan = NGFWRemoveSubnetsPlan()
        subnets = [{"name": "attack", "cidr": "10.1.2.0/28", "connected_to": []}]
        steps = plan.get_steps(subnets, range_id=1)

        assert len(steps) == 1
        assert steps[0].name == "remove_subnets"

    def test_step_has_stdin_input(self):
        """Step should have stdin_input with the delete commands."""
        plan = NGFWRemoveSubnetsPlan()
        subnets = [{"name": "attack", "cidr": "10.1.2.0/28", "connected_to": []}]
        steps = plan.get_steps(subnets, range_id=1)

        assert steps[0].stdin_input is not None
        assert "delete" in steps[0].stdin_input
        assert "commit" in steps[0].stdin_input
