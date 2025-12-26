"""Instance component tests for Pulumi provisioner.

These tests use Pulumi's mocking framework to exercise InstanceComponent
without making AWS API calls. Tests verify SSH keys, Secrets Manager resources,
EC2 instance configuration, and user data behavior.
"""

import base64
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the real functions and classes we're testing
from components.instance import generate_ssh_keypair, validate_s3_path


class TestGenerateSshKeypair:
    """Tests for the generate_ssh_keypair function."""

    def test_returns_tuple_of_two_strings(self):
        """generate_ssh_keypair should return (private_key, public_key) tuple."""
        private_key, public_key = generate_ssh_keypair()

        assert isinstance(private_key, str)
        assert isinstance(public_key, str)

    def test_private_key_is_pem_format(self):
        """Private key should be in OpenSSH PEM format."""
        private_key, _ = generate_ssh_keypair()

        assert private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert private_key.strip().endswith("-----END OPENSSH PRIVATE KEY-----")

    def test_public_key_is_openssh_format(self):
        """Public key should be in OpenSSH format (ssh-ed25519 ...)."""
        _, public_key = generate_ssh_keypair()

        assert public_key.startswith("ssh-ed25519 ")

    def test_keys_are_unique_each_call(self):
        """Each call should generate a unique keypair."""
        key1_private, key1_public = generate_ssh_keypair()
        key2_private, key2_public = generate_ssh_keypair()

        assert key1_private != key2_private
        assert key1_public != key2_public

    def test_keypair_is_valid_ed25519(self):
        """Generated keypair should be valid Ed25519."""
        from cryptography.hazmat.primitives.serialization import (
            load_ssh_private_key,
            load_ssh_public_key,
        )

        private_key_pem, public_key_openssh = generate_ssh_keypair()

        # Load and verify private key
        private_key = load_ssh_private_key(
            private_key_pem.encode(), password=None
        )
        assert private_key is not None

        # Verify public key can be loaded
        public_key = load_ssh_public_key(public_key_openssh.encode())
        assert public_key is not None

    def test_private_key_has_no_passphrase(self):
        """Private key should not be encrypted (no passphrase)."""
        from cryptography.hazmat.primitives.serialization import load_ssh_private_key

        private_key_pem, _ = generate_ssh_keypair()

        # This should succeed without a password
        private_key = load_ssh_private_key(
            private_key_pem.encode(), password=None
        )
        assert private_key is not None


class TestValidateS3Path:
    """Tests for the validate_s3_path function."""

    def test_valid_simple_key(self):
        """Simple alphanumeric path should be valid."""
        assert validate_s3_path("agents/installer.sh") is True

    def test_valid_key_with_dashes(self):
        """Path with dashes should be valid."""
        assert validate_s3_path("my-bucket/my-key.tar.gz") is True

    def test_valid_key_with_underscores(self):
        """Path with underscores should be valid."""
        assert validate_s3_path("my_bucket/my_key.zip") is True

    def test_valid_key_with_dots(self):
        """Path with dots should be valid."""
        assert validate_s3_path("path/file.tar.gz") is True

    def test_valid_key_with_equals(self):
        """Path with equals sign should be valid (S3 metadata)."""
        assert validate_s3_path("path/file=value") is True

    def test_invalid_key_with_semicolon(self):
        """Semicolon (shell command separator) should be rejected."""
        assert validate_s3_path("; rm -rf /") is False

    def test_invalid_key_with_backtick(self):
        """Backtick (command substitution) should be rejected."""
        assert validate_s3_path("`whoami`") is False

    def test_invalid_key_with_dollar_paren(self):
        """Dollar-paren (command substitution) should be rejected."""
        assert validate_s3_path("$(command)") is False

    def test_invalid_key_with_pipe(self):
        """Pipe (command chaining) should be rejected."""
        assert validate_s3_path("file | cat") is False

    def test_invalid_key_with_ampersand(self):
        """Ampersand (command chaining) should be rejected."""
        assert validate_s3_path("file && rm") is False

    def test_invalid_key_with_newline(self):
        """Newline (command injection) should be rejected."""
        assert validate_s3_path("file\nrm -rf /") is False

    def test_invalid_key_with_space(self):
        """Space should be rejected (unsafe in shell)."""
        assert validate_s3_path("file with space") is False

    def test_empty_string_returns_false(self):
        """Empty string should return False."""
        assert validate_s3_path("") is False

    def test_valid_nested_path(self):
        """Deeply nested path should be valid."""
        assert validate_s3_path("a/b/c/d/e/file.tar.gz") is True


class TestInstanceComponentWithPulumiMocks:
    """Tests for InstanceComponent using Pulumi runtime mocks.

    These tests verify that the component creates resources correctly
    by using Pulumi's mocking framework.
    """

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_creates_secrets_manager_secret(self, temp_templates):
        """InstanceComponent should create a Secrets Manager secret."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-instance",
                range_id=42,
                user_id=1,
                index=0,
                role="attacker",
                os_type="kali",
                instance_type="t3.small",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
            )

            # Verify secret was created
            assert component.ssh_key_secret is not None
            assert component.ssh_key_secret_arn is not None

    @pulumi.runtime.test
    def test_creates_ec2_instance(self, temp_templates):
        """InstanceComponent should create an EC2 instance."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-instance",
                range_id=42,
                user_id=1,
                index=0,
                role="attacker",
                os_type="kali",
                instance_type="t3.small",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
            )

            # Verify instance was created
            assert component.instance is not None
            assert component.instance_id is not None
            assert component.private_ip is not None

    @pulumi.runtime.test
    def test_secret_naming_without_index(self, temp_templates):
        """First instance (index=0) should not have index in secret name."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-instance",
                range_id=42,
                user_id=1,
                index=0,
                role="attacker",
                os_type="kali",
                instance_type="t3.small",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
            )

            # Check the secret name pattern in the mock
            def check_secret_name(name):
                assert "attacker-ssh-key" in name
                assert "-0-" not in name  # No index suffix for index=0

            component.ssh_key_secret.name.apply(check_secret_name)

    @pulumi.runtime.test
    def test_secret_naming_with_index(self, temp_templates):
        """Non-first instance (index>0) should have index in secret name."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-instance",
                range_id=42,
                user_id=1,
                index=2,
                role="victim",
                os_type="ubuntu",
                instance_type="t3.micro",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
            )

            def check_secret_name(name):
                assert "victim-2-ssh-key" in name

            component.ssh_key_secret.name.apply(check_secret_name)

    @pulumi.runtime.test
    def test_instance_profile_attached_when_provided(self, temp_templates):
        """Instance should have IAM profile when instance_profile_name is set."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-instance",
                range_id=42,
                user_id=1,
                index=0,
                role="attacker",
                os_type="kali",
                instance_type="t3.small",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
                instance_profile_name="my-profile",
            )

            def check_profile(profile):
                assert profile == "my-profile"

            component.instance.iam_instance_profile.apply(check_profile)

    @pulumi.runtime.test
    def test_to_output_dict_returns_expected_keys(self, temp_templates):
        """to_output_dict should return dict with instance_id, private_ip, ssh_key_secret_arn."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-instance",
                range_id=42,
                user_id=1,
                index=0,
                role="attacker",
                os_type="kali",
                instance_type="t3.small",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
            )

            output_dict = component.to_output_dict()

            assert "instance_id" in output_dict
            assert "private_ip" in output_dict
            assert "ssh_key_secret_arn" in output_dict


class TestDCInstanceComponent:
    """Tests for DC (Domain Controller) instance component functionality."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_dc_instance_creates_config_parameter(self, temp_templates):
        """DC instance should create an SSM Parameter for DC config."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-dc",
                range_id=42,
                user_id=1,
                index=0,
                role="dc",
                os_type="windows",
                instance_type="t3.large",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
                dc_config={"domain_name": "internal.shifter", "netbios_name": "SHIFTER"},
            )

            # Verify SSM Parameter was created
            assert hasattr(component, "dc_config_param")
            assert component.dc_config_param is not None

    @pulumi.runtime.test
    def test_dc_instance_parameter_path_scoped_to_range(self, temp_templates):
        """DC config parameter should be scoped to the specific range."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-dc",
                range_id=42,
                user_id=1,
                index=0,
                role="dc",
                os_type="windows",
                instance_type="t3.large",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
                dc_config={"domain_name": "internal.shifter", "netbios_name": "SHIFTER"},
            )

            # Parameter name should follow pattern: /shifter/{env}/range/{range_id}/dc-config
            assert component.dc_config_param_name == "/shifter/dev/range/42/dc-config"

    @pulumi.runtime.test
    def test_dc_instance_generates_dsrm_password(self, temp_templates):
        """DC instance should generate DSRM password."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-dc",
                range_id=42,
                user_id=1,
                index=0,
                role="dc",
                os_type="windows",
                instance_type="t3.large",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
                dc_config={"domain_name": "internal.shifter", "netbios_name": "SHIFTER"},
            )

            # DSRM password should be generated
            assert hasattr(component, "dsrm_password")
            assert component.dsrm_password is not None
            assert len(component.dsrm_password) >= 16

    @pulumi.runtime.test
    def test_dc_instance_stores_config_for_orchestration(self, temp_templates):
        """DC instance should store config for SSM orchestration.

        NOTE: DC user data is now a minimal bootstrap script.
        AD DS setup (domain_name, netbios_name) is handled via SSM.
        """
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-dc",
                range_id=42,
                user_id=1,
                index=0,
                role="dc",
                os_type="windows",
                instance_type="t3.large",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
                dc_config={"domain_name": "internal.shifter", "netbios_name": "SHIFTER"},
            )

            # DC config should be stored on component for SSM orchestration
            assert component.domain_name == "internal.shifter"
            assert component.netbios_name == "SHIFTER"
            assert component.dsrm_password is not None
            assert component.domain_admin_password is not None
            assert component.hostname == "shifter-dc-42"
            assert component.public_key is not None  # Stored for BootstrapPlan

            # User data should be minimal - all setup via SSM
            def check_user_data(user_data_b64):
                import base64

                user_data = base64.b64decode(user_data_b64).decode()
                # Minimal template just logs that SSM will handle setup
                assert "SSM" in user_data
                # Should NOT have any setup logic (hostname, SSH, AD DS)
                assert "Rename-Computer" not in user_data
                assert "Start-Service sshd" not in user_data
                assert "Install-WindowsFeature" not in user_data
                assert "Install-ADDSForest" not in user_data

            component.instance.user_data_base64.apply(check_user_data)

    @pulumi.runtime.test
    def test_victim_instance_unchanged(self, temp_templates):
        """Existing victim instance behavior should be unchanged."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            victim = InstanceComponent(
                name="test-victim",
                range_id=42,
                user_id=1,
                index=0,
                role="victim",
                os_type="ubuntu",
                instance_type="t3.small",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
            )

            # Victim should NOT have DC config parameter
            assert not hasattr(victim, "dc_config_param") or victim.dc_config_param is None
            assert not hasattr(victim, "dsrm_password") or victim.dsrm_password is None


class TestUserDataGeneration:
    """Tests for user data generation - verify templates are rendered correctly."""

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory."""
        return temp_templates_dir

    @pulumi.runtime.test
    def test_attacker_uses_kali_template(self, temp_templates, pulumi_mocks):
        """Attacker role should use kali.sh.j2 template."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-attacker",
                range_id=42,
                user_id=1,
                index=0,
                role="attacker",
                os_type="kali",
                instance_type="t3.small",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
            )

            def check_user_data(user_data_b64):
                user_data = base64.b64decode(user_data_b64).decode()
                assert "Kali setup complete" in user_data

            component.instance.user_data_base64.apply(check_user_data)

    @pulumi.runtime.test
    def test_linux_victim_uses_linux_template(self, temp_templates, pulumi_mocks):
        """Linux victim should use victim_linux.sh.j2 template."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-victim",
                range_id=42,
                user_id=1,
                index=0,
                role="victim",
                os_type="ubuntu",
                instance_type="t3.micro",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
            )

            def check_user_data(user_data_b64):
                user_data = base64.b64decode(user_data_b64).decode()
                assert "Victim setup complete" in user_data
                assert "#!/bin/bash" in user_data

            component.instance.user_data_base64.apply(check_user_data)

    @pulumi.runtime.test
    def test_windows_victim_uses_windows_template(self, temp_templates, pulumi_mocks):
        """Windows victim should use victim_windows.ps1.j2 template."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-windows",
                range_id=42,
                user_id=1,
                index=0,
                role="victim",
                os_type="windows",
                instance_type="t3.medium",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
            )

            def check_user_data(user_data_b64):
                user_data = base64.b64decode(user_data_b64).decode()
                assert "Windows setup complete" in user_data
                assert "<powershell>" in user_data

            component.instance.user_data_base64.apply(check_user_data)

    @pulumi.runtime.test
    def test_agent_presigned_url_in_user_data(self, temp_templates, pulumi_mocks):
        """Agent presigned URL should appear in victim user data."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = InstanceComponent(
                name="test-victim",
                range_id=42,
                user_id=1,
                index=0,
                role="victim",
                os_type="ubuntu",
                instance_type="t3.micro",
                subnet_id="subnet-12345",
                security_group_id="sg-12345",
                ami_id="ami-12345",
                environment="dev",
                agent_presigned_url="https://s3.example.com/signed-agent-url",
                agent_s3_key="agents/xdr.tar.gz",
            )

            def check_user_data(user_data_b64):
                user_data = base64.b64decode(user_data_b64).decode()
                assert "https://s3.example.com/signed-agent-url" in user_data

            component.instance.user_data_base64.apply(check_user_data)

    def test_invalid_s3_key_raises_valueerror(self, temp_templates, pulumi_mocks):
        """Invalid S3 key with shell injection chars should raise ValueError."""
        from components.instance import InstanceComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            with pytest.raises(ValueError) as exc_info:
                InstanceComponent(
                    name="test-victim",
                    range_id=42,
                    user_id=1,
                    index=0,
                    role="victim",
                    os_type="ubuntu",
                    instance_type="t3.micro",
                    subnet_id="subnet-12345",
                    security_group_id="sg-12345",
                    ami_id="ami-12345",
                    environment="dev",
                    agent_s3_key="; rm -rf /",  # Shell injection attempt
                )

            assert "shell injection" in str(exc_info.value).lower()
