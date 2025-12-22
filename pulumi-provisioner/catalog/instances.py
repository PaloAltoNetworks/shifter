"""Instance type catalog for Shifter range provisioning.

This module defines the available instance types and their configurations.
Add new OS types here to extend the platform's capabilities.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class InstanceType:
    """Configuration for an instance type."""

    name: str
    role: str  # "attacker" or "victim"
    default_instance_type: str
    user_data_template: str
    description: str
    ami_lookup: Optional[dict] = None  # For dynamic AMI lookup
    requires_agent: bool = False
    ssh_user: str = "ubuntu"  # Default SSH user for the OS


# Instance type catalog - add new OS types here
INSTANCE_CATALOG: dict[str, InstanceType] = {
    "kali-2024": InstanceType(
        name="kali-2024",
        role="attacker",
        default_instance_type="t3.small",
        user_data_template="kali.sh.j2",
        description="Kali Linux with kali-linux-headless tools",
        ami_lookup={"name": "kali-linux-*", "owner": "679593333241"},
        requires_agent=False,
        ssh_user="kali",
    ),
    "ubuntu-22.04-victim": InstanceType(
        name="ubuntu-22.04-victim",
        role="victim",
        default_instance_type="t3.micro",
        user_data_template="victim_linux.sh.j2",
        description="Ubuntu 22.04 LTS victim with XDR agent",
        ami_lookup={
            "name": "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*",
            "owner": "099720109477",
        },
        requires_agent=True,
        ssh_user="ubuntu",
    ),
    "ubuntu-24.04-victim": InstanceType(
        name="ubuntu-24.04-victim",
        role="victim",
        default_instance_type="t3.micro",
        user_data_template="victim_linux.sh.j2",
        description="Ubuntu 24.04 LTS victim with XDR agent",
        ami_lookup={
            "name": "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*",
            "owner": "099720109477",
        },
        requires_agent=True,
        ssh_user="ubuntu",
    ),
    "windows-server-2022-victim": InstanceType(
        name="windows-server-2022-victim",
        role="victim",
        default_instance_type="t3.medium",
        user_data_template="victim_windows.ps1.j2",
        description="Windows Server 2022 victim with XDR agent",
        ami_lookup={
            "name": "Windows_Server-2022-English-Full-Base-*",
            "owner": "amazon",
        },
        requires_agent=True,
        ssh_user="Administrator",  # For RDP/WinRM
    ),
    "amazon-linux-2023-victim": InstanceType(
        name="amazon-linux-2023-victim",
        role="victim",
        default_instance_type="t3.micro",
        user_data_template="victim_linux.sh.j2",
        description="Amazon Linux 2023 victim with XDR agent",
        ami_lookup={
            "name": "al2023-ami-*-x86_64",
            "owner": "amazon",
        },
        requires_agent=True,
        ssh_user="ec2-user",
    ),
}


def get_instance_type(name: str) -> Optional[InstanceType]:
    """Get instance type configuration by name.

    Args:
        name: Instance type name (e.g., "kali-2024", "ubuntu-22.04-victim").

    Returns:
        InstanceType configuration or None if not found.
    """
    return INSTANCE_CATALOG.get(name)


def get_available_instance_types() -> list[str]:
    """Get list of available instance type names.

    Returns:
        List of instance type names.
    """
    return list(INSTANCE_CATALOG.keys())


def get_attacker_types() -> list[str]:
    """Get list of available attacker instance type names.

    Returns:
        List of attacker instance type names.
    """
    return [name for name, cfg in INSTANCE_CATALOG.items() if cfg.role == "attacker"]


def get_victim_types() -> list[str]:
    """Get list of available victim instance type names.

    Returns:
        List of victim instance type names.
    """
    return [name for name, cfg in INSTANCE_CATALOG.items() if cfg.role == "victim"]
