"""Range instance setup via Ansible playbooks over SSH."""

import json
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PLAYBOOKS_PATH = Path(__file__).parent / "ansible" / "playbooks"

# SSH wait defaults
SSH_WAIT_TIMEOUT_DEFAULT = 300
SSH_WAIT_INTERVAL = 15


def wait_for_ssh(
    host: str,
    user: str,
    private_key: str,
    timeout_seconds: int = SSH_WAIT_TIMEOUT_DEFAULT,
) -> None:
    """Wait for SSH to become available on a host."""
    logger.info("wait_for_ssh: host=%s user=%s timeout=%d", host, user, timeout_seconds)
    start_time = time.time()

    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "ssh_key"
        key_path.write_text(private_key)
        key_path.chmod(0o600)

        while time.time() - start_time < timeout_seconds:
            try:
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
                    f"{user}@{host}",
                    "echo ok",
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)  # noqa: S603
                if result.returncode == 0:
                    logger.info("wait_for_ssh: SSH available on %s", host)
                    return
            except subprocess.TimeoutExpired:
                pass
            except Exception as e:
                logger.debug("wait_for_ssh: attempt failed: %s", e)

            time.sleep(SSH_WAIT_INTERVAL)

        raise RuntimeError(f"Timeout waiting for SSH on {host}")


def run_dc_setup(
    host: str,
    user: str,
    private_key: str,
    xdr_agent_url: str = "",
) -> None:
    """Run DC setup playbook."""
    logger.info("run_dc_setup: host=%s", host)
    _run_playbook(
        playbook="range_dc_setup.yml",
        host=host,
        user=user,
        private_key=private_key,
        extra_vars={"xdr_agent_url": xdr_agent_url},
    )


def run_windows_setup(  # nosec B107 - empty string default means "no password", not hardcoded
    host: str,
    user: str,
    private_key: str,
    hostname: str,
    ssh_public_key: str,
    xdr_agent_url: str = "",
    join_domain: bool = False,
    domain_name: str = "",
    dc_ip: str = "",
    domain_admin_user: str = "",
    domain_admin_password: str = "",
) -> None:
    """Run Windows instance setup playbook."""
    logger.info("run_windows_setup: host=%s hostname=%s", host, hostname)
    _run_playbook(
        playbook="range_windows_setup.yml",
        host=host,
        user=user,
        private_key=private_key,
        extra_vars={
            "hostname": hostname,
            "ssh_public_key": ssh_public_key,
            "xdr_agent_url": xdr_agent_url,
            "join_domain": join_domain,
            "domain_name": domain_name,
            "dc_ip": dc_ip,
            "domain_admin_user": domain_admin_user,
            "domain_admin_password": domain_admin_password,
        },
    )


def run_linux_setup(
    host: str,
    user: str,
    private_key: str,
    hostname: str,
    ssh_public_key: str,
    ssh_user: str = "ubuntu",
    xdr_agent_url: str = "",
) -> None:
    """Run Linux instance setup playbook."""
    logger.info("run_linux_setup: host=%s hostname=%s", host, hostname)
    _run_playbook(
        playbook="range_linux_setup.yml",
        host=host,
        user=user,
        private_key=private_key,
        extra_vars={
            "hostname": hostname,
            "ssh_public_key": ssh_public_key,
            "ssh_user": ssh_user,
            "xdr_agent_url": xdr_agent_url,
        },
    )


def run_kali_setup(
    host: str,
    user: str,
    private_key: str,
    hostname: str,
    ssh_public_key: str,
) -> None:
    """Run Kali instance setup playbook."""
    logger.info("run_kali_setup: host=%s hostname=%s", host, hostname)
    _run_playbook(
        playbook="range_kali_setup.yml",
        host=host,
        user=user,
        private_key=private_key,
        extra_vars={
            "hostname": hostname,
            "ssh_public_key": ssh_public_key,
        },
    )


# NGFW configuration constants (same as plans/ngfw_provision.py)
ALERT_PROFILE_GROUP = "Alert-Group"


def _build_connected_pairs(subnets: list[dict]) -> list[tuple[str, str]]:
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


def _build_ngfw_configure_commands(
    subnets: list[dict],
    range_id: int,
    vpc_gateway_ip: str,
) -> str:
    """Build PAN-OS configure commands for routes, addresses and security rules.

    Args:
        subnets: List of dicts with 'name', 'cidr', and 'connected_to' keys.
        range_id: Range ID for unique naming.
        vpc_gateway_ip: VPC gateway IP address for static route next-hop.

    Returns:
        Multi-line string with configure commands and single commit.
    """
    lines = ["configure"]

    # Add static routes for each subnet (routes must exist for traffic to flow)
    for subnet in subnets:
        route_name = f"range-{range_id}-{subnet['name']}"
        cidr = subnet["cidr"]
        lines.append(
            f"set network virtual-router default routing-table ip static-route "
            f"{route_name} destination {cidr} interface ethernet1/1 "
            f"nexthop ip-address {vpc_gateway_ip}"
        )

    # Add address objects for each subnet
    for subnet in subnets:
        addr_name = f"range-{range_id}-{subnet['name']}"
        cidr = subnet["cidr"]
        lines.append(f"set address {addr_name} ip-netmask {cidr}")

    # Add bidirectional security rules for each connected pair
    # Rules use 'ranges' zone (created during NGFW provisioning)
    # Profile-group attaches alert-only threat detection
    for subnet_a, subnet_b in _build_connected_pairs(subnets):
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

    lines.append("commit")
    lines.append("exit")
    return "\n".join(lines)


def run_ngfw_configure_subnets(
    host: str,
    private_key: str,
    subnets: list[dict],
    range_id: int,
    vpc_gateway_ip: str,
    timeout_seconds: int = 300,
) -> None:
    """Configure NGFW subnets via SSH using PAN-OS CLI.

    Uses paramiko invoke_shell() for interactive PAN-OS CLI session.
    This is required because PAN-OS CLI is interactive, not command-based.

    Configures the NGFW with:
    - Static routes for each subnet (via VPC gateway)
    - Address objects for all subnets in a range
    - Security rules based on connected_to relationships (bidirectional)
      with ALERT_PROFILE_GROUP for threat detection without blocking

    Args:
        host: NGFW management IP
        private_key: SSH private key (PEM format)
        subnets: List of dicts with {name, cidr, connected_to}
        range_id: Range ID for unique naming
        vpc_gateway_ip: VPC gateway IP for static route next-hop
        timeout_seconds: Max time for command execution (default 300s)
    """
    logger.info(
        "run_ngfw_configure_subnets: host=%s subnets=%d range_id=%d",
        host,
        len(subnets),
        range_id,
    )

    # Build the PAN-OS configure commands
    configure_commands = _build_ngfw_configure_commands(subnets, range_id, vpc_gateway_ip)
    logger.debug("NGFW configure commands:\n%s", configure_commands)

    # Execute via SSH using paramiko invoke_shell (required for PAN-OS CLI)
    _run_panos_cli_commands(
        host=host,
        private_key=private_key,
        commands=configure_commands,
        timeout_seconds=timeout_seconds,
    )


def _run_panos_cli_commands(
    host: str,
    private_key: str,
    commands: str,
    timeout_seconds: int = 300,
) -> str:
    """Execute commands on PAN-OS CLI via SSH interactive shell.

    PAN-OS requires invoke_shell() because it's an interactive CLI,
    not a standard shell that accepts command-line arguments.

    Args:
        host: NGFW management IP
        private_key: SSH private key (PEM format)
        commands: Multi-line string of PAN-OS CLI commands
        timeout_seconds: Max time for command execution

    Returns:
        Command output from PAN-OS CLI

    Raises:
        RuntimeError: If SSH connection or command execution fails
    """
    import io

    import paramiko

    # Load private key (supports RSA and Ed25519)
    key_file = io.StringIO(private_key)
    try:
        pkey = paramiko.Ed25519Key.from_private_key(file_obj=key_file)
    except paramiko.SSHException:
        key_file.seek(0)
        try:
            pkey = paramiko.RSAKey.from_private_key(file_obj=key_file)
        except paramiko.SSHException as e:
            raise RuntimeError(f"Unsupported SSH key type: {e}") from e

    client = paramiko.SSHClient()
    # AutoAddPolicy is acceptable - we connect to freshly provisioned VMs in isolated VPCs
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507  # nosec B507

    try:
        logger.info("Connecting to PAN-OS at %s:22 as admin", host)
        client.connect(
            hostname=host,
            port=22,
            username="admin",
            pkey=pkey,
            timeout=30,
            allow_agent=False,
            look_for_keys=False,
        )

        # Open interactive shell (required for PAN-OS CLI)
        logger.info("Opening interactive shell with invoke_shell()")
        channel = client.invoke_shell()
        channel.settimeout(timeout_seconds)

        # Send commands via interactive shell
        # 1. Disable pager (essential for full output)
        # 2. Send all commands
        # 3. Send exit to cleanly close session
        logger.info("Sending commands to PAN-OS CLI...")
        channel.send("set cli pager off\n")
        channel.send(commands + "\n")
        channel.send("exit\n")
        channel.shutdown_write()

        # Read output until channel EOF (server finished sending)
        output = ""
        start_time = time.time()
        chunk_count = 0

        logger.info("Reading output until channel EOF")
        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk

            # Check for EOF (server finished sending all data)
            if channel.eof_received:
                logger.info("Channel EOF received - draining remaining data")
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    output += chunk
                break

            # Timeout check
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise RuntimeError(f"PAN-OS command timed out after {timeout_seconds}s")

            time.sleep(0.1)

        elapsed = time.time() - start_time
        logger.info("PAN-OS commands completed in %.1fs (%d bytes output)", elapsed, len(output))

        # Check for commit success in output
        if "commit" in commands.lower():
            if "Configuration committed successfully" in output:
                logger.info("PAN-OS commit succeeded")
            elif "commit failed" in output.lower() or "error" in output.lower():
                logger.error("PAN-OS commit may have failed. Output: %s", output[-500:])
                raise RuntimeError(f"PAN-OS commit failed: {output[-500:]}")

        return output

    except paramiko.SSHException as e:
        raise RuntimeError(f"SSH connection to {host} failed: {e}") from e
    finally:
        client.close()


def _run_playbook(
    playbook: str,
    host: str,
    user: str,
    private_key: str,
    extra_vars: dict[str, Any],
) -> None:
    """Run an Ansible playbook against a host via SSH."""
    playbook_path = PLAYBOOKS_PATH / playbook
    if not playbook_path.exists():
        raise FileNotFoundError(f"Playbook not found: {playbook_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Write SSH key
        key_path = tmpdir_path / "ssh_key"
        key_path.write_text(private_key)
        key_path.chmod(0o600)

        # Write inventory
        inventory = {
            "all": {
                "hosts": {
                    host: {
                        "ansible_user": user,
                        "ansible_ssh_private_key_file": str(key_path),
                        "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
                    }
                }
            }
        }
        inventory_path = tmpdir_path / "inventory.json"
        inventory_path.write_text(json.dumps(inventory))

        # Write extra vars
        vars_path = tmpdir_path / "vars.json"
        vars_path.write_text(json.dumps(extra_vars))

        cmd = [
            "ansible-playbook",
            "-i",
            str(inventory_path),
            "-e",
            f"@{vars_path}",
            str(playbook_path),
            "-v",
        ]

        logger.info("Running playbook %s for host %s", playbook, host)
        logger.debug("Command: %s", " ".join(cmd))

        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,
        )

        if result.returncode != 0:
            logger.error("Playbook failed stdout=%s stderr=%s", result.stdout, result.stderr)
            raise RuntimeError(f"Playbook {playbook} failed: {result.stderr}")

        logger.info("Playbook %s completed for host %s", playbook, host)


def run_post_pulumi_range_setup(
    instances: list[dict],
    dc_domain_name: str | None = None,
    dc_domain_password: str | None = None,
    region: str = "us-east-2",
) -> None:
    """Run Ansible setup for all range instances after Pulumi completes.

    Handles orchestration order:
    1. DC instances first (if any)
    2. Non-domain-joining instances in parallel
    3. Domain-joining instances after DC is ready

    Args:
        instances: List of instance dicts from Pulumi outputs, each with:
            - uuid: Instance UUID
            - role: 'dc', 'attacker', or 'victim'
            - os: 'windows', 'ubuntu', 'amazon-linux', 'kali'
            - private_ip: Instance private IP
            - ssh_key_secret_arn: ARN of SSH key in Secrets Manager
            - hostname: (optional) Desired hostname
            - ssh_public_key: (optional) Public key to configure
            - xdr_agent_url: (optional) URL for XDR agent installer
            - join_domain: (optional) Whether to join domain
        dc_domain_name: Domain FQDN for domain-joined instances
        dc_domain_password: Domain admin password
        region: AWS region for Secrets Manager
    """
    import concurrent.futures

    import boto3

    # Get Secrets Manager client
    secrets_client = boto3.client("secretsmanager", region_name=region)

    def get_ssh_key(secret_arn: str) -> str:
        """Retrieve SSH private key from Secrets Manager."""
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        return response["SecretString"]

    # Separate instances by type
    dc_instances = [i for i in instances if i.get("role") == "dc"]
    non_dc_instances = [i for i in instances if i.get("role") != "dc"]

    # Further separate non-DC instances
    domain_join_instances = [i for i in non_dc_instances if i.get("join_domain")]
    non_domain_join_instances = [i for i in non_dc_instances if not i.get("join_domain")]

    def setup_dc(instance: dict) -> None:
        """Setup a DC instance."""
        host = instance["private_ip"]
        private_key = get_ssh_key(instance["ssh_key_secret_arn"])
        xdr_url = instance.get("xdr_agent_url", "")

        logger.info("Setting up DC instance: %s", host)
        wait_for_ssh(host=host, user="Administrator", private_key=private_key, timeout_seconds=600)
        run_dc_setup(
            host=host,
            user="Administrator",
            private_key=private_key,
            xdr_agent_url=xdr_url,
        )
        logger.info("DC setup complete: %s", host)

    def setup_instance(instance: dict, dc_ip: str | None = None) -> None:
        """Setup a non-DC instance."""
        host = instance["private_ip"]
        private_key = get_ssh_key(instance["ssh_key_secret_arn"])
        os_type = instance.get("os", "windows")
        hostname = instance.get("hostname", "")
        ssh_public_key = instance.get("ssh_public_key", "")
        xdr_url = instance.get("xdr_agent_url", "")
        join_domain = instance.get("join_domain", False)

        # Determine SSH user based on OS
        if os_type == "kali":
            ssh_user = "kali"
        elif os_type in ("ubuntu", "amazon-linux"):
            ssh_user = "ubuntu" if os_type == "ubuntu" else "ec2-user"
        else:
            ssh_user = "Administrator"

        logger.info("Setting up %s instance: %s (os=%s)", instance.get("role"), host, os_type)
        wait_for_ssh(host=host, user=ssh_user, private_key=private_key, timeout_seconds=300)

        if os_type == "kali":
            run_kali_setup(
                host=host,
                user=ssh_user,
                private_key=private_key,
                hostname=hostname,
                ssh_public_key=ssh_public_key,
            )
        elif os_type in ("ubuntu", "amazon-linux"):
            run_linux_setup(
                host=host,
                user=ssh_user,
                private_key=private_key,
                hostname=hostname,
                ssh_public_key=ssh_public_key,
                ssh_user=ssh_user,
                xdr_agent_url=xdr_url,
            )
        else:
            # Windows
            run_windows_setup(
                host=host,
                user=ssh_user,
                private_key=private_key,
                hostname=hostname,
                ssh_public_key=ssh_public_key,
                xdr_agent_url=xdr_url,
                join_domain=join_domain and dc_ip is not None,
                domain_name=dc_domain_name or "",
                dc_ip=dc_ip or "",
                domain_admin_user="Administrator",
                domain_admin_password=dc_domain_password or "",
            )
        logger.info("Instance setup complete: %s", host)

    # 1. Setup DC instances first
    dc_ip = None
    for dc in dc_instances:
        setup_dc(dc)
        dc_ip = dc["private_ip"]  # Use last DC's IP for domain join

    # 2. Setup non-domain-joining instances in parallel
    if non_domain_join_instances:
        logger.info("Setting up %d non-domain-joining instances in parallel", len(non_domain_join_instances))
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(setup_instance, inst) for inst in non_domain_join_instances]
            errors = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error("Instance setup failed: %s", e)
                    errors.append(e)
            if errors:
                raise RuntimeError(f"Instance setup failed for {len(errors)} instances: {errors[0]}")

    # 3. Setup domain-joining instances in parallel (after DC is ready)
    if domain_join_instances and dc_ip:
        logger.info("Setting up %d domain-joining instances in parallel", len(domain_join_instances))
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(setup_instance, inst, dc_ip) for inst in domain_join_instances]
            errors = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error("Domain-joining instance setup failed: %s", e)
                    errors.append(e)
            if errors:
                raise RuntimeError(f"Domain-joining instance setup failed for {len(errors)} instances: {errors[0]}")

    logger.info("All instance setup complete (%d total)", len(instances))
