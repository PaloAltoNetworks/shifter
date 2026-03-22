"""Shared test fixtures for Shifter Engine tests.

This module provides:
- Mocked database connections
- Mocked boto3 clients
- Sample configuration objects
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add parent directory to path so we can import the modules under test
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import InstanceConfig, RangeConfig, SubnetConfig

# =============================================================================
# Database Mocking
# =============================================================================


@pytest.fixture
def mock_db_connection(mocker):
    """Fixture providing a mocked psycopg database connection.

    Returns:
        MagicMock: Mocked connection with cursor support.
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    return mock_conn, mock_cursor


@pytest.fixture
def mock_psycopg_connect(mocker, mock_db_connection):
    """Fixture that patches psycopg.connect to return mock connection."""
    mock_conn, mock_cursor = mock_db_connection
    mock_connect = mocker.patch("psycopg.connect", return_value=mock_conn)
    return mock_connect, mock_conn, mock_cursor


# =============================================================================
# Boto3 Mocking
# =============================================================================


@pytest.fixture
def mock_boto3_clients(mocker):
    """Fixture providing mocked boto3 clients for RDS, S3, and Secrets Manager.

    Returns:
        dict: Dictionary of mocked clients.
    """
    # Mock RDS client
    mock_rds = MagicMock()
    mock_rds.generate_db_auth_token.return_value = "mock-auth-token"

    # Mock S3 client
    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned-url"

    # Mock Secrets Manager client (for SSH keys)
    mock_secretsmanager = MagicMock()
    mock_secretsmanager.get_secret_value.return_value = {
        "SecretString": "-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY\n-----END RSA PRIVATE KEY-----"
    }

    # Patch boto3.client to return appropriate mock
    def mock_client_factory(service_name, **kwargs):
        clients = {
            "rds": mock_rds,
            "s3": mock_s3,
            "secretsmanager": mock_secretsmanager,
        }
        return clients.get(service_name, MagicMock())

    mocker.patch("boto3.client", side_effect=mock_client_factory)

    return {"rds": mock_rds, "s3": mock_s3, "secretsmanager": mock_secretsmanager}


# =============================================================================
# Subprocess Mocking
# =============================================================================


@pytest.fixture
def mock_subprocess(mocker):
    """Fixture providing mocked subprocess.run.

    Returns:
        tuple: (mock_run, mock_result) for subprocess assertions.
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    mock_run = mocker.patch("subprocess.run", return_value=mock_result)
    return mock_run, mock_result


# =============================================================================
# Sample Configuration Fixtures
# =============================================================================


@pytest.fixture
def sample_instance_config_attacker():
    """Sample InstanceConfig for an attacker (Kali) instance."""
    return InstanceConfig(
        uuid="inst-uuid-attacker",
        name="attacker-kali",
        role="attacker",
        os_type="kali",
        instance_type="t3.small",
    )


@pytest.fixture
def sample_instance_config_victim():
    """Sample InstanceConfig for a Linux victim instance."""
    return InstanceConfig(
        uuid="inst-uuid-victim",
        name="target-ubuntu",
        role="victim",
        os_type="ubuntu",
        instance_type="t3.micro",
        agent_s3_key="agents/xdr-agent.tar.gz",
        agent_presigned_url="https://s3.example.com/agents/xdr-agent.tar.gz?signed",
    )


@pytest.fixture
def sample_instance_config_windows():
    """Sample InstanceConfig for a Windows victim instance."""
    return InstanceConfig(
        uuid="inst-uuid-windows",
        name="target-windows",
        role="victim",
        os_type="windows",
        instance_type="t3.medium",
        agent_s3_key="agents/xdr-agent.msi",
        agent_presigned_url="https://s3.example.com/agents/xdr-agent.msi?signed",
    )


@pytest.fixture
def sample_subnet_config_attack(sample_instance_config_attacker):
    """Sample SubnetConfig for an attack subnet."""
    return SubnetConfig(
        name="attack",
        uuid="subnet-uuid-attack-123",
        instances=[sample_instance_config_attacker],
        connected_to=["target"],
    )


@pytest.fixture
def sample_subnet_config_target(sample_instance_config_victim):
    """Sample SubnetConfig for a target subnet."""
    return SubnetConfig(
        name="target",
        uuid="subnet-uuid-target-456",
        instances=[sample_instance_config_victim],
        connected_to=[],
    )


@pytest.fixture
def sample_range_config(sample_subnet_config_attack, sample_subnet_config_target):
    """Sample RangeConfig with attack and target subnets."""
    return RangeConfig(
        range_id=42,
        user_id=1,
        request_uuid="request-uuid-12345",
        environment="dev",
        subnets=[sample_subnet_config_attack, sample_subnet_config_target],
        vpc_id="vpc-12345",
        vpc_cidr="10.1.0.0/16",
        route_table_id="rtb-12345",
        instance_profile_name="range-instance-profile",
        kali_ami_id="ami-kali123",
        victim_ami_id="ami-ubuntu123",
        windows_ami_id="ami-windows123",
        dc_ami_id="ami-dc-test",
        agent_s3_bucket="shifter-agents",
        availability_zone="us-east-2a",
        ngfw_data_eni_id="",
    )


@pytest.fixture
def sample_range_config_multi_subnet():
    """Sample RangeConfig with multiple subnets (cortex_byot-style)."""
    return RangeConfig(
        range_id=99,
        user_id=2,
        request_uuid="request-uuid-multi-67890",
        environment="prod",
        subnets=[
            SubnetConfig(
                name="attack",
                uuid="subnet-uuid-attack-multi",
                instances=[
                    InstanceConfig(
                        uuid="inst-uuid-001",
                        name="attacker-kali",
                        role="attacker",
                        os_type="kali",
                        instance_type="t3.small",
                    ),
                ],
                connected_to=["servers", "workstations"],
            ),
            SubnetConfig(
                name="servers",
                uuid="subnet-uuid-servers",
                instances=[
                    InstanceConfig(
                        uuid="inst-uuid-002",
                        name="target-ubuntu",
                        role="victim",
                        os_type="ubuntu",
                        instance_type="t3.micro",
                        agent_s3_key="agents/xdr.tar.gz",
                        agent_presigned_url="https://s3.example.com/1",
                    ),
                ],
                connected_to=["dc_network"],
            ),
            SubnetConfig(
                name="workstations",
                uuid="subnet-uuid-workstations",
                instances=[
                    InstanceConfig(
                        uuid="inst-uuid-003",
                        name="target-windows",
                        role="victim",
                        os_type="windows",
                        instance_type="t3.medium",
                        agent_s3_key="agents/xdr.msi",
                        agent_presigned_url="https://s3.example.com/2",
                    ),
                ],
                connected_to=["dc_network"],
            ),
            SubnetConfig(
                name="dc_network",
                uuid="subnet-uuid-dc",
                instances=[
                    InstanceConfig(
                        uuid="inst-uuid-004",
                        name="dc-windows",
                        role="dc",
                        os_type="windows",
                        instance_type="t3.large",
                    ),
                ],
                connected_to=[],
            ),
        ],
        vpc_id="vpc-prod",
        vpc_cidr="10.2.0.0/16",
        route_table_id="rtb-prod",
        instance_profile_name="prod-instance-profile",
        kali_ami_id="ami-kali-prod",
        victim_ami_id="ami-ubuntu-prod",
        windows_ami_id="ami-windows-prod",
        dc_ami_id="ami-dc-prod",
        agent_s3_bucket="shifter-agents-prod",
        availability_zone="us-east-2b",
        ngfw_data_eni_id="eni-ngfw123456789",
    )


# =============================================================================
# Template Testing Fixtures
# =============================================================================


@pytest.fixture
def temp_templates_dir():
    """Create a temporary directory with test templates.

    Yields:
        Path: Path to the temporary templates directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        templates_path = Path(tmpdir)

        # Create minimal test templates
        kali_template = templates_path / "kali.sh.j2"
        kali_template.write_text(
            """#!/bin/bash
set -euo pipefail
echo "Setting hostname to {{ hostname }}..."
hostnamectl set-hostname {{ hostname }}
echo "{{ public_key }}" >> /home/kali/.ssh/authorized_keys
echo "Kali setup complete"
"""
        )

        # Linux victim - MINIMAL, all setup via SSM plans
        linux_victim_template = templates_path / "victim_linux.sh.j2"
        linux_victim_template.write_text(
            """#!/bin/bash
set -euo pipefail
exec > >(tee /var/log/user-data.log) 2>&1
echo "Victim Linux instance booting..."
# All setup (hostname, SSH, XDR) is handled by SSM plans:
#   - LinuxBootstrapPlan: hostname + SSH configuration
#   - LinuxXDRAgentInstallPlan: XDR agent installation
echo "user_data complete. SSM will handle remaining setup."
"""
        )

        # Windows victim - MINIMAL, all setup via SSM plans
        windows_victim_template = templates_path / "victim_windows.ps1.j2"
        windows_victim_template.write_text(
            """<powershell>
$ErrorActionPreference = "Stop"
$LogFile = "C:\\Windows\\Temp\\userdata.log"
"Victim Windows instance booting..." | Out-File -FilePath $LogFile
# All setup (hostname, SSH, XDR) is handled by SSM plans:
#   - BootstrapPlan: hostname + SSH configuration
#   - XDRAgentInstallPlan: XDR agent installation
"user_data complete. SSM will handle remaining setup." | Out-File -Append -FilePath $LogFile
</powershell>
"""
        )

        # DC user_data is minimal - all setup via SSM (BootstrapPlan + DCSetupPlan)
        dc_template = templates_path / "dc_windows.ps1.j2"
        dc_template.write_text(
            """<powershell>
# Windows DC user_data - intentionally minimal
# All setup is handled via SSM Run Command orchestration:
#   1. BootstrapPlan: hostname + SSH configuration + reboot
#   2. DCSetupPlan: AD DS install + DC promotion + verification

$LogFile = "C:\\Windows\\Temp\\dc-userdata.log"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"$timestamp - DC instance started. Setup will be orchestrated via SSM." | Out-File -FilePath $LogFile
</powershell>
"""
        )

        # Domain member template for Windows instances joining a domain (Phase 7)
        domain_member_template = templates_path / "domain_member_windows.ps1.j2"
        domain_member_template.write_text(
            """<powershell>
$ErrorActionPreference = "Stop"
$LogFile = "C:\\Windows\\Temp\\domain-member-setup.log"
function Log-Message {
    param([string]$Message)
    Write-Host $Message
}
try {
    Log-Message "Setting hostname to {{ hostname }}..."
    Rename-Computer -NewName "{{ hostname }}" -Force
    Start-Service sshd
    Set-Service -Name sshd -StartupType Automatic
    {% if public_key %}
    $sshDir = "C:\\ProgramData\\ssh"
    "{{ public_key }}" | Out-File "$sshDir/administrators_authorized_keys"
    {% endif %}
    # Read DC config with retry
    $maxAttempts = 30
    $attempt = 0
    while ($attempt -lt $maxAttempts) {
        aws ssm get-parameter --name "{{ dc_config_param_name }}" --with-decryption
        $attempt++
    }
    Set-DnsClientServerAddress -InterfaceIndex 1 -ServerAddresses @($DcIp)
    {% if presigned_url %}
    $Action = New-ScheduledTaskAction -Execute "powershell.exe"
    Register-ScheduledTask -TaskName "DomainMember-PostRebootAgent" -Action $Action
    Invoke-WebRequest -Uri '{{ presigned_url }}' -OutFile $InstallerPath
    {% endif %}
    Add-Computer -DomainName $domain -Credential $cred -Restart -Force
} catch {
    Log-Message "ERROR: $_"
    throw
}
</powershell>
"""
        )

        yield templates_path


# =============================================================================
# Environment Variable Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def set_instance_type_env_vars(monkeypatch):
    """Set required instance type environment variables for all tests.

    These are required by config.py and catalog/instances.py.
    """
    monkeypatch.setenv("KALI_INSTANCE_TYPE", "t3.medium")
    monkeypatch.setenv("VICTIM_INSTANCE_TYPE", "t3.medium")


@pytest.fixture
def mock_env_vars(mocker):
    """Fixture providing mock environment variables for testing."""
    env_vars = {
        "DB_HOST": "test-db.example.com",
        "DB_PORT": "5432",
        "DB_NAME": "shifter",
        "DB_USER": "shifter_app",
        "AWS_REGION": "us-east-2",
        "ENVIRONMENT": "dev",
        "RANGE_VPC_ID": "vpc-test",
        "RANGE_VPC_CIDR": "10.1.0.0/16",
        "RANGE_ROUTE_TABLE_ID": "rtb-test",
        "RANGE_AVAILABILITY_ZONE": "us-east-2a",
        "KALI_SECURITY_GROUP_ID": "sg-kali-test",
        "VICTIM_SECURITY_GROUP_ID": "sg-victim-test",
        "DC_SECURITY_GROUP_ID": "sg-dc-test",
        "RANGE_INSTANCE_PROFILE_NAME": "test-profile",
        "KALI_AMI_ID": "ami-kali-test",
        "VICTIM_AMI_ID": "ami-victim-test",
        "WINDOWS_AMI_ID": "ami-windows-test",
        "DC_AMI_ID": "ami-dc-test",
        "AGENT_S3_BUCKET": "test-agents-bucket",
        "RANGE_ID": "42",
        "KALI_INSTANCE_TYPE": "t3.medium",
        "VICTIM_INSTANCE_TYPE": "t3.medium",
    }

    mocker.patch.dict(os.environ, env_vars, clear=False)
    return env_vars


@pytest.fixture
def mock_env_vars_minimal(mocker):
    """Fixture providing minimal required environment variables."""
    env_vars = {
        "DB_HOST": "test-db.example.com",
        "DB_NAME": "shifter",
        "DB_USER": "shifter_app",
        "AWS_REGION": "us-east-2",
        "KALI_INSTANCE_TYPE": "t3.medium",
        "VICTIM_INSTANCE_TYPE": "t3.medium",
    }
    mocker.patch.dict(os.environ, env_vars, clear=False)
    return env_vars


# =============================================================================
# Database Row Fixtures
# =============================================================================


@pytest.fixture
def sample_db_range_row():
    """Sample database row for a range with subnets (new format).

    Returns tuple matching get_range_from_db query:
    (id, user_id, uuid, range_config)
    """
    return (
        42,  # id
        1,  # user_id
        "request-uuid-12345",  # uuid
        {  # range_config
            "subnets": [
                {
                    "name": "attack",
                    "uuid": "subnet-uuid-attack",
                    "instances": [{"uuid": "inst-uuid-001", "role": "attacker", "os_type": "kali"}],
                    "connected_to": ["target"],
                },
                {
                    "name": "target",
                    "uuid": "subnet-uuid-target",
                    "instances": [
                        {
                            "uuid": "inst-uuid-002",
                            "role": "victim",
                            "os_type": "ubuntu",
                            "agent": {"s3_key": "agents/xdr-agent.tar.gz"},
                        }
                    ],
                    "connected_to": [],
                },
            ]
        },
    )


@pytest.fixture
def sample_db_range_row_with_ngfw():
    """Sample database row for a range with NGFW enabled (ngfw: true in range_config)."""
    return (
        42,  # id
        1,  # user_id
        "request-uuid-ngfw-12345",  # uuid
        {  # range_config
            "ngfw": True,  # Indicates NGFW scenario
            "subnets": [
                {
                    "name": "attack",
                    "uuid": "subnet-uuid-attack",
                    "instances": [{"uuid": "inst-uuid-001", "role": "attacker", "os_type": "kali"}],
                    "connected_to": ["target"],
                },
                {
                    "name": "target",
                    "uuid": "subnet-uuid-target",
                    "instances": [{"uuid": "inst-uuid-002", "role": "victim", "os_type": "ubuntu"}],
                    "connected_to": [],
                },
            ],
        },
    )


@pytest.fixture
def sample_db_range_row_no_agent():
    """Sample database row for a range without agent."""
    return (
        43,  # id
        2,  # user_id
        "request-uuid-no-agent",  # uuid
        {  # range_config
            "subnets": [
                {
                    "name": "attack",
                    "uuid": "subnet-uuid-attack-43",
                    "instances": [{"uuid": "inst-uuid-001", "role": "attacker", "os_type": "kali"}],
                    "connected_to": ["target"],
                },
                {
                    "name": "target",
                    "uuid": "subnet-uuid-target-43",
                    "instances": [{"uuid": "inst-uuid-002", "role": "victim", "os_type": "ubuntu"}],
                    "connected_to": [],
                },
            ]
        },
    )


@pytest.fixture
def sample_db_range_row_multi_subnet():
    """Sample database row for a range with 4 subnets (cortex_byot-style)."""
    return (
        44,  # id
        3,  # user_id
        "request-uuid-multi-subnet",  # uuid
        {  # range_config
            "ngfw": True,  # Indicates NGFW scenario
            "subnets": [
                {
                    "name": "attack",
                    "uuid": "subnet-uuid-attack-44",
                    "instances": [{"uuid": "inst-uuid-001", "role": "attacker", "os_type": "kali"}],
                    "connected_to": ["servers", "workstations"],
                },
                {
                    "name": "servers",
                    "uuid": "subnet-uuid-servers-44",
                    "instances": [
                        {
                            "uuid": "inst-uuid-002",
                            "role": "victim",
                            "os_type": "ubuntu",
                            "agent": {"s3_key": "agents/linux.tar.gz"},
                        },
                    ],
                    "connected_to": ["dc_network"],
                },
                {
                    "name": "workstations",
                    "uuid": "subnet-uuid-ws-44",
                    "instances": [
                        {
                            "uuid": "inst-uuid-003",
                            "role": "victim",
                            "os_type": "windows",
                            "agent": {"s3_key": "agents/windows.msi"},
                        },
                    ],
                    "connected_to": ["dc_network"],
                },
                {
                    "name": "dc_network",
                    "uuid": "subnet-uuid-dc-44",
                    "instances": [
                        {
                            "uuid": "inst-uuid-004",
                            "role": "dc",
                            "os_type": "windows",
                            "dc_config": {
                                "domain_name": "test.local",
                                "netbios_name": "TEST",
                            },
                        },
                    ],
                    "connected_to": [],
                },
            ],
        },
    )
