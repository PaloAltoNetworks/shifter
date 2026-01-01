"""Shared test fixtures for Shifter Engine tests.

This module provides:
- Pulumi runtime mocks for component tests
- Mocked database connections
- Mocked boto3 clients
- Sample configuration objects
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Add parent directory to path so we can import the modules under test
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import InstanceConfig, RangeConfig


# =============================================================================
# Pulumi Mocking Infrastructure
# =============================================================================


class PulumiMocks:
    """Mock implementation for Pulumi runtime.

    This class implements the Pulumi mock interface to simulate AWS resource
    creation without making actual API calls.
    """

    def __init__(self):
        self.resources = {}
        self.calls = []

    def new_resource(
        self,
        args: Any,
    ) -> tuple[str, dict]:
        """Mock resource creation.

        Args:
            args: Pulumi MockResourceArgs containing type_, name, inputs, etc.

        Returns:
            Tuple of (resource_id, outputs).
        """
        resource_type = args.typ
        name = args.name
        inputs = args.inputs

        # Generate mock ID
        resource_id = f"{name}-mock-id"

        # Store resource for inspection
        self.resources[name] = {
            "type": resource_type,
            "inputs": inputs,
            "id": resource_id,
        }

        # Return appropriate outputs based on resource type
        outputs = {"id": resource_id}

        if resource_type == "aws:ec2/subnet:Subnet":
            outputs["cidrBlock"] = inputs.get("cidrBlock", "10.1.1.0/24")
            outputs["vpcId"] = inputs.get("vpcId", "vpc-mock")
            outputs["availabilityZone"] = inputs.get("availabilityZone", "us-east-2a")

        elif resource_type == "aws:ec2/instance:Instance":
            outputs["privateIp"] = "10.1.1.100"
            outputs["publicIp"] = ""
            outputs["instanceType"] = inputs.get("instanceType", "t3.micro")
            outputs["ami"] = inputs.get("ami", "ami-mock")
            outputs["tags"] = inputs.get("tags", {})

        elif resource_type == "aws:secretsmanager/secret:Secret":
            outputs["arn"] = f"arn:aws:secretsmanager:us-east-2:123456789012:secret:{name}"
            outputs["name"] = inputs.get("name", name)

        elif resource_type == "aws:secretsmanager/secretVersion:SecretVersion":
            outputs["arn"] = f"arn:aws:secretsmanager:us-east-2:123456789012:secret:{name}"
            outputs["versionId"] = "mock-version-id"

        elif resource_type == "aws:ec2/routeTableAssociation:RouteTableAssociation":
            outputs["subnetId"] = inputs.get("subnetId", "subnet-mock")
            outputs["routeTableId"] = inputs.get("routeTableId", "rtb-mock")

        elif resource_type == "aws:ssm/parameter:Parameter":
            param_name = inputs.get("name", f"/mock/param/{name}")
            outputs["arn"] = f"arn:aws:ssm:us-east-2:123456789012:parameter{param_name}"
            outputs["name"] = param_name
            outputs["type"] = inputs.get("type", "String")
            outputs["value"] = inputs.get("value", "{}")

        elif resource_type == "aws:lb/loadBalancer:LoadBalancer":
            outputs["arn"] = f"arn:aws:elasticloadbalancing:us-east-2:123456789012:loadbalancer/gwy/{name}"
            outputs["dnsName"] = f"{name}.elb.us-east-2.amazonaws.com"
            outputs["loadBalancerType"] = inputs.get("loadBalancerType", "gateway")

        elif resource_type == "aws:lb/targetGroup:TargetGroup":
            outputs["arn"] = f"arn:aws:elasticloadbalancing:us-east-2:123456789012:targetgroup/{name}"
            outputs["protocol"] = inputs.get("protocol", "GENEVE")
            outputs["port"] = inputs.get("port", 6081)

        elif resource_type == "aws:lb/listener:Listener":
            outputs["arn"] = f"arn:aws:elasticloadbalancing:us-east-2:123456789012:listener/{name}"

        elif resource_type == "aws:ec2/vpcEndpointService:VpcEndpointService":
            outputs["serviceName"] = f"com.amazonaws.vpce.us-east-2.vpce-svc-{name[:8]}"
            outputs["acceptanceRequired"] = inputs.get("acceptanceRequired", True)

        elif resource_type == "aws:ec2/networkInterface:NetworkInterface":
            outputs["privateIp"] = inputs.get("privateIps", ["10.1.1.50"])[0] if inputs.get("privateIps") else "10.1.1.50"
            outputs["subnetId"] = inputs.get("subnetId", "subnet-mock")
            outputs["sourceDestCheck"] = inputs.get("sourceDestCheck", True)

        elif resource_type == "aws:s3/bucketObject:BucketObject":
            outputs["bucket"] = inputs.get("bucket", "mock-bucket")
            outputs["key"] = inputs.get("key", "mock-key")
            outputs["etag"] = "mock-etag-123"

        return resource_id, outputs

    def call(self, args: Any) -> dict:
        """Mock Pulumi function calls (e.g., aws.getAmi).

        Args:
            args: Pulumi MockCallArgs containing token and inputs.

        Returns:
            Dictionary of outputs.
        """
        token = args.token
        call_args = args.args

        self.calls.append({"token": token, "args": call_args})

        # Return appropriate outputs based on function
        if token == "aws:ec2/getAmi:getAmi":
            return {"id": "ami-mock-lookup", "name": "mock-ami"}

        return {}


@pytest.fixture
def pulumi_mocks():
    """Fixture that sets up Pulumi mocking for component tests.

    This fixture patches the Pulumi runtime to use our mock implementation,
    allowing tests to verify resource creation without actual AWS calls.

    Yields:
        PulumiMocks: The mock instance for assertions.
    """
    import pulumi

    mocks = PulumiMocks()
    pulumi.runtime.set_mocks(mocks, preview=False)
    yield mocks


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
    """Fixture providing mocked boto3 clients for RDS and S3.

    Returns:
        dict: Dictionary of mocked clients.
    """
    # Mock RDS client
    mock_rds = MagicMock()
    mock_rds.generate_db_auth_token.return_value = "mock-auth-token"

    # Mock S3 client
    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned-url"

    # Patch boto3.client to return appropriate mock
    def mock_client_factory(service_name, **kwargs):
        if service_name == "rds":
            return mock_rds
        elif service_name == "s3":
            return mock_s3
        return MagicMock()

    mocker.patch("boto3.client", side_effect=mock_client_factory)

    return {"rds": mock_rds, "s3": mock_s3}


# =============================================================================
# Subprocess Mocking
# =============================================================================


@pytest.fixture
def mock_subprocess(mocker):
    """Fixture providing a mocked subprocess.run.

    Returns:
        MagicMock: Mocked subprocess.run function.
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
        role="attacker",
        os_type="kali",
        instance_type="t3.small",
    )


@pytest.fixture
def sample_instance_config_victim():
    """Sample InstanceConfig for a Linux victim instance."""
    return InstanceConfig(
        role="victim",
        os_type="ubuntu",
        instance_type="t3.micro",
        agent_id=1,
        agent_s3_key="agents/xdr-agent.tar.gz",
        agent_presigned_url="https://s3.example.com/agents/xdr-agent.tar.gz?signed",
    )


@pytest.fixture
def sample_instance_config_windows():
    """Sample InstanceConfig for a Windows victim instance."""
    return InstanceConfig(
        role="victim",
        os_type="windows",
        instance_type="t3.medium",
        agent_id=2,
        agent_s3_key="agents/xdr-agent.msi",
        agent_presigned_url="https://s3.example.com/agents/xdr-agent.msi?signed",
    )


@pytest.fixture
def sample_range_config(sample_instance_config_attacker, sample_instance_config_victim):
    """Sample RangeConfig with one attacker and one victim."""
    return RangeConfig(
        range_id=42,
        user_id=1,
        subnet_index=5,
        environment="dev",
        instances=[sample_instance_config_attacker, sample_instance_config_victim],
        vpc_id="vpc-12345",
        vpc_cidr="10.1.0.0/16",
        route_table_id="rtb-12345",
        kali_security_group_id="sg-kali",
        victim_security_group_id="sg-victim",
        instance_profile_name="range-instance-profile",
        kali_ami_id="ami-kali123",
        victim_ami_id="ami-ubuntu123",
        windows_ami_id="ami-windows123",
        dc_ami_id="ami-dc-test",
        agent_s3_bucket="shifter-agents",
        availability_zone="us-east-2a",
    )


@pytest.fixture
def sample_range_config_multi_instance():
    """Sample RangeConfig with multiple attackers and victims."""
    return RangeConfig(
        range_id=99,
        user_id=2,
        subnet_index=10,
        environment="prod",
        instances=[
            InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
            InstanceConfig(role="attacker", os_type="kali", instance_type="t3.medium"),
            InstanceConfig(
                role="victim",
                os_type="ubuntu",
                instance_type="t3.micro",
                agent_id=1,
                agent_s3_key="agents/xdr.tar.gz",
                agent_presigned_url="https://s3.example.com/1",
            ),
            InstanceConfig(
                role="victim",
                os_type="windows",
                instance_type="t3.medium",
                agent_id=2,
                agent_s3_key="agents/xdr.msi",
                agent_presigned_url="https://s3.example.com/2",
            ),
        ],
        vpc_id="vpc-prod",
        vpc_cidr="10.2.0.0/16",
        route_table_id="rtb-prod",
        kali_security_group_id="sg-kali-prod",
        victim_security_group_id="sg-victim-prod",
        instance_profile_name="prod-instance-profile",
        kali_ami_id="ami-kali-prod",
        victim_ami_id="ami-ubuntu-prod",
        windows_ami_id="ami-windows-prod",
        dc_ami_id="ami-dc-prod",
        agent_s3_bucket="shifter-agents-prod",
        availability_zone="us-east-2b",
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
        "PULUMI_SECRETS_PROVIDER": "awskms://alias/test-pulumi-secrets",
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
    """Sample database row for a range with agent."""
    return (
        42,  # id
        1,  # user_id
        5,  # subnet_index
        1,  # agent_id
        None,  # instance_config (uses defaults)
        "agents/xdr-agent.tar.gz",  # agent_s3_key
    )


@pytest.fixture
def sample_db_range_row_no_agent():
    """Sample database row for a range without agent."""
    return (
        43,  # id
        2,  # user_id
        6,  # subnet_index
        None,  # agent_id
        None,  # instance_config
        None,  # agent_s3_key
    )


@pytest.fixture
def sample_db_range_row_custom_config():
    """Sample database row for a range with custom instance config."""
    return (
        44,  # id
        3,  # user_id
        7,  # subnet_index
        None,  # agent_id (per-instance)
        [
            {"role": "attacker", "os": "kali", "instance_type": "t3.medium"},
            {
                "role": "victim",
                "os": "ubuntu",
                "instance_type": "t3.small",
                "agent_id": 1,
                "agent_s3_key": "agents/custom.tar.gz",
            },
            {
                "role": "victim",
                "os": "windows",
                "instance_type": "t3.large",
                "agent_id": 2,
                "agent_s3_key": "agents/custom.msi",
            },
        ],
        None,  # agent_s3_key (per-instance)
    )


@pytest.fixture
def mock_pulumi_config(mocker):
    """Mock Pulumi Config object with required values for load_config tests."""
    mock_config = MagicMock()

    mock_config.require.side_effect = lambda key: {
        "environment": "dev",
        "rangeVpcId": "vpc-test123",
        "rangeVpcCidr": "10.1.0.0/16",
        "rangeRouteTableId": "rtb-test123",
        "kaliSecurityGroupId": "sg-kali-test",
        "victimSecurityGroupId": "sg-victim-test",
        "kaliAmiId": "ami-kali-test",
        "victimAmiId": "ami-victim-test",
        "availabilityZone": "us-east-2a",
    }.get(key, f"mock-{key}")

    mock_config.require_int.side_effect = lambda key: {
        "rangeId": 42,
    }.get(key, 0)

    mock_config.get.side_effect = lambda key: {
        "agentS3Bucket": "test-agents-bucket",
        "windowsAmiId": "ami-windows-test",
        "dcAmiId": "ami-dc-test",
        "dcSecurityGroupId": "sg-dc-test",
        "rangeInstanceProfileName": "test-profile",
        "portalVpcCidr": "10.0.0.0/16",
    }.get(key)

    mocker.patch("pulumi.Config", return_value=mock_config)
    return mock_config
