"""Ansible runner for NGFW configuration operations.

This module provides functions to run Ansible playbooks for NGFW provisioning
and deprovisioning, replacing the SSHExecutor/SetupOrchestrator approach.

Playbooks are stored in ansible/playbooks/ and use simple SSH connections
to send PAN-OS CLI commands.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Path to the Ansible playbooks directory
ANSIBLE_DIR = Path(__file__).parent / "ansible"
PLAYBOOKS_DIR = ANSIBLE_DIR / "playbooks"


def _write_inventory(
    management_ip: str,
    ssh_key_path: str,
    inventory_path: Path,
) -> None:
    """Write dynamic Ansible inventory file.

    Args:
        management_ip: NGFW management IP address
        ssh_key_path: Path to SSH private key file
        inventory_path: Path to write inventory file
    """
    inventory_content = f"""[ngfw]
{management_ip}

[ngfw:vars]
ansible_user=admin
ansible_ssh_private_key_file={ssh_key_path}
ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
"""
    inventory_path.write_text(inventory_content)
    logger.debug("Wrote inventory to %s", inventory_path)


def _write_ssh_key(private_key: str, key_path: Path) -> None:
    """Write SSH private key to file with proper permissions.

    Args:
        private_key: SSH private key content
        key_path: Path to write key file
    """
    key_path.write_text(private_key)
    key_path.chmod(0o600)
    logger.debug("Wrote SSH key to %s", key_path)


def _run_playbook(
    playbook_name: str,
    inventory_path: Path,
    extra_vars: dict[str, Any] | None = None,
    timeout_seconds: int = 1800,
) -> subprocess.CompletedProcess[str]:
    """Run an Ansible playbook.

    Args:
        playbook_name: Name of playbook file (e.g., 'ngfw_provision.yml')
        inventory_path: Path to inventory file
        extra_vars: Extra variables to pass to playbook
        timeout_seconds: Timeout for playbook execution

    Returns:
        Completed process result

    Raises:
        RuntimeError: If playbook fails
    """
    playbook_path = PLAYBOOKS_DIR / playbook_name
    if not playbook_path.exists():
        raise RuntimeError(f"Playbook not found: {playbook_path}")

    cmd = [
        "ansible-playbook",
        str(playbook_path),
        "-i",
        str(inventory_path),
        "-v",  # Verbose output
    ]

    # Add extra vars if provided
    if extra_vars:
        cmd.extend(["-e", json.dumps(extra_vars)])

    # Set environment with Ansible config
    env = {
        **os.environ,
        "ANSIBLE_CONFIG": str(ANSIBLE_DIR / "ansible.cfg"),
        "ANSIBLE_HOST_KEY_CHECKING": "False",
        "ANSIBLE_STDOUT_CALLBACK": "json",
    }

    logger.info("Running Ansible playbook: %s", playbook_name)
    logger.debug("Command: %s", " ".join(cmd))

    result = subprocess.run(  # noqa: S603
        cmd,
        cwd=str(ANSIBLE_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )

    if result.returncode != 0:
        logger.error("Ansible playbook failed: %s", result.stderr)
        logger.error("Ansible stdout: %s", result.stdout[:2000] if result.stdout else "")
        raise RuntimeError(f"Ansible playbook '{playbook_name}' failed: {result.stderr}")

    logger.info("Ansible playbook completed successfully")
    logger.debug("Ansible output: %s", result.stdout[:2000] if result.stdout else "")

    return result


def run_ngfw_provision(
    management_ip: str,
    private_key: str,
    sls_region: str = "americas",
    timeout_seconds: int = 1800,
) -> None:
    """Run NGFW provision playbook.

    Configures a newly provisioned NGFW with:
    - Data interface configuration
    - Shared zone creation
    - Cloud logging
    - Log forwarding profile
    - Security profiles
    - Threat content download and install

    Args:
        management_ip: NGFW management IP address
        private_key: SSH private key for authentication
        sls_region: Strata Logging Service region
        timeout_seconds: Timeout for playbook execution

    Raises:
        RuntimeError: If provisioning fails
    """
    logger.info("Starting NGFW provision via Ansible for %s", management_ip)

    # Create temp directory for inventory and key files
    with tempfile.TemporaryDirectory(prefix="ansible_ngfw_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        key_path = tmpdir_path / "ssh_key"
        inventory_path = tmpdir_path / "inventory"

        # Write SSH key and inventory
        _write_ssh_key(private_key, key_path)
        _write_inventory(management_ip, str(key_path), inventory_path)

        # Run playbook
        extra_vars = {
            "management_ip": management_ip,
            "sls_region": sls_region,
        }

        _run_playbook(
            playbook_name="ngfw_provision.yml",
            inventory_path=inventory_path,
            extra_vars=extra_vars,
            timeout_seconds=timeout_seconds,
        )

    logger.info("NGFW provision completed for %s", management_ip)


def run_ngfw_deprovision(
    management_ip: str,
    private_key: str,
    timeout_seconds: int = 300,
) -> None:
    """Run NGFW deprovision playbook.

    Cleans up before NGFW destruction:
    - Deactivates VM-Series license

    Args:
        management_ip: NGFW management IP address
        private_key: SSH private key for authentication
        timeout_seconds: Timeout for playbook execution

    Raises:
        RuntimeError: If deprovisioning fails (non-fatal, logged as warning)
    """
    logger.info("Starting NGFW deprovision via Ansible for %s", management_ip)

    # Create temp directory for inventory and key files
    with tempfile.TemporaryDirectory(prefix="ansible_ngfw_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        key_path = tmpdir_path / "ssh_key"
        inventory_path = tmpdir_path / "inventory"

        # Write SSH key and inventory
        _write_ssh_key(private_key, key_path)
        _write_inventory(management_ip, str(key_path), inventory_path)

        # Run playbook
        extra_vars = {
            "management_ip": management_ip,
        }

        try:
            _run_playbook(
                playbook_name="ngfw_deprovision.yml",
                inventory_path=inventory_path,
                extra_vars=extra_vars,
                timeout_seconds=timeout_seconds,
            )
        except RuntimeError as e:
            # Deprovision failures are non-fatal - log and continue
            logger.warning("NGFW deprovision failed (non-fatal): %s", e)
            return

    logger.info("NGFW deprovision completed for %s", management_ip)


def wait_for_ssh(
    management_ip: str,
    private_key: str,
    timeout_seconds: int = 3600,
    poll_interval: int = 30,
) -> None:
    """Wait for SSH to become available on NGFW.

    Polls the NGFW until SSH connection succeeds.

    Args:
        management_ip: NGFW management IP address
        private_key: SSH private key for authentication
        timeout_seconds: Maximum time to wait
        poll_interval: Seconds between attempts

    Raises:
        RuntimeError: If SSH is not available within timeout
    """
    import time

    logger.info("Waiting for SSH on NGFW at %s (timeout=%ds)", management_ip, timeout_seconds)

    start_time = time.time()

    # Create temp directory for key file
    with tempfile.TemporaryDirectory(prefix="ansible_ssh_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        key_path = tmpdir_path / "ssh_key"
        _write_ssh_key(private_key, key_path)

        while time.time() - start_time < timeout_seconds:
            try:
                # Try SSH connection with a simple command
                cmd = [
                    "ssh",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-o",
                    "ConnectTimeout=10",
                    "-o",
                    "BatchMode=yes",
                    "-i",
                    str(key_path),
                    f"admin@{management_ip}",
                    "show clock",
                ]

                result = subprocess.run(  # noqa: S603
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode == 0:
                    logger.info("SSH is available on %s", management_ip)
                    return

                logger.debug("SSH not ready yet: %s", result.stderr[:200] if result.stderr else "")

            except subprocess.TimeoutExpired:
                logger.debug("SSH connection timed out, retrying...")
            except Exception as e:
                logger.debug("SSH connection failed: %s", e)

            time.sleep(poll_interval)

    raise RuntimeError(f"SSH not available on {management_ip} after {timeout_seconds}s")
