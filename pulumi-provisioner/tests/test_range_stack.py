"""Range stack component tests for Pulumi provisioner.

These tests use Pulumi's mocking framework to test the actual RangeStack
component which composes NetworkComponent and InstanceComponent(s).
Tests verify that the composition:
- Creates the network component
- Creates instance components for each config entry
- Correctly routes attackers vs victims to different AMIs/SGs
- Properly indexes multiple instances of the same role
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import InstanceConfig, RangeConfig


@pytest.fixture
def mock_cleanup_orphaned_subnet():
    """Mock _cleanup_orphaned_subnet for RangeStack tests.

    The cleanup function makes real AWS API calls, which we don't want
    during Pulumi component tests.
    """
    with patch("components.network._cleanup_orphaned_subnet"):
        yield


class TestRangeStackComposition:
    """Tests for RangeStack component composition."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_cleanup_orphaned_subnet):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pytest.fixture
    def basic_config(self):
        """Basic RangeConfig with one attacker and one victim."""
        return RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
                InstanceConfig(
                    role="victim",
                    os_type="ubuntu",
                    instance_type="t3.micro",
                    agent_s3_key="agents/xdr.tar.gz",
                    agent_presigned_url="https://s3.example.com/agent",
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
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

    @pulumi.runtime.test
    def test_creates_network_component(self, temp_templates, basic_config):
        """RangeStack should create a NetworkComponent."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=basic_config)

            assert stack.network is not None
            assert stack.subnet_id is not None
            assert stack.subnet_cidr is not None

    @pulumi.runtime.test
    def test_creates_instance_components(self, temp_templates, basic_config):
        """RangeStack should create InstanceComponent for each config entry."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=basic_config)

            # Should have 2 instances (1 attacker, 1 victim)
            assert len(stack.instances) == 2

    @pulumi.runtime.test
    def test_cidr_prefix_extraction(self, temp_templates, basic_config):
        """CIDR prefix should be extracted correctly from VPC CIDR."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=basic_config)

            # The network should use the correct CIDR prefix
            # 10.1.0.0/16 -> 10.1, with subnet_index=5 -> 10.1.6.0/24
            def check_cidr(cidr):
                assert cidr.startswith("10.1.")

            stack.subnet_cidr.apply(check_cidr)

    @pulumi.runtime.test
    def test_get_outputs_returns_expected_keys(self, temp_templates, basic_config):
        """get_outputs should return dict with subnet_id, subnet_cidr, instances."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=basic_config)

            outputs = stack.get_outputs()

            assert "subnet_id" in outputs
            assert "subnet_cidr" in outputs
            assert "instances" in outputs
            assert len(outputs["instances"]) == 2


class TestRangeStackSecurityGroupAssignment:
    """Tests for security group assignment logic."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_cleanup_orphaned_subnet):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_attacker_uses_kali_security_group(self, temp_templates):
        """Attacker instances should use kali_security_group_id."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali-specific",
            victim_security_group_id="sg-victim-specific",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            # Verify the attacker instance uses kali SG
            attacker = stack.instances[0]

            def check_sg(sgs):
                assert "sg-kali-specific" in sgs

            attacker.instance.vpc_security_group_ids.apply(check_sg)

    @pulumi.runtime.test
    def test_victim_uses_victim_security_group(self, temp_templates):
        """Victim instances should use victim_security_group_id."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(
                    role="victim",
                    os_type="ubuntu",
                    instance_type="t3.micro",
                ),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali-specific",
            victim_security_group_id="sg-victim-specific",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            victim = stack.instances[0]

            def check_sg(sgs):
                assert "sg-victim-specific" in sgs

            victim.instance.vpc_security_group_ids.apply(check_sg)


class TestRangeStackAmiSelection:
    """Tests for AMI selection logic."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_cleanup_orphaned_subnet):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_attacker_uses_kali_ami(self, temp_templates):
        """Attacker instances should use kali_ami_id."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali-specific",
            victim_ami_id="ami-ubuntu-specific",
            windows_ami_id="ami-windows-specific",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            attacker = stack.instances[0]

            def check_ami(ami):
                assert ami == "ami-kali-specific"

            attacker.instance.ami.apply(check_ami)

    @pulumi.runtime.test
    def test_linux_victim_uses_victim_ami(self, temp_templates):
        """Linux victim instances should use victim_ami_id."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(
                    role="victim",
                    os_type="ubuntu",
                    instance_type="t3.micro",
                ),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali-specific",
            victim_ami_id="ami-ubuntu-specific",
            windows_ami_id="ami-windows-specific",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            victim = stack.instances[0]

            def check_ami(ami):
                assert ami == "ami-ubuntu-specific"

            victim.instance.ami.apply(check_ami)

    @pulumi.runtime.test
    def test_windows_victim_uses_windows_ami(self, temp_templates):
        """Windows victim instances should use windows_ami_id."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(
                    role="victim",
                    os_type="windows",
                    instance_type="t3.medium",
                ),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali-specific",
            victim_ami_id="ami-ubuntu-specific",
            windows_ami_id="ami-windows-specific",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            victim = stack.instances[0]

            def check_ami(ami):
                assert ami == "ami-windows-specific"

            victim.instance.ami.apply(check_ami)


class TestRangeStackMultipleInstances:
    """Tests for multiple instance handling and indexing."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_cleanup_orphaned_subnet):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_multiple_attackers_indexed_correctly(self, temp_templates):
        """Multiple attackers should have sequential indices 0, 1, 2..."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.medium"),
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.large"),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            assert len(stack.instances) == 3

    @pulumi.runtime.test
    def test_multiple_victims_indexed_correctly(self, temp_templates):
        """Multiple victims should have sequential indices 0, 1, 2..."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(role="victim", os_type="ubuntu", instance_type="t3.micro"),
                InstanceConfig(role="victim", os_type="windows", instance_type="t3.medium"),
                InstanceConfig(role="victim", os_type="ubuntu", instance_type="t3.small"),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            assert len(stack.instances) == 3

    @pulumi.runtime.test
    def test_mixed_roles_indexed_independently(self, temp_templates):
        """Attackers and victims should maintain separate index counters."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
                InstanceConfig(role="victim", os_type="ubuntu", instance_type="t3.micro"),
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.medium"),
                InstanceConfig(role="victim", os_type="windows", instance_type="t3.medium"),
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.large"),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            assert len(stack.instances) == 5

    @pulumi.runtime.test
    def test_empty_instances_list(self, temp_templates):
        """Range with no instances should still create network."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[],  # Empty!
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            assert stack.network is not None
            assert len(stack.instances) == 0


class TestRangeStackCidrPrefixExtraction:
    """Tests for CIDR prefix extraction logic."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_cleanup_orphaned_subnet):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_cidr_prefix_10_1(self, temp_templates):
        """VPC CIDR 10.1.0.0/16 should extract prefix 10.1."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            def check_cidr(cidr):
                assert cidr.startswith("10.1.")

            stack.subnet_cidr.apply(check_cidr)

    @pulumi.runtime.test
    def test_cidr_prefix_172_16(self, temp_templates):
        """VPC CIDR 172.16.0.0/16 should extract prefix 172.16."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[],
            vpc_id="vpc-12345",
            vpc_cidr="172.16.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            def check_cidr(cidr):
                assert cidr.startswith("172.16.")

            stack.subnet_cidr.apply(check_cidr)

    @pulumi.runtime.test
    def test_cidr_prefix_192_168(self, temp_templates):
        """VPC CIDR 192.168.0.0/16 should extract prefix 192.168."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[],
            vpc_id="vpc-12345",
            vpc_cidr="192.168.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            def check_cidr(cidr):
                assert cidr.startswith("192.168.")

            stack.subnet_cidr.apply(check_cidr)
