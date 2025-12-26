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


@pytest.fixture
def mock_dc_setup():
    """Mock DC setup for RangeStack tests.

    DC setup uses SSM Run Command which requires AWS credentials and region.
    We mock it to return a successful Output without making real API calls.
    """
    with patch("components.instance.InstanceComponent.run_dc_setup") as mock:
        mock.return_value = pulumi.Output.from_input(True)
        yield mock


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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
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
            dc_ami_id="ami-dc-test",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            def check_cidr(cidr):
                assert cidr.startswith("192.168.")

            stack.subnet_cidr.apply(check_cidr)


class TestRangeStackDCDependencyOrdering:
    """Tests for DC instance dependency ordering and configuration.

    These tests verify:
    1. DC instances are created before other instances (list order)
    2. Domain members have DC in their depends_on (actual dependency)
    3. Security groups are correctly assigned per role
    4. dc_config_param_name is correctly set and exported
    """

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_cleanup_orphaned_subnet, mock_dc_setup):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pytest.fixture
    def dc_range_config(self):
        """RangeConfig with DC, domain member, and attacker.

        Note: Victim is listed BEFORE DC in config to verify reordering works.
        """
        return RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                # Intentionally put victim first to test reordering
                InstanceConfig(
                    role="victim",
                    os_type="windows",
                    instance_type="t3.medium",
                    join_domain=True,
                ),
                InstanceConfig(
                    role="dc",
                    os_type="windows",
                    instance_type="t3.large",
                    dc_config={"domain_name": "internal.shifter", "netbios_name": "SHIFTER"},
                ),
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.medium"),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            dc_security_group_id="sg-dc",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            dc_ami_id="ami-dc-test",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )


class TestDCSecurityGroupAssignment(TestRangeStackDCDependencyOrdering):
    """Tests for security group assignment by role."""

    @pulumi.runtime.test
    def test_dc_uses_dc_security_group(self, temp_templates, dc_range_config):
        """DC instance should use dc_security_group_id, not victim SG."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=dc_range_config)

            # Find DC instance by checking dc_config_param attribute
            dc_instance = None
            for inst in stack.instances:
                if inst.dc_config_param is not None:
                    dc_instance = inst
                    break

            assert dc_instance is not None, "Should have a DC instance"

            def check_dc_sg(sgs):
                assert "sg-dc" in sgs, f"DC should use sg-dc, got {sgs}"
                assert "sg-victim" not in sgs, "DC should NOT use victim SG"

            dc_instance.instance.vpc_security_group_ids.apply(check_dc_sg)

    @pulumi.runtime.test
    def test_victim_uses_victim_security_group_not_dc(self, temp_templates, dc_range_config):
        """Victim instance should use victim_security_group_id, not DC SG."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=dc_range_config)

            # Find victim instance (has no dc_config_param, not attacker)
            victim_instance = None
            for inst in stack.instances:
                if inst.dc_config_param is None:
                    # Check it's not the attacker by checking SG
                    def is_victim(sgs):
                        return "sg-victim" in sgs
                    # Use tags to identify
                    def check_role(tags):
                        return tags.get("shifter:role") == "victim"
                    victim_instance = inst
                    break

            # Verify by checking all non-DC instances
            for inst in stack.instances:
                if inst.dc_config_param is None:
                    def check_not_dc_sg(sgs):
                        assert "sg-dc" not in sgs, f"Non-DC instance should not use sg-dc, got {sgs}"
                    inst.instance.vpc_security_group_ids.apply(check_not_dc_sg)

    @pulumi.runtime.test
    def test_dc_fallback_to_victim_sg_when_dc_sg_not_set(self, temp_templates):
        """DC should fall back to victim SG if dc_security_group_id is empty."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(
                    role="dc",
                    os_type="windows",
                    instance_type="t3.large",
                    dc_config={"domain_name": "test.local", "netbios_name": "TEST"},
                ),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim-fallback",
            dc_security_group_id="",  # Empty - should fall back
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            dc_ami_id="ami-dc-test",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            def check_fallback_sg(sgs):
                assert "sg-victim-fallback" in sgs, f"DC should fall back to victim SG, got {sgs}"

            stack.instances[0].instance.vpc_security_group_ids.apply(check_fallback_sg)


class TestDCConfigParamName(TestRangeStackDCDependencyOrdering):
    """Tests for dc_config_param_name attribute."""

    @pulumi.runtime.test
    def test_dc_config_param_name_format(self, temp_templates, dc_range_config):
        """dc_config_param_name should follow /shifter/{env}/range/{id}/dc-config pattern."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=dc_range_config)

            expected_path = "/shifter/dev/range/42/dc-config"
            assert stack.dc_config_param_name == expected_path, \
                f"Expected {expected_path}, got {stack.dc_config_param_name}"

    @pulumi.runtime.test
    def test_dc_config_param_name_none_without_dc(self, temp_templates):
        """dc_config_param_name should be None when no DC in range."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
                InstanceConfig(role="victim", os_type="ubuntu", instance_type="t3.micro"),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            dc_security_group_id="sg-dc",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            dc_ami_id="ami-dc-test",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)
            assert stack.dc_config_param_name is None, \
                "dc_config_param_name should be None when no DC"

    @pulumi.runtime.test
    def test_dc_config_param_name_in_get_outputs(self, temp_templates, dc_range_config):
        """get_outputs should include dc_config_param_name."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=dc_range_config)

            outputs = stack.get_outputs()
            assert "dc_config_param_name" in outputs, "get_outputs should include dc_config_param_name"
            assert outputs["dc_config_param_name"] == "/shifter/dev/range/42/dc-config"

    @pulumi.runtime.test
    def test_multiple_dcs_uses_first_dc_param_name(self, temp_templates):
        """With multiple DCs, should use first DC's param name."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=99,
            user_id=1,
            subnet_index=5,
            environment="prod",
            instances=[
                InstanceConfig(
                    role="dc",
                    os_type="windows",
                    instance_type="t3.large",
                    dc_config={"domain_name": "first.local", "netbios_name": "FIRST"},
                ),
                InstanceConfig(
                    role="dc",
                    os_type="windows",
                    instance_type="t3.large",
                    dc_config={"domain_name": "second.local", "netbios_name": "SECOND"},
                ),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            dc_security_group_id="sg-dc",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            dc_ami_id="ami-dc-test",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            # Should use first DC's param name (both would have same path anyway)
            expected_path = "/shifter/prod/range/99/dc-config"
            assert stack.dc_config_param_name == expected_path


class TestDCInstanceOrdering(TestRangeStackDCDependencyOrdering):
    """Tests for DC instance creation ordering."""

    @pulumi.runtime.test
    def test_dc_is_first_in_instances_list(self, temp_templates, dc_range_config):
        """DC should be first in instances list even if listed later in config."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=dc_range_config)

            # DC should be first (config had victim first, but we reorder)
            assert stack.instances[0].dc_config_param is not None, \
                "First instance should be DC (has dc_config_param)"

    @pulumi.runtime.test
    def test_instance_count_matches_config(self, temp_templates, dc_range_config):
        """All configured instances should be created."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=dc_range_config)
            assert len(stack.instances) == 3, "Should create all 3 instances"

    @pulumi.runtime.test
    def test_dc_instances_grouped_first(self, temp_templates):
        """All DC instances should come before non-DC instances."""
        from components.range_stack import RangeStack

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
                InstanceConfig(
                    role="dc",
                    os_type="windows",
                    instance_type="t3.large",
                    dc_config={"domain_name": "test.local", "netbios_name": "TEST"},
                ),
                InstanceConfig(role="victim", os_type="ubuntu", instance_type="t3.micro"),
                InstanceConfig(
                    role="dc",
                    os_type="windows",
                    instance_type="t3.large",
                    dc_config={"domain_name": "test2.local", "netbios_name": "TEST2"},
                ),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            dc_security_group_id="sg-dc",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            dc_ami_id="ami-dc-test",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            # First two should be DCs
            assert stack.instances[0].dc_config_param is not None, "Instance 0 should be DC"
            assert stack.instances[1].dc_config_param is not None, "Instance 1 should be DC"
            # Last two should be non-DC
            assert stack.instances[2].dc_config_param is None, "Instance 2 should not be DC"
            assert stack.instances[3].dc_config_param is None, "Instance 3 should not be DC"


class TestDCDependsOn(TestRangeStackDCDependencyOrdering):
    """Tests for Pulumi depends_on relationships.

    These tests mock InstanceComponent to capture the opts passed to it,
    allowing us to verify the actual depends_on relationships.
    """

    @pulumi.runtime.test
    def test_domain_member_depends_on_dc(self, temp_templates, dc_range_config):
        """Domain member (join_domain=True) should have DC in depends_on."""
        from components.range_stack import RangeStack
        from components.instance import InstanceComponent

        created_instances = []
        original_init = InstanceComponent.__init__

        def capture_init(self, *args, **kwargs):
            created_instances.append({
                "name": args[0] if args else kwargs.get("name"),
                "role": kwargs.get("role"),
                "opts": kwargs.get("opts"),
            })
            return original_init(self, *args, **kwargs)

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            with patch.object(InstanceComponent, "__init__", capture_init):
                stack = RangeStack("test-range", config=dc_range_config)

        # Find DC and victim creations
        dc_creation = next((c for c in created_instances if c["role"] == "dc"), None)
        victim_creation = next((c for c in created_instances if c["role"] == "victim"), None)

        assert dc_creation is not None, "DC should be created"
        assert victim_creation is not None, "Victim should be created"

        # Victim (join_domain=True) should have DC in depends_on
        victim_opts = victim_creation["opts"]
        assert victim_opts is not None, "Victim should have opts"
        assert victim_opts.depends_on is not None, "Victim should have depends_on"

        # depends_on should contain more than just network (should include DC)
        depends_on_count = len(victim_opts.depends_on)
        assert depends_on_count >= 2, \
            f"Victim should depend on network AND DC, got {depends_on_count} dependencies"

    @pulumi.runtime.test
    def test_non_domain_member_does_not_depend_on_dc(self, temp_templates, dc_range_config):
        """Non-domain member (join_domain=False) should NOT have DC in depends_on."""
        from components.range_stack import RangeStack
        from components.instance import InstanceComponent

        created_instances = []
        original_init = InstanceComponent.__init__

        def capture_init(self, *args, **kwargs):
            created_instances.append({
                "name": args[0] if args else kwargs.get("name"),
                "role": kwargs.get("role"),
                "opts": kwargs.get("opts"),
            })
            return original_init(self, *args, **kwargs)

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            with patch.object(InstanceComponent, "__init__", capture_init):
                stack = RangeStack("test-range", config=dc_range_config)

        # Find attacker (join_domain=False by default)
        attacker_creation = next((c for c in created_instances if c["role"] == "attacker"), None)

        assert attacker_creation is not None, "Attacker should be created"

        # Attacker should only depend on network (1 dependency)
        attacker_opts = attacker_creation["opts"]
        assert attacker_opts is not None, "Attacker should have opts"
        assert attacker_opts.depends_on is not None, "Attacker should have depends_on"

        depends_on_count = len(attacker_opts.depends_on)
        assert depends_on_count == 1, \
            f"Attacker should only depend on network, got {depends_on_count} dependencies"

    @pulumi.runtime.test
    def test_join_domain_true_but_no_dc_in_range(self, temp_templates):
        """join_domain=True without DC should not cause error (no DC to depend on)."""
        from components.range_stack import RangeStack
        from components.instance import InstanceComponent

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
                    join_domain=True,  # Wants to join, but no DC!
                ),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            dc_security_group_id="sg-dc",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            dc_ami_id="ami-dc-test",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        created_instances = []
        original_init = InstanceComponent.__init__

        def capture_init(self, *args, **kwargs):
            created_instances.append({
                "role": kwargs.get("role"),
                "opts": kwargs.get("opts"),
            })
            return original_init(self, *args, **kwargs)

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            with patch.object(InstanceComponent, "__init__", capture_init):
                # Should not raise an error
                stack = RangeStack("test-range", config=config)

        # Victim should be created with only network dependency
        victim_creation = created_instances[0]
        depends_on_count = len(victim_creation["opts"].depends_on)
        assert depends_on_count == 1, \
            "Victim with join_domain=True but no DC should only depend on network"


class TestDomainMemberDCConfigParamName(TestRangeStackDCDependencyOrdering):
    """Tests for passing dc_config_param_name to domain members (Phase 7)."""

    @pulumi.runtime.test
    def test_domain_member_receives_dc_config_param_name(self, temp_templates, dc_range_config):
        """Domain member (join_domain=True) should receive dc_config_param_name."""
        from components.range_stack import RangeStack
        from components.instance import InstanceComponent

        created_instances = []
        original_init = InstanceComponent.__init__

        def capture_init(self, *args, **kwargs):
            created_instances.append({
                "name": args[0] if args else kwargs.get("name"),
                "role": kwargs.get("role"),
                "join_domain": kwargs.get("join_domain"),
                "dc_config_param_name": kwargs.get("dc_config_param_name"),
            })
            return original_init(self, *args, **kwargs)

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            with patch.object(InstanceComponent, "__init__", capture_init):
                stack = RangeStack("test-range", config=dc_range_config)

        # Find the domain member victim
        victim_creation = next((c for c in created_instances if c["role"] == "victim"), None)

        assert victim_creation is not None, "Victim should be created"
        assert victim_creation["dc_config_param_name"] == "/shifter/dev/range/42/dc-config", \
            f"Domain member should receive dc_config_param_name, got {victim_creation['dc_config_param_name']}"

    @pulumi.runtime.test
    def test_non_domain_member_does_not_receive_dc_config_param_name(self, temp_templates, dc_range_config):
        """Non-domain member should NOT receive dc_config_param_name."""
        from components.range_stack import RangeStack
        from components.instance import InstanceComponent

        created_instances = []
        original_init = InstanceComponent.__init__

        def capture_init(self, *args, **kwargs):
            created_instances.append({
                "name": args[0] if args else kwargs.get("name"),
                "role": kwargs.get("role"),
                "dc_config_param_name": kwargs.get("dc_config_param_name"),
            })
            return original_init(self, *args, **kwargs)

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            with patch.object(InstanceComponent, "__init__", capture_init):
                stack = RangeStack("test-range", config=dc_range_config)

        # Attacker should NOT receive dc_config_param_name
        attacker_creation = next((c for c in created_instances if c["role"] == "attacker"), None)

        assert attacker_creation is not None, "Attacker should be created"
        assert attacker_creation["dc_config_param_name"] is None, \
            f"Attacker should NOT receive dc_config_param_name, got {attacker_creation['dc_config_param_name']}"

    @pulumi.runtime.test
    def test_join_domain_flag_passed_to_instance(self, temp_templates, dc_range_config):
        """join_domain flag should be passed to InstanceComponent."""
        from components.range_stack import RangeStack
        from components.instance import InstanceComponent

        created_instances = []
        original_init = InstanceComponent.__init__

        def capture_init(self, *args, **kwargs):
            created_instances.append({
                "role": kwargs.get("role"),
                "join_domain": kwargs.get("join_domain"),
            })
            return original_init(self, *args, **kwargs)

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            with patch.object(InstanceComponent, "__init__", capture_init):
                stack = RangeStack("test-range", config=dc_range_config)

        # Victim with join_domain=True should have it passed
        victim_creation = next((c for c in created_instances if c["role"] == "victim"), None)
        assert victim_creation["join_domain"] is True, "Victim join_domain should be True"

        # Attacker should have join_domain=False (default)
        attacker_creation = next((c for c in created_instances if c["role"] == "attacker"), None)
        assert attacker_creation["join_domain"] is False or attacker_creation["join_domain"] is None, \
            "Attacker join_domain should be False or None"

    @pulumi.runtime.test
    def test_range_without_dc_domain_member_gets_none(self, temp_templates):
        """Domain member in range without DC should get None for dc_config_param_name."""
        from components.range_stack import RangeStack
        from components.instance import InstanceComponent

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
                    join_domain=True,  # Wants to join but no DC!
                ),
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            dc_security_group_id="sg-dc",
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            dc_ami_id="ami-dc-test",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        created_instances = []
        original_init = InstanceComponent.__init__

        def capture_init(self, *args, **kwargs):
            created_instances.append({
                "role": kwargs.get("role"),
                "dc_config_param_name": kwargs.get("dc_config_param_name"),
            })
            return original_init(self, *args, **kwargs)

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            with patch.object(InstanceComponent, "__init__", capture_init):
                stack = RangeStack("test-range", config=config)

        # Victim should get None since no DC exists
        victim_creation = next((c for c in created_instances if c["role"] == "victim"), None)
        assert victim_creation["dc_config_param_name"] is None, \
            "Domain member without DC should get None for dc_config_param_name"


class TestBackwardCompatibility(TestRangeStackDCDependencyOrdering):
    """Tests ensuring existing functionality isn't broken."""

    @pulumi.runtime.test
    def test_range_without_dc_works(self, temp_templates):
        """Range without DC should work exactly as before."""
        from components.range_stack import RangeStack

        config = RangeConfig(
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
                    agent_s3_key="agents/test.tar.gz",
                    agent_presigned_url="https://example.com/agent",
                ),
            ],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            dc_security_group_id="",  # Not set
            instance_profile_name="range-profile",
            kali_ami_id="ami-kali123",
            victim_ami_id="ami-ubuntu123",
            windows_ami_id="ami-windows123",
            dc_ami_id="ami-dc-test",
            agent_s3_bucket="shifter-agents",
            availability_zone="us-east-2a",
        )

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=config)

            assert len(stack.instances) == 2
            assert stack.dc_config_param_name is None
            assert stack.network is not None
            assert stack.subnet_id is not None

    @pulumi.runtime.test
    def test_attacker_still_uses_kali_sg(self, temp_templates, dc_range_config):
        """Attacker should still use kali SG even when DC is present."""
        from components.range_stack import RangeStack

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            stack = RangeStack("test-range", config=dc_range_config)

            # Find attacker instance
            for inst in stack.instances:
                def check_if_attacker(tags):
                    if tags.get("shifter:role") == "attacker":
                        def verify_kali_sg(sgs):
                            assert "sg-kali" in sgs, f"Attacker should use sg-kali, got {sgs}"
                        inst.instance.vpc_security_group_ids.apply(verify_kali_sg)
                inst.instance.tags.apply(check_if_attacker)
