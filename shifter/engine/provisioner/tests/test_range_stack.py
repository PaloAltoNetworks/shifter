"""Range stack component tests for Shifter Engine.

These tests use Pulumi's mocking framework to test the RangeStack
component which composes NetworkComponent(s) and InstanceComponent(s).

Tests verify that the composition:
- Creates network components for each subnet
- Creates instance components in their designated subnets
- Correctly routes instances to their subnet's security group
- Properly indexes multiple instances of the same role
- Handles DC dependency ordering
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import InstanceConfig, RangeConfig, SubnetConfig


@pytest.fixture
def mock_find_free_subnet():
    """Mock _find_free_subnet for RangeStack tests.

    The subnet finder makes real AWS API calls, which we don't want
    during Pulumi component tests.
    """
    with patch("components.network._find_free_subnet", return_value="10.1.2.0/28"):
        yield


@pytest.fixture
def mock_dc_setup():
    """Mock DC setup for RangeStack tests."""
    with patch("components.instance.InstanceComponent.run_dc_setup") as mock:
        mock.return_value = pulumi.Output.from_input(True)
        yield mock


@pytest.fixture
def mock_setup():
    """Mock setup for RangeStack tests."""
    with patch("components.instance.InstanceComponent.run_setup") as mock:
        mock.return_value = pulumi.Output.from_input(True)
        yield mock


def make_basic_config(subnets: list[SubnetConfig]) -> RangeConfig:
    """Helper to create a RangeConfig with required fields."""
    return RangeConfig(
        range_id=42,
        user_id=1,
        request_uuid="req-12345",
        environment="dev",
        subnets=subnets,
        vpc_id="vpc-12345",
        vpc_cidr="10.1.0.0/16",
        route_table_id="rtb-12345",
        kali_security_group_id="sg-kali",
        victim_security_group_id="sg-victim",
        instance_profile_name="range-profile",
        kali_ami_id="ami-kali123",
        victim_ami_id="ami-ubuntu123",
        windows_ami_id="ami-windows123",
        dc_ami_id="ami-dc-test",
        agent_s3_bucket="shifter-agents",
        availability_zone="us-east-2a",
    )


class TestRangeStackMultiSubnet:
    """Tests for RangeStack with multiple subnets."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet, mock_setup):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_creates_network_for_each_subnet(self, temp_templates):
        """RangeStack should create one NetworkComponent per subnet."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="uuid-attack",
                    instances=[
                        InstanceConfig(
                            role="attacker",
                            os_type="kali",
                            instance_type="t3.small",
                            uuid="inst-uuid-attacker",
                        ),
                    ],
                ),
                SubnetConfig(
                    name="target",
                    uuid="uuid-target",
                    instances=[
                        InstanceConfig(
                            role="victim",
                            os_type="ubuntu",
                            instance_type="t3.micro",
                            uuid="inst-uuid-victim",
                        ),
                    ],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            assert len(stack.networks) == 2
            assert "attack" in stack.networks
            assert "target" in stack.networks

    @pulumi.runtime.test
    def test_instances_placed_in_correct_subnets(self, temp_templates):
        """Instances should be created in their designated subnet."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="uuid-attack",
                    instances=[
                        InstanceConfig(
                            role="attacker",
                            os_type="kali",
                            instance_type="t3.small",
                            uuid="inst-uuid-attacker",
                        ),
                    ],
                ),
                SubnetConfig(
                    name="target",
                    uuid="uuid-target",
                    instances=[
                        InstanceConfig(
                            role="victim",
                            os_type="ubuntu",
                            instance_type="t3.micro",
                            uuid="inst-uuid-victim",
                        ),
                    ],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            # Should have 2 instances
            assert len(stack.instances) == 2

            # Check subnet_name tracking
            subnet_names = [subnet_name for _, subnet_name in stack.instances]
            assert "attack" in subnet_names
            assert "target" in subnet_names

    @pulumi.runtime.test
    def test_get_outputs_contains_subnets_dict(self, temp_templates):
        """get_outputs should return subnets dict with per-subnet details."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="uuid-attack",
                    instances=[],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            outputs = stack.get_outputs()

            assert "subnets" in outputs
            assert "attack" in outputs["subnets"]
            assert "subnet_id" in outputs["subnets"]["attack"]
            assert "subnet_cidr" in outputs["subnets"]["attack"]
            assert "security_group_id" in outputs["subnets"]["attack"]

    @pulumi.runtime.test
    def test_instance_outputs_include_subnet_name(self, temp_templates):
        """Instance outputs should include subnet_name field."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="uuid-attack",
                    instances=[
                        InstanceConfig(
                            role="attacker",
                            os_type="kali",
                            instance_type="t3.small",
                            uuid="inst-uuid-attacker",
                        ),
                    ],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            outputs = stack.get_outputs()

            assert len(outputs["instances"]) == 1
            assert outputs["instances"][0]["subnet_name"] == "attack"


class TestRangeStackValidation:
    """Tests for RangeStack config validation."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet, mock_setup):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_raises_on_empty_subnets(self, temp_templates):
        """Should raise ValueError if subnets list is empty."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(subnets=[])

        with (
            patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}),
            pytest.raises(ValueError, match="At least one subnet is required"),
        ):
            RangeStack("test-range", config=config)

    @pulumi.runtime.test
    def test_raises_on_duplicate_subnet_names(self, temp_templates):
        """Should raise ValueError if subnet names are not unique."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(name="attack", uuid="uuid-1", instances=[]),
                SubnetConfig(name="attack", uuid="uuid-2", instances=[]),
            ]
        )

        with (
            patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}),
            pytest.raises(ValueError, match="Subnet names must be unique"),
        ):
            RangeStack("test-range", config=config)

    @pulumi.runtime.test
    def test_raises_on_dc_without_dc_ami(self, temp_templates):
        """Should raise ValueError if DC exists but dc_ami_id is empty."""
        from stacks.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            request_uuid="req-12345",
            environment="dev",
            subnets=[
                SubnetConfig(
                    name="dc_network",
                    uuid="uuid-dc",
                    instances=[
                        InstanceConfig(
                            role="dc",
                            os_type="windows",
                            instance_type="t3.large",
                            uuid="inst-uuid-dc",
                            dc_config={
                                "domain_name": "test.local",
                                "netbios_name": "TEST",
                            },
                        ),
                    ],
                ),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            dc_ami_id="",  # Empty!
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with (
            patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}),
            pytest.raises(ValueError, match="dc_ami_id is required"),
        ):
            RangeStack("test-range", config=config)


class TestRangeStackDCOrdering:
    """Tests for DC instance dependency ordering."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet, mock_dc_setup, mock_setup):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_dc_instances_created_first(self, temp_templates):
        """DC instances should be first in the instances list."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="uuid-attack",
                    instances=[
                        InstanceConfig(
                            role="attacker",
                            os_type="kali",
                            instance_type="t3.small",
                            uuid="inst-uuid-attacker",
                        ),
                    ],
                ),
                SubnetConfig(
                    name="dc_network",
                    uuid="uuid-dc",
                    instances=[
                        InstanceConfig(
                            role="dc",
                            os_type="windows",
                            instance_type="t3.large",
                            uuid="inst-uuid-dc",
                            dc_config={
                                "domain_name": "test.local",
                                "netbios_name": "TEST",
                            },
                        ),
                    ],
                ),
            ]
        )

        env_vars = {"TEMPLATES_DIR": str(temp_templates), "DC_DOMAIN_PASSWORD": "test"}
        with patch.dict(os.environ, env_vars):
            stack = RangeStack("test-range", config=config)

            # DC should be first even though it's in second subnet
            first_instance, _ = stack.instances[0]
            assert first_instance.role == "dc"

    @pulumi.runtime.test
    def test_dc_config_param_name_set(self, temp_templates):
        """dc_config_param_name should be set when DC exists."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="dc_network",
                    uuid="uuid-dc",
                    instances=[
                        InstanceConfig(
                            role="dc",
                            os_type="windows",
                            instance_type="t3.large",
                            uuid="inst-uuid-dc",
                            dc_config={
                                "domain_name": "test.local",
                                "netbios_name": "TEST",
                            },
                        ),
                    ],
                ),
            ]
        )

        env_vars = {"TEMPLATES_DIR": str(temp_templates), "DC_DOMAIN_PASSWORD": "test"}
        with patch.dict(os.environ, env_vars):
            stack = RangeStack("test-range", config=config)

            expected = "/shifter/dev/range/42/dc-config"
            assert stack.dc_config_param_name == expected

    @pulumi.runtime.test
    def test_no_dc_config_param_name_without_dc(self, temp_templates):
        """dc_config_param_name should be None when no DC."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="uuid-attack",
                    instances=[
                        InstanceConfig(
                            role="attacker",
                            os_type="kali",
                            instance_type="t3.small",
                            uuid="inst-uuid-attacker",
                        ),
                    ],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            assert stack.dc_config_param_name is None


class TestRangeStackAmiSelection:
    """Tests for AMI selection logic."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet, mock_setup):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_attacker_uses_kali_ami(self, temp_templates):
        """Attacker instances should use kali_ami_id."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="uuid-attack",
                    instances=[
                        InstanceConfig(
                            role="attacker",
                            os_type="kali",
                            instance_type="t3.small",
                            uuid="inst-uuid-attacker",
                        ),
                    ],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            instance, _ = stack.instances[0]

            def check_ami(ami):
                assert ami == "ami-kali123"

            instance.instance.ami.apply(check_ami)

    @pulumi.runtime.test
    def test_linux_victim_uses_victim_ami(self, temp_templates):
        """Linux victim instances should use victim_ami_id."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="target",
                    uuid="uuid-target",
                    instances=[
                        InstanceConfig(
                            role="victim",
                            os_type="ubuntu",
                            instance_type="t3.micro",
                            uuid="inst-uuid-victim",
                        ),
                    ],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            instance, _ = stack.instances[0]

            def check_ami(ami):
                assert ami == "ami-ubuntu123"

            instance.instance.ami.apply(check_ami)

    @pulumi.runtime.test
    def test_windows_victim_uses_windows_ami(self, temp_templates):
        """Windows victim instances should use windows_ami_id."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="target",
                    uuid="uuid-target",
                    instances=[
                        InstanceConfig(
                            role="victim",
                            os_type="windows",
                            instance_type="t3.medium",
                            uuid="inst-uuid-windows",
                        ),
                    ],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            instance, _ = stack.instances[0]

            def check_ami(ami):
                assert ami == "ami-windows123"

            instance.instance.ami.apply(check_ami)


class TestRangeStackMultipleInstances:
    """Tests for multiple instance handling and indexing."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet, mock_setup):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_multiple_instances_in_one_subnet(self, temp_templates):
        """Multiple instances in one subnet should work."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="uuid-attack",
                    instances=[
                        InstanceConfig(
                            role="attacker",
                            os_type="kali",
                            instance_type="t3.small",
                            uuid="inst-uuid-attacker",
                        ),
                        InstanceConfig(
                            role="attacker",
                            os_type="kali",
                            instance_type="t3.medium",
                            uuid="inst-uuid-attacker-2",
                        ),
                    ],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            assert len(stack.instances) == 2
            # Both should be in attack subnet
            for _, subnet_name in stack.instances:
                assert subnet_name == "attack"

    @pulumi.runtime.test
    def test_instances_spread_across_subnets(self, temp_templates):
        """Instances should be placed in their designated subnets."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="uuid-attack",
                    instances=[
                        InstanceConfig(
                            role="attacker",
                            os_type="kali",
                            instance_type="t3.small",
                            uuid="inst-uuid-attacker",
                        ),
                    ],
                ),
                SubnetConfig(
                    name="target1",
                    uuid="uuid-target1",
                    instances=[
                        InstanceConfig(
                            role="victim",
                            os_type="ubuntu",
                            instance_type="t3.micro",
                            uuid="inst-uuid-victim",
                        ),
                    ],
                ),
                SubnetConfig(
                    name="target2",
                    uuid="uuid-target2",
                    instances=[
                        InstanceConfig(
                            role="victim",
                            os_type="windows",
                            instance_type="t3.medium",
                            uuid="inst-uuid-windows",
                        ),
                    ],
                ),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            assert len(stack.instances) == 3
            assert len(stack.networks) == 3

            subnet_names = {name for _, name in stack.instances}
            assert subnet_names == {"attack", "target1", "target2"}


class TestRangeStackCidrPrefix:
    """Tests for CIDR prefix extraction."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet, mock_setup):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_extract_cidr_prefix_10_1(self, temp_templates):
        """VPC CIDR 10.1.0.0/16 should extract prefix 10.1."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(name="test", uuid="uuid-1", instances=[]),
            ]
        )
        config = RangeConfig(**{**config.__dict__, "vpc_cidr": "10.1.0.0/16"})

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)
            prefix = stack._extract_cidr_prefix("10.1.0.0/16")
            assert prefix == "10.1"

    @pulumi.runtime.test
    def test_extract_cidr_prefix_172_16(self, temp_templates):
        """VPC CIDR 172.16.0.0/16 should extract prefix 172.16."""
        from stacks.range_stack import RangeStack

        config = make_basic_config(
            subnets=[
                SubnetConfig(name="test", uuid="uuid-1", instances=[]),
            ]
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)
            prefix = stack._extract_cidr_prefix("172.16.0.0/16")
            assert prefix == "172.16"
